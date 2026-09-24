"""Cliente da Microsoft Graph API para ler e enviar emails da caixa de suporte."""

from __future__ import annotations

import logging
import time
from collections.abc import Callable, Iterable
from datetime import UTC, datetime
from typing import Any
from urllib.parse import quote

import httpx
import msal

from omnis_support.domain import IncomingEmail

logger = logging.getLogger(__name__)

GRAPH_BASE_URL = "https://graph.microsoft.com/v1.0"
GRAPH_SCOPE = "https://graph.microsoft.com/.default"
_RETRYABLE_STATUS = frozenset({429, 500, 502, 503, 504})
_MAX_RETRIES = 3
_PAGE_SIZE = 50
# IDs imutáveis não mudam quando alguém move o email de pasta no Outlook.
_IMMUTABLE_IDS = 'IdType="ImmutableId"'
_MESSAGE_FIELDS = (
    "id,conversationId,internetMessageId,subject,from,body,receivedDateTime,internetMessageHeaders"
)

TokenProvider = Callable[[], str]


class GraphApiError(RuntimeError):
    """Erro retornado pela Graph API."""


def msal_token_provider(tenant_id: str, client_id: str, client_secret: str) -> TokenProvider:
    """Obtém tokens de aplicativo (client credentials). O MSAL mantém o cache."""
    app = msal.ConfidentialClientApplication(
        client_id,
        authority=f"https://login.microsoftonline.com/{tenant_id}",
        client_credential=client_secret,
    )

    def provide() -> str:
        result = app.acquire_token_for_client(scopes=[GRAPH_SCOPE])
        if not result or "access_token" not in result:
            detail = (result or {}).get("error_description", result)
            raise GraphApiError(f"Falha ao autenticar na Graph API: {detail}")
        return str(result["access_token"])

    return provide


class GraphMailClient:
    """Operações de email sobre uma única caixa (a caixa de suporte)."""

    def __init__(
        self,
        mailbox: str,
        token_provider: TokenProvider,
        http_client: httpx.Client | None = None,
    ) -> None:
        self._mailbox = mailbox
        self._token_provider = token_provider
        self._http = http_client or httpx.Client(base_url=GRAPH_BASE_URL, timeout=30.0)

    # ------------------------------------------------------------------ leitura

    def fetch_received_since(self, since: datetime, limit: int) -> list[IncomingEmail]:
        """Retorna os emails da caixa de entrada recebidos a partir de `since`, lidos ou não.

        Não depende do status "lido": um email aberto por alguém no Outlook antes
        do agente rodar continua sendo atendido. O banco evita atendimentos duplicados.
        """
        path: str | None = f"{self._mailbox_path}/mailFolders/inbox/messages"
        params: dict[str, str] | None = {
            # A Graph exige que o campo do $orderby apareça no $filter.
            "$filter": f"receivedDateTime ge {_to_graph_datetime(since)}",
            "$orderby": "receivedDateTime asc",
            "$top": str(min(_PAGE_SIZE, limit)),
            "$select": _MESSAGE_FIELDS,
        }
        emails: list[IncomingEmail] = []
        while path and len(emails) < limit:
            page = self._request(
                "GET",
                path,
                params=params,
                headers={"Prefer": f'outlook.body-content-type="text", {_IMMUTABLE_IDS}'},
            ).json()
            emails.extend(_parse_message(item) for item in page.get("value", []))
            # O nextLink já traz todos os parâmetros da consulta.
            path, params = page.get("@odata.nextLink"), None
        return emails[:limit]

    # ------------------------------------------------------------------ escrita

    def reply(self, message_id: str, html_body: str) -> None:
        """Responde ao remetente no mesmo fio de conversa."""
        self._request(
            "POST",
            f"{self._message_path(message_id)}/reply",
            json={"message": {"body": {"contentType": "HTML", "content": html_body}}},
        )

    def forward(
        self,
        message_id: str,
        recipients: Iterable[str],
        subject: str,
        intro_html: str,
        reply_to: str,
    ) -> None:
        """Encaminha o email original, com anexos, definindo o cliente como Responder Para.

        Assim, quando a equipe clicar em "Responder", a resposta vai direto ao cliente.
        """
        draft = self._request(
            "POST",
            f"{self._message_path(message_id)}/createForward",
            json={"message": {"toRecipients": _recipients(recipients)}},
        ).json()
        draft_path = self._message_path(draft["id"])
        original_html = (draft.get("body") or {}).get("content", "")
        try:
            self._request(
                "PATCH",
                draft_path,
                json={
                    "subject": subject,
                    "replyTo": _recipients([reply_to]),
                    "body": {
                        "contentType": "HTML",
                        "content": _prepend_html(intro_html, original_html),
                    },
                },
            )
            self._request("POST", f"{draft_path}/send")
        except GraphApiError:
            self._discard_draft(draft_path)
            raise

    def mark_processed(self, message_id: str, label: str) -> None:
        """Marca como lido e aplica uma categoria visível no Outlook."""
        self._request(
            "PATCH",
            self._message_path(message_id),
            json={"isRead": True, "categories": [label]},
        )

    # ------------------------------------------------------------------ interno

    def _discard_draft(self, draft_path: str) -> None:
        """Remove o rascunho de um encaminhamento que falhou, para não acumular lixo."""
        try:
            self._request("DELETE", draft_path)
        except GraphApiError:
            logger.warning("Não foi possível remover o rascunho %s", draft_path)

    @property
    def _mailbox_path(self) -> str:
        return f"/users/{quote(self._mailbox, safe='')}"

    def _message_path(self, message_id: str) -> str:
        return f"{self._mailbox_path}/messages/{quote(message_id, safe='')}"

    def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, str] | None = None,
        json: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> httpx.Response:
        for attempt in range(1, _MAX_RETRIES + 1):
            response = self._http.request(
                method,
                path,
                params=params,
                json=json,
                headers={
                    "Authorization": f"Bearer {self._token_provider()}",
                    "Prefer": _IMMUTABLE_IDS,
                    **(headers or {}),
                },
            )
            if response.status_code not in _RETRYABLE_STATUS or attempt == _MAX_RETRIES:
                break
            delay = _retry_delay(response, attempt)
            logger.warning(
                "Graph API retornou %s; nova tentativa em %ss", response.status_code, delay
            )
            time.sleep(delay)

        if response.is_error:
            raise GraphApiError(
                f"{method} {path} falhou com {response.status_code}: {response.text[:500]}"
            )
        return response


def _parse_message(item: dict[str, Any]) -> IncomingEmail:
    sender = (item.get("from") or {}).get("emailAddress") or {}
    headers = {
        header["name"].lower(): header.get("value", "")
        for header in item.get("internetMessageHeaders") or []
        if header.get("name")
    }
    return IncomingEmail(
        message_id=item["id"],
        conversation_id=item.get("conversationId"),
        internet_message_id=item.get("internetMessageId"),
        sender_email=str(sender.get("address", "")).lower(),
        sender_name=sender.get("name"),
        subject=item.get("subject") or "",
        body=(item.get("body") or {}).get("content", "").strip(),
        received_at=datetime.fromisoformat(item["receivedDateTime"]),
        headers=headers,
    )


def _to_graph_datetime(value: datetime) -> str:
    """Formata em UTC. Datas sem fuso são tratadas como UTC."""
    utc = value.astimezone(UTC) if value.tzinfo else value.replace(tzinfo=UTC)
    return utc.strftime("%Y-%m-%dT%H:%M:%SZ")


def _recipients(addresses: Iterable[str]) -> list[dict[str, dict[str, str]]]:
    return [{"emailAddress": {"address": address}} for address in addresses]


def _prepend_html(intro_html: str, original_html: str) -> str:
    """Insere o bloco da equipe logo após a tag <body> do rascunho de encaminhamento."""
    lower = original_html.lower()
    body_start = lower.find("<body")
    if body_start == -1:
        return intro_html + original_html
    insert_at = lower.find(">", body_start) + 1
    return original_html[:insert_at] + intro_html + original_html[insert_at:]


def _retry_delay(response: httpx.Response, attempt: int) -> int:
    retry_after = response.headers.get("Retry-After", "")
    return int(retry_after) if retry_after.isdigit() else 2**attempt
