"""Repositórios de chamados: PostgreSQL em produção e memória para testes e simulação."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta

import psycopg
from psycopg.rows import dict_row

from omnis_support.domain import IncomingEmail, Ticket, TicketStatus, TriageResult

_FINISHED_STATUSES = (TicketStatus.RESPONDIDO_AUTOMATICAMENTE, TicketStatus.ENCAMINHADO)
# Um chamado "recebido" há mais tempo que isso foi interrompido no meio (ex.: queda
# ou limite de tempo da função) e pode ser retomado.
STALE_CLAIM_AFTER = timedelta(minutes=20)


class PostgresTicketRepository:
    def __init__(self, conn: psycopg.Connection) -> None:
        self._conn = conn

    def claim(self, email: IncomingEmail, max_attempts: int) -> Ticket | None:
        """Registra o email para atendimento.

        Retorna None quando o email já foi atendido ou esgotou as tentativas.
        Um email com erro anterior, ou interrompido no meio, é liberado para nova tentativa.
        """
        row = self._fetch_one(
            """
            INSERT INTO tickets (graph_message_id, internet_message_id, conversation_id,
                                 sender_email, sender_name, subject, body, received_at)
            VALUES (%(message_id)s, %(internet_message_id)s, %(conversation_id)s,
                    %(sender_email)s, %(sender_name)s, %(subject)s, %(body)s, %(received_at)s)
            ON CONFLICT (graph_message_id) DO UPDATE
               SET attempts = tickets.attempts + 1, status = 'recebido', last_error = NULL
             WHERE tickets.attempts < %(max_attempts)s
               AND (tickets.status = 'erro'
                    OR (tickets.status = 'recebido' AND tickets.updated_at < now() - %(stale)s))
            RETURNING id, status, attempts
            """,
            {
                "message_id": email.message_id,
                "internet_message_id": email.internet_message_id,
                "conversation_id": email.conversation_id,
                "sender_email": email.sender_email,
                "sender_name": email.sender_name,
                "subject": email.subject,
                "body": email.body,
                "received_at": email.received_at,
                "max_attempts": max_attempts,
                "stale": STALE_CLAIM_AFTER,
            },
        )
        return _to_ticket(row) if row else None

    def find_previous_in_conversation(
        self, conversation_id: str | None, current_ticket_id: int
    ) -> Ticket | None:
        if not conversation_id:
            return None
        row = self._fetch_one(
            """
            SELECT id, status, attempts FROM tickets
             WHERE conversation_id = %(conversation_id)s
               AND id <> %(current_id)s
               AND status = ANY(%(statuses)s)
             ORDER BY id DESC
             LIMIT 1
            """,
            {
                "conversation_id": conversation_id,
                "current_id": current_ticket_id,
                "statuses": [status.value for status in _FINISHED_STATUSES],
            },
        )
        return _to_ticket(row) if row else None

    def record_triage(self, ticket_id: int, triage: TriageResult) -> None:
        self._conn.execute(
            """
            UPDATE tickets
               SET category = %(category)s, complexity = %(complexity)s,
                   confidence = %(confidence)s, summary = %(summary)s,
                   is_interesting = %(is_interesting)s, interesting_reason = %(reason)s
             WHERE id = %(id)s
            """,
            {
                "id": ticket_id,
                "category": triage.category.value,
                "complexity": triage.complexity.value,
                "confidence": round(triage.confidence, 3),
                "summary": triage.summary,
                "is_interesting": triage.is_interesting,
                "reason": triage.interesting_reason,
            },
        )

    def complete(
        self,
        ticket_id: int,
        status: TicketStatus,
        decision_reason: str,
        auto_reply: str | None = None,
    ) -> None:
        self._conn.execute(
            """
            UPDATE tickets
               SET status = %(status)s, decision_reason = %(reason)s, auto_reply = %(reply)s
             WHERE id = %(id)s
            """,
            {
                "id": ticket_id,
                "status": status.value,
                "reason": decision_reason,
                "reply": auto_reply,
            },
        )

    def fail(self, ticket_id: int, error: str) -> None:
        self._conn.execute(
            "UPDATE tickets SET status = 'erro', last_error = %(error)s WHERE id = %(id)s",
            {"id": ticket_id, "error": error[:2000]},
        )

    def _fetch_one(self, query: str, params: dict[str, object]) -> dict[str, object] | None:
        with self._conn.cursor(row_factory=dict_row) as cursor:
            cursor.execute(query.encode(), params)
            return cursor.fetchone()


def _to_ticket(row: dict[str, object]) -> Ticket:
    return Ticket(
        id=int(str(row["id"])),
        status=TicketStatus(str(row["status"])),
        attempts=int(str(row["attempts"])),
    )


@dataclass
class _StoredTicket:
    ticket: Ticket
    email: IncomingEmail
    claimed_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    triage: TriageResult | None = None
    decision_reason: str | None = None
    auto_reply: str | None = None
    last_error: str | None = None


@dataclass
class InMemoryTicketRepository:
    """Mesmo contrato do repositório PostgreSQL, sem banco. Usado em testes e no modo simulação."""

    tickets: dict[str, _StoredTicket] = field(default_factory=dict)

    def claim(self, email: IncomingEmail, max_attempts: int) -> Ticket | None:
        stored = self.tickets.get(email.message_id)
        if stored is None:
            ticket = Ticket(id=len(self.tickets) + 1, status=TicketStatus.RECEBIDO, attempts=1)
            self.tickets[email.message_id] = _StoredTicket(ticket, email)
            return ticket
        stale = (
            stored.ticket.status is TicketStatus.RECEBIDO
            and datetime.now(UTC) - stored.claimed_at > STALE_CLAIM_AFTER
        )
        retryable = stored.ticket.status is TicketStatus.ERRO or stale
        if retryable and stored.ticket.attempts < max_attempts:
            stored.ticket = replace(
                stored.ticket, status=TicketStatus.RECEBIDO, attempts=stored.ticket.attempts + 1
            )
            stored.claimed_at = datetime.now(UTC)
            return stored.ticket
        return None

    def find_previous_in_conversation(
        self, conversation_id: str | None, current_ticket_id: int
    ) -> Ticket | None:
        if not conversation_id:
            return None
        matches = [
            stored.ticket
            for stored in self.tickets.values()
            if stored.email.conversation_id == conversation_id
            and stored.ticket.id != current_ticket_id
            and stored.ticket.status in _FINISHED_STATUSES
        ]
        return max(matches, key=lambda ticket: ticket.id, default=None)

    def record_triage(self, ticket_id: int, triage: TriageResult) -> None:
        self._get(ticket_id).triage = triage

    def complete(
        self,
        ticket_id: int,
        status: TicketStatus,
        decision_reason: str,
        auto_reply: str | None = None,
    ) -> None:
        stored = self._get(ticket_id)
        stored.ticket = replace(stored.ticket, status=status)
        stored.decision_reason = decision_reason
        stored.auto_reply = auto_reply

    def fail(self, ticket_id: int, error: str) -> None:
        stored = self._get(ticket_id)
        stored.ticket = replace(stored.ticket, status=TicketStatus.ERRO)
        stored.last_error = error

    def by_id(self, ticket_id: int) -> _StoredTicket:
        return self._get(ticket_id)

    def _get(self, ticket_id: int) -> _StoredTicket:
        return next(s for s in self.tickets.values() if s.ticket.id == ticket_id)
