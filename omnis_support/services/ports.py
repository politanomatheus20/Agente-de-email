"""Contratos que o agente espera da infraestrutura. Facilitam testes e trocas de fornecedor."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime
from typing import Protocol

from omnis_support.domain import (
    DraftReply,
    IncomingEmail,
    Ticket,
    TicketStatus,
    TriageResult,
)


class MailGateway(Protocol):
    def fetch_unread(self, limit: int, since: datetime | None = None) -> list[IncomingEmail]: ...

    def reply(self, message_id: str, html_body: str) -> None: ...

    def forward(
        self,
        message_id: str,
        recipients: Iterable[str],
        subject: str,
        intro_html: str,
        reply_to: str,
    ) -> None: ...

    def mark_processed(self, message_id: str, label: str) -> None: ...


class TicketRepository(Protocol):
    def claim(self, email: IncomingEmail, max_attempts: int) -> Ticket | None: ...

    def find_previous_in_conversation(
        self, conversation_id: str | None, current_ticket_id: int
    ) -> Ticket | None: ...

    def record_triage(self, ticket_id: int, triage: TriageResult) -> None: ...

    def complete(
        self,
        ticket_id: int,
        status: TicketStatus,
        decision_reason: str,
        auto_reply: str | None = None,
    ) -> None: ...

    def fail(self, ticket_id: int, error: str) -> None: ...


class SupportAssistant(Protocol):
    def triage(self, email: IncomingEmail) -> TriageResult: ...

    def draft_reply(self, email: IncomingEmail) -> DraftReply: ...
