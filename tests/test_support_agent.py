"""Testes do fluxo completo do agente, com dublês de email e de IA."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime

import pytest

from omnis_support.db.repository import InMemoryTicketRepository
from omnis_support.domain import (
    Category,
    Complexity,
    DraftReply,
    IncomingEmail,
    TicketStatus,
    TriageResult,
)
from omnis_support.services.support_agent import (
    LABEL_ALREADY_HANDLED,
    LABEL_AUTO_REPLIED,
    LABEL_ESCALATED,
    LABEL_IGNORED,
    AgentSettings,
    SupportAgent,
)
from tests.factories import make_email, make_triage

TEAM = ("caio.p@datagroup.global", "matheus.gavioli@datagroup.global")


@dataclass
class FakeMail:
    inbox: list[IncomingEmail] = field(default_factory=list)
    replies: list[tuple[str, str]] = field(default_factory=list)
    forwards: list[dict[str, object]] = field(default_factory=list)
    labels: dict[str, str] = field(default_factory=dict)
    fail_forward: bool = False

    def fetch_unread(self, limit: int, since: datetime | None = None) -> list[IncomingEmail]:
        return [email for email in self.inbox if email.message_id not in self.labels][:limit]

    def reply(self, message_id: str, html_body: str) -> None:
        self.replies.append((message_id, html_body))

    def forward(
        self,
        message_id: str,
        recipients: Iterable[str],
        subject: str,
        intro_html: str,
        reply_to: str,
    ) -> None:
        if self.fail_forward:
            raise RuntimeError("Graph indisponível")
        self.forwards.append(
            {
                "message_id": message_id,
                "to": list(recipients),
                "subject": subject,
                "intro": intro_html,
                "reply_to": reply_to,
            }
        )

    def mark_processed(self, message_id: str, label: str) -> None:
        self.labels[message_id] = label


@dataclass
class FakeAssistant:
    triage_result: TriageResult = field(default_factory=make_triage)
    draft: DraftReply = field(
        default_factory=lambda: DraftReply(True, "Olá, Maria!\n\nSiga os passos...", "coberto")
    )
    triage_error: Exception | None = None
    draft_calls: int = 0

    def triage(self, email: IncomingEmail) -> TriageResult:
        if self.triage_error:
            raise self.triage_error
        return self.triage_result

    def draft_reply(self, email: IncomingEmail) -> DraftReply:
        self.draft_calls += 1
        return self.draft


def build(
    mail: FakeMail,
    assistant: FakeAssistant,
    repo: InMemoryTicketRepository | None = None,
    *,
    send_ack: bool = True,
    max_attempts: int = 3,
) -> tuple[SupportAgent, InMemoryTicketRepository]:
    repository = repo or InMemoryTicketRepository()
    settings = AgentSettings(
        escalation_recipients=TEAM,
        internal_addresses=frozenset({"suporte@dataomnis.com.br", *TEAM}),
        signature="Equipe de Suporte Omnis",
        min_confidence=0.8,
        max_messages_per_run=25,
        max_attempts=max_attempts,
        send_acknowledgement=send_ack,
    )
    return SupportAgent(mail, repository, assistant, settings), repository


def test_simple_question_gets_automatic_reply() -> None:
    mail = FakeMail(inbox=[make_email()])
    agent, repo = build(mail, FakeAssistant())

    report = agent.run_once()

    assert report.auto_replied == 1
    assert len(mail.replies) == 1
    assert "Siga os passos" in mail.replies[0][1]
    assert "Equipe de Suporte Omnis" in mail.replies[0][1]
    assert mail.forwards == []
    assert mail.labels["msg-1"] == LABEL_AUTO_REPLIED
    stored = repo.by_id(1)
    assert stored.ticket.status is TicketStatus.RESPONDIDO_AUTOMATICAMENTE
    assert stored.auto_reply == "Olá, Maria!\n\nSiga os passos..."


def test_complex_question_is_forwarded_with_customer_as_reply_to() -> None:
    mail = FakeMail(inbox=[make_email(subject="Conexão com Postgres")])
    assistant = FakeAssistant(
        make_triage(category=Category.CONEXAO_BANCO, complexity=Complexity.COMPLEXO)
    )
    agent, repo = build(mail, assistant)

    report = agent.run_once()

    assert report.escalated == 1
    forward = mail.forwards[0]
    assert forward["to"] == list(TEAM)
    assert forward["reply_to"] == "maria@cliente.com.br"
    assert forward["subject"] == "[OMN-000001] Conexão com Postgres"
    assert "OMN-000001" in str(forward["intro"])
    # O cliente recebe o aviso de recebimento com o número do chamado.
    assert len(mail.replies) == 1
    assert "OMN-000001" in mail.replies[0][1]
    assert assistant.draft_calls == 0
    assert mail.labels["msg-1"] == LABEL_ESCALATED
    assert repo.by_id(1).ticket.status is TicketStatus.ENCAMINHADO


def test_acknowledgement_can_be_disabled() -> None:
    mail = FakeMail(inbox=[make_email()])
    assistant = FakeAssistant(make_triage(category=Category.BUG))
    agent, _ = build(mail, assistant, send_ack=False)

    agent.run_once()

    assert len(mail.forwards) == 1
    assert mail.replies == []


def test_bug_report_is_recorded_as_interesting() -> None:
    mail = FakeMail(inbox=[make_email()])
    agent, repo = build(mail, FakeAssistant(make_triage(category=Category.LENTIDAO)))

    agent.run_once()

    triage = repo.by_id(1).triage
    assert triage is not None
    assert triage.is_interesting


def test_escalates_when_knowledge_base_cannot_answer() -> None:
    mail = FakeMail(inbox=[make_email()])
    assistant = FakeAssistant(draft=DraftReply(False, "", "não há procedimento documentado"))
    agent, _ = build(mail, assistant)

    report = agent.run_once()

    assert report.escalated == 1
    assert "não há procedimento documentado" in str(mail.forwards[0]["intro"])


def test_customer_follow_up_after_auto_reply_goes_to_team_without_new_ack() -> None:
    mail = FakeMail(inbox=[make_email()])
    agent, _ = build(mail, FakeAssistant())
    agent.run_once()

    mail.inbox.append(make_email(message_id="msg-2", body="Não funcionou."))
    report = agent.run_once()

    assert report.escalated == 1
    assert "Continuação do chamado OMN-000001" in str(mail.forwards[0]["intro"])
    assert len(mail.replies) == 1  # apenas a resposta automática original


@pytest.mark.parametrize(
    ("sender", "headers"),
    [
        ("caio.p@datagroup.global", {}),
        ("suporte@dataomnis.com.br", {}),
        ("no-reply@sistema.com", {}),
        ("cliente@empresa.com", {"auto-submitted": "auto-replied"}),
    ],
)
def test_automatic_or_internal_emails_are_ignored_without_ai(
    sender: str, headers: dict[str, str]
) -> None:
    mail = FakeMail(inbox=[make_email(sender_email=sender, headers=headers)])
    assistant = FakeAssistant(triage_error=AssertionError("não deveria chamar a IA"))
    agent, _ = build(mail, assistant)

    report = agent.run_once()

    assert report.ignored == 1
    assert mail.labels["msg-1"] == LABEL_IGNORED
    assert mail.replies == []
    assert mail.forwards == []


def test_failure_keeps_email_unread_for_retry() -> None:
    mail = FakeMail(inbox=[make_email()])
    agent, repo = build(mail, FakeAssistant(triage_error=RuntimeError("API fora do ar")))

    report = agent.run_once()

    assert report.failed == 1
    assert "msg-1" not in mail.labels
    stored = repo.by_id(1)
    assert stored.ticket.status is TicketStatus.ERRO
    assert stored.last_error is not None
    assert "API fora do ar" in stored.last_error


def test_retry_succeeds_after_transient_failure() -> None:
    mail = FakeMail(inbox=[make_email()])
    assistant = FakeAssistant(triage_error=RuntimeError("instável"))
    agent, repo = build(mail, assistant)
    agent.run_once()

    assistant.triage_error = None
    report = agent.run_once()

    assert report.auto_replied == 1
    assert repo.by_id(1).ticket.attempts == 2


def test_last_failed_attempt_hands_email_to_team_without_ai() -> None:
    mail = FakeMail(inbox=[make_email()])
    agent, repo = build(mail, FakeAssistant(triage_error=RuntimeError("erro")), max_attempts=1)

    report = agent.run_once()

    assert report.failed == 1
    assert len(mail.forwards) == 1
    assert "não conseguiu processar" in str(mail.forwards[0]["intro"])
    assert mail.labels["msg-1"] == LABEL_ESCALATED
    assert repo.by_id(1).ticket.status is TicketStatus.ENCAMINHADO


def test_already_handled_email_is_only_marked_as_read() -> None:
    repo = InMemoryTicketRepository()
    email = make_email()
    ticket = repo.claim(email, max_attempts=3)
    assert ticket is not None
    repo.complete(ticket.id, TicketStatus.ENCAMINHADO, "já encaminhado")

    mail = FakeMail(inbox=[email])
    agent, _ = build(mail, FakeAssistant(), repo)
    report = agent.run_once()

    assert report.already_handled == 1
    assert mail.labels["msg-1"] == LABEL_ALREADY_HANDLED
    assert mail.replies == []
