"""Orquestra o ciclo de atendimento: ler, classificar, responder ou encaminhar, registrar."""

from __future__ import annotations

import logging
from collections.abc import Collection, Sequence
from dataclasses import dataclass
from datetime import datetime

from omnis_support.domain import IncomingEmail, Ticket, TicketStatus, TriageResult
from omnis_support.email import templates
from omnis_support.email.filters import skip_reason
from omnis_support.services.decision import Action, apply_interest_rules, decide
from omnis_support.services.ports import MailGateway, SupportAssistant, TicketRepository

logger = logging.getLogger(__name__)

LABEL_AUTO_REPLIED = "Agente Omnis: respondido"
LABEL_ESCALATED = "Agente Omnis: encaminhado"
LABEL_IGNORED = "Agente Omnis: ignorado"
LABEL_ALREADY_HANDLED = "Agente Omnis: processado"
LABEL_ERROR = "Agente Omnis: erro"


@dataclass(frozen=True, slots=True)
class AgentSettings:
    escalation_recipients: Sequence[str]
    internal_addresses: Collection[str]
    signature: str
    min_confidence: float
    max_messages_per_run: int
    max_attempts: int
    send_acknowledgement: bool
    process_since: datetime | None = None


@dataclass
class RunReport:
    fetched: int = 0
    auto_replied: int = 0
    escalated: int = 0
    ignored: int = 0
    already_handled: int = 0
    failed: int = 0

    def register(self, status: TicketStatus) -> None:
        if status is TicketStatus.RESPONDIDO_AUTOMATICAMENTE:
            self.auto_replied += 1
        elif status is TicketStatus.ENCAMINHADO:
            self.escalated += 1
        elif status is TicketStatus.IGNORADO:
            self.ignored += 1


class SupportAgent:
    def __init__(
        self,
        mail: MailGateway,
        tickets: TicketRepository,
        assistant: SupportAssistant,
        settings: AgentSettings,
    ) -> None:
        self._mail = mail
        self._tickets = tickets
        self._assistant = assistant
        self._settings = settings

    def run_once(self) -> RunReport:
        report = RunReport()
        emails = self._mail.fetch_unread(
            self._settings.max_messages_per_run, self._settings.process_since
        )
        report.fetched = len(emails)
        for email in emails:
            try:
                self._process_safely(email, report)
            except Exception:
                # Falha de infraestrutura antes do registro (ex.: banco indisponível).
                logger.exception("Falha inesperada no email %s", email.message_id)
                report.failed += 1
        logger.info("Ciclo concluído: %s", report)
        return report

    # ------------------------------------------------------------------ fluxo

    def _process_safely(self, email: IncomingEmail, report: RunReport) -> None:
        ticket = self._tickets.claim(email, self._settings.max_attempts)
        if ticket is None:
            # Já atendido antes, mas ainda aparecia como não lido.
            self._mail.mark_processed(email.message_id, LABEL_ALREADY_HANDLED)
            report.already_handled += 1
            return

        try:
            report.register(self._handle(email, ticket))
        except Exception as exc:
            logger.exception("Falha ao processar o chamado %s", ticket.number)
            self._tickets.fail(ticket.id, f"{type(exc).__name__}: {exc}")
            report.failed += 1
            if ticket.attempts >= self._settings.max_attempts:
                self._give_up(email, ticket, exc)

    def _handle(self, email: IncomingEmail, ticket: Ticket) -> TicketStatus:
        reason = skip_reason(email, self._settings.internal_addresses)
        if reason:
            return self._ignore(email, ticket, reason)

        triage = apply_interest_rules(self._assistant.triage(email))
        self._tickets.record_triage(ticket.id, triage)
        previous = self._tickets.find_previous_in_conversation(email.conversation_id, ticket.id)
        decision = decide(triage, previous, self._settings.min_confidence)
        logger.info(
            "Chamado %s: categoria=%s complexidade=%s confiança=%.2f decisão=%s",
            ticket.number,
            triage.category,
            triage.complexity,
            triage.confidence,
            decision.action,
        )

        if decision.action is Action.IGNORE:
            return self._ignore(email, ticket, decision.reason)
        if decision.action is Action.AUTO_REPLY:
            draft = self._assistant.draft_reply(email)
            if draft.can_answer:
                return self._auto_reply(email, ticket, draft.body, decision.reason)
            return self._escalate(
                email, ticket, f"Resposta automática não foi possível: {draft.reason}", triage
            )
        return self._escalate(email, ticket, decision.reason, triage, acknowledge=previous is None)

    # ------------------------------------------------------------------ ações

    def _auto_reply(
        self, email: IncomingEmail, ticket: Ticket, reply_text: str, reason: str
    ) -> TicketStatus:
        html = templates.auto_reply_html(reply_text, self._settings.signature, email)
        self._mail.reply(email.message_id, html)
        self._tickets.complete(
            ticket.id, TicketStatus.RESPONDIDO_AUTOMATICAMENTE, reason, auto_reply=reply_text
        )
        self._mail.mark_processed(email.message_id, LABEL_AUTO_REPLIED)
        return TicketStatus.RESPONDIDO_AUTOMATICAMENTE

    def _escalate(
        self,
        email: IncomingEmail,
        ticket: Ticket,
        reason: str,
        triage: TriageResult | None,
        *,
        acknowledge: bool = True,
    ) -> TicketStatus:
        self._mail.forward(
            email.message_id,
            recipients=self._settings.escalation_recipients,
            subject=f"[{ticket.number}] {email.subject or '(sem assunto)'}",
            intro_html=templates.escalation_intro_html(ticket.number, email, reason, triage),
            reply_to=email.sender_email,
        )
        if acknowledge and self._settings.send_acknowledgement:
            self._send_acknowledgement(email, ticket)
        self._tickets.complete(ticket.id, TicketStatus.ENCAMINHADO, reason)
        self._mail.mark_processed(email.message_id, LABEL_ESCALATED)
        return TicketStatus.ENCAMINHADO

    def _send_acknowledgement(self, email: IncomingEmail, ticket: Ticket) -> None:
        # O encaminhamento já aconteceu; uma falha aqui não deve gerar reenvio à equipe.
        try:
            self._mail.reply(
                email.message_id,
                templates.acknowledgement_html(
                    email.sender_name, ticket.number, self._settings.signature
                ),
            )
        except Exception:
            logger.exception("Falha ao enviar o aviso de recebimento do chamado %s", ticket.number)

    def _ignore(self, email: IncomingEmail, ticket: Ticket, reason: str) -> TicketStatus:
        logger.info("Chamado %s ignorado: %s", ticket.number, reason)
        self._tickets.complete(ticket.id, TicketStatus.IGNORADO, reason)
        self._mail.mark_processed(email.message_id, LABEL_IGNORED)
        return TicketStatus.IGNORADO

    def _give_up(self, email: IncomingEmail, ticket: Ticket, error: Exception) -> None:
        """Última tentativa esgotada: entrega o email à equipe sem passar pela IA."""
        reason = (
            "O agente não conseguiu processar este email automaticamente "
            f"({type(error).__name__}). Por favor, atenda manualmente."
        )
        try:
            self._escalate(email, ticket, reason, triage=None, acknowledge=False)
        except Exception:
            logger.exception("Não foi possível encaminhar o chamado %s à equipe", ticket.number)
            try:
                self._mail.mark_processed(email.message_id, LABEL_ERROR)
            except Exception:
                logger.exception("Não foi possível marcar o email do chamado %s", ticket.number)
