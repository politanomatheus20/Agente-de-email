"""Gateway de simulação: lê emails de verdade, mas apenas registra em log o que enviaria."""

from __future__ import annotations

import logging
from collections.abc import Iterable
from datetime import datetime

from omnis_support.domain import IncomingEmail
from omnis_support.services.ports import MailGateway

logger = logging.getLogger(__name__)


class DryRunMailGateway:
    def __init__(self, inner: MailGateway) -> None:
        self._inner = inner

    def fetch_received_since(self, since: datetime, limit: int) -> list[IncomingEmail]:
        return self._inner.fetch_received_since(since, limit)

    def reply(self, message_id: str, html_body: str) -> None:
        logger.info("[SIMULAÇÃO] Responderia ao email %s:\n%s", message_id, html_body)

    def forward(
        self,
        message_id: str,
        recipients: Iterable[str],
        subject: str,
        intro_html: str,
        reply_to: str,
    ) -> None:
        logger.info(
            "[SIMULAÇÃO] Encaminharia o email %s para %s com assunto %r (responder para %s)",
            message_id,
            ", ".join(recipients),
            subject,
            reply_to,
        )

    def mark_processed(self, message_id: str, label: str) -> None:
        logger.info("[SIMULAÇÃO] Marcaria o email %s como lido (%s)", message_id, label)
