"""Testes do fluxo completo do agente, com dublês de email e de IA."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta

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
    LABEL_AUTO_REPLIED,
    LABEL_ESCALATED,
    LABEL_IGNORED,
    AgentSettings,
    SupportAgent,
)
from tests.factories import make_email, make_triage

TEAM = ("matheus.gavioli@datagroup.global", "thiago.dourado@grupodata.com.br")


@dataclass
class FakeMail:
    inbox: list[IncomingEmail] = field(default_factory=list)
    replies: list[tuple[str, str]] = field(default_factory=list)
    forwards: list[dict[str, object]] = field(default_factory=list)
    labels: dict[str, str] = field(default_factory=dict)
    fail_forward: bool = False
    fail_label: bool = False
    fetched_since: list[datetime] = field(default_factory=list)

    def fetch_received_since(self, since: datetime, limit: int) -> list[IncomingEmail]:
        # Como a Graph real: devolve tudo da janela, lido ou não.
        self.fetched_since.append(since)
        return self.inbox[:limit]

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
        if self.fail_label:
            raise RuntimeError("Graph indisponível ao marcar")
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
    max_per_run: int = 25,
    clock: Callable[[], datetime] | None = None,
    timer: Callable[[], float] | None = None,
) -> tuple[SupportAgent, InMemoryTicketRepository]:
    repository = repo or InMemoryTicketRepository()
    settings = AgentSettings(
        escalation_recipients=TEAM,
        internal_addresses=frozenset({"suporte@dataomnis.com.br", *TEAM}),
        signature="Equipe de Suporte Omnis",
        min_confidence=0.8,
        max_messages_per_run=max_per_run,
        max_attempts=max_attempts,
        send_acknowledgement=send_ack,
    )
    agent = SupportAgent(
        mail,
        repository,
        assistant,
        settings,
        clock=clock or (lambda: datetime.now(UTC)),
        timer=timer or (lambda: 0.0),
    )
    return agent, repository


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
        ("thiago.dourado@grupodata.com.br", {}),
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


def test_already_handled_email_is_skipped_on_next_cycles() -> None:
    mail = FakeMail(inbox=[make_email()])
    agent, _ = build(mail, FakeAssistant())
    agent.run_once()

    report = agent.run_once()

    assert report.already_handled == 1
    assert report.processed == 0
    assert len(mail.replies) == 1


def test_email_already_opened_in_outlook_is_still_handled() -> None:
    # Não existe filtro por "não lido": o email aberto por uma pessoa continua na janela.
    mail = FakeMail(inbox=[make_email()], labels={"msg-1": "lido por uma pessoa"})
    agent, _ = build(mail, FakeAssistant())

    assert agent.run_once().auto_replied == 1


def test_failure_to_label_does_not_cause_duplicate_reply() -> None:
    mail = FakeMail(inbox=[make_email()], fail_label=True)
    agent, repo = build(mail, FakeAssistant())

    first = agent.run_once()
    second = agent.run_once()

    assert first.auto_replied == 1
    assert second.already_handled == 1
    assert len(mail.replies) == 1
    assert repo.by_id(1).ticket.status is TicketStatus.RESPONDIDO_AUTOMATICAMENTE


def test_interrupted_ticket_is_resumed_after_stale_period() -> None:
    repo = InMemoryTicketRepository()
    email = make_email()
    assert repo.claim(email, max_attempts=3) is not None  # interrompido no meio
    repo.tickets[email.message_id].claimed_at -= timedelta(minutes=30)

    mail = FakeMail(inbox=[email])
    agent, _ = build(mail, FakeAssistant(), repo)
    report = agent.run_once()

    assert report.auto_replied == 1
    assert repo.by_id(1).ticket.attempts == 2


def test_recent_in_progress_ticket_is_not_taken_twice() -> None:
    repo = InMemoryTicketRepository()
    email = make_email()
    assert repo.claim(email, max_attempts=3) is not None

    assert repo.claim(email, max_attempts=3) is None


def test_limit_per_cycle_counts_only_new_emails() -> None:
    emails = [make_email(message_id=f"msg-{n}", conversation_id=f"c{n}") for n in range(4)]
    mail = FakeMail(inbox=emails)
    agent, _ = build(mail, FakeAssistant(), max_per_run=2)

    first = agent.run_once()
    second = agent.run_once()

    assert (first.auto_replied, second.auto_replied) == (2, 2)
    assert second.already_handled == 2


def test_time_budget_stops_taking_new_emails() -> None:
    emails = [make_email(message_id=f"msg-{n}", conversation_id=f"c{n}") for n in range(3)]
    ticks = iter([0.0, 0.0, 400.0, 400.0])
    mail = FakeMail(inbox=emails)
    agent, _ = build(mail, FakeAssistant(), timer=lambda: next(ticks))

    report = agent.run_once()

    assert report.auto_replied == 1


def test_search_window_respects_lookback_and_process_since() -> None:
    now = datetime(2026, 9, 25, 12, 0, tzinfo=UTC)
    mail = FakeMail()
    agent, _ = build(mail, FakeAssistant(), clock=lambda: now)
    agent.run_once()
    assert mail.fetched_since[-1] == now - timedelta(hours=24)

    since = datetime(2026, 9, 25, 8, 0)  # sem fuso: tratado como UTC
    settings = replace(agent._settings, process_since=since)
    SupportAgent(
        mail, InMemoryTicketRepository(), FakeAssistant(), settings, clock=lambda: now
    ).run_once()
    assert mail.fetched_since[-1] == since.replace(tzinfo=UTC)


def test_customer_out_of_office_in_same_conversation_is_ignored() -> None:
    mail = FakeMail(inbox=[make_email()])
    assistant = FakeAssistant()
    agent, _ = build(mail, assistant)
    agent.run_once()

    assistant.triage_result = make_triage(category=Category.NAO_SUPORTE, confidence=0.95)
    mail.inbox.append(make_email(message_id="msg-2", body="Estou de férias até dia 30."))
    report = agent.run_once()

    assert report.ignored == 1
    assert mail.forwards == []
