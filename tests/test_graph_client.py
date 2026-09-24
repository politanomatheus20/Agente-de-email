"""Testes do cliente Graph usando um transporte HTTP falso."""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import UTC, datetime

import httpx
import pytest

from omnis_support.email import graph_client
from omnis_support.email.graph_client import GRAPH_BASE_URL, GraphApiError, GraphMailClient

Handler = Callable[[httpx.Request], httpx.Response]


def make_client(handler: Handler) -> GraphMailClient:
    http = httpx.Client(base_url=GRAPH_BASE_URL, transport=httpx.MockTransport(handler))
    return GraphMailClient("suporte@dataomnis.com.br", lambda: "token-teste", http)


def test_fetch_unread_parses_messages_and_builds_query() -> None:
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(
            200,
            json={
                "value": [
                    {
                        "id": "AAMk=",
                        "conversationId": "conv",
                        "internetMessageId": "<1@x>",
                        "subject": "Ajuda",
                        "from": {"emailAddress": {"address": "Cliente@Empresa.com", "name": "Ana"}},
                        "body": {"contentType": "text", "content": "  Olá  "},
                        "receivedDateTime": "2026-09-24T10:00:00Z",
                        "internetMessageHeaders": [{"name": "Auto-Submitted", "value": "no"}],
                    }
                ]
            },
        )

    emails = make_client(handler).fetch_unread(10, datetime(2026, 9, 1, tzinfo=UTC))

    request = captured[0]
    assert request.headers["Authorization"] == "Bearer token-teste"
    assert "outlook.body-content-type" in request.headers["Prefer"]
    assert request.url.params["$filter"] == (
        "receivedDateTime ge 2026-09-01T00:00:00Z and isRead eq false"
    )
    assert request.url.params["$top"] == "10"
    email = emails[0]
    assert email.sender_email == "cliente@empresa.com"
    assert email.body == "Olá"
    assert email.headers == {"auto-submitted": "no"}
    assert email.received_at == datetime(2026, 9, 24, 10, 0, tzinfo=UTC)


def test_forward_sets_reply_to_and_keeps_original_content() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path.endswith("/createForward"):
            draft = {"id": "draft-1", "body": {"content": "<html><body>original</body></html>"}}
            return httpx.Response(201, json=draft)
        return httpx.Response(202 if request.method == "POST" else 200, json={})

    make_client(handler).forward(
        "msg-1", ["equipe@x.com"], "[OMN-000001] Ajuda", "<div>intro</div>", "cliente@y.com"
    )

    create, patch, send = requests
    assert json.loads(create.content)["message"]["toRecipients"] == [
        {"emailAddress": {"address": "equipe@x.com"}}
    ]
    patch_body = json.loads(patch.content)
    assert patch.method == "PATCH"
    assert patch_body["replyTo"] == [{"emailAddress": {"address": "cliente@y.com"}}]
    assert patch_body["body"]["content"] == "<html><body><div>intro</div>original</body></html>"
    assert send.url.path.endswith("/messages/draft-1/send")


def test_retries_on_throttling(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(graph_client.time, "sleep", lambda _: None)
    responses = iter([httpx.Response(429, headers={"Retry-After": "1"}), httpx.Response(200)])

    make_client(lambda _: next(responses)).mark_processed("msg-1", "rótulo")


def test_raises_on_client_error() -> None:
    client = make_client(lambda _: httpx.Response(403, text="Access denied"))
    with pytest.raises(GraphApiError, match="403"):
        client.reply("msg-1", "<p>oi</p>")
