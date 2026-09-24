"""Ponto de composição: monta o agente com as implementações reais de cada dependência."""

from __future__ import annotations

import logging
from dataclasses import replace
from datetime import timedelta

import anthropic
import psycopg

from omnis_support.ai.assistant import ClaudeSupportAssistant
from omnis_support.ai.knowledge import load_knowledge_base
from omnis_support.config import Settings
from omnis_support.db.migrate import apply_migrations
from omnis_support.db.repository import InMemoryTicketRepository, PostgresTicketRepository
from omnis_support.email.dry_run import DryRunMailGateway
from omnis_support.email.graph_client import GraphMailClient, msal_token_provider
from omnis_support.services.ports import MailGateway
from omnis_support.services.support_agent import AgentSettings, RunReport, SupportAgent

logger = logging.getLogger(__name__)

# Um pouco maior que o intervalo entre ciclos (30 min), para não pular nenhum email.
DRY_RUN_LOOKBACK = timedelta(minutes=35)


def run_cycle(settings: Settings) -> RunReport:
    """Executa um ciclo completo de leitura e atendimento da caixa de suporte."""
    settings.require_production_settings()

    mail: MailGateway = GraphMailClient(
        mailbox=settings.mailbox_address,
        token_provider=msal_token_provider(
            settings.graph_tenant_id,
            settings.graph_client_id,
            settings.graph_client_secret.get_secret_value(),
        ),
    )
    assistant = ClaudeSupportAssistant(
        # Limite por chamada bem abaixo do tempo máximo de execução da função.
        client=anthropic.Anthropic(
            api_key=settings.anthropic_api_key.get_secret_value(), timeout=120.0, max_retries=2
        ),
        model=settings.claude_model,
        knowledge_base=load_knowledge_base(settings.knowledge_dir),
    )
    agent_settings = _agent_settings(settings)

    if settings.dry_run:
        logger.warning("Modo SIMULAÇÃO: nada será enviado, marcado ou gravado no banco.")
        # Sem banco, a simulação não lembra dos ciclos anteriores. A janela curta
        # evita reclassificar (e pagar de novo) os mesmos emails a cada ciclo.
        agent = SupportAgent(
            DryRunMailGateway(mail),
            InMemoryTicketRepository(),
            assistant,
            replace(agent_settings, lookback=DRY_RUN_LOOKBACK),
        )
        return agent.run_once()

    with psycopg.connect(
        settings.database_url.get_secret_value(), autocommit=True, connect_timeout=15
    ) as conn:
        applied = apply_migrations(conn)
        if applied:
            logger.info("Migrações aplicadas: %s", ", ".join(applied))
        agent = SupportAgent(mail, PostgresTicketRepository(conn), assistant, agent_settings)
        return agent.run_once()


def _agent_settings(settings: Settings) -> AgentSettings:
    internal = {settings.mailbox_address.lower(), *settings.escalation_recipients}
    return AgentSettings(
        escalation_recipients=settings.escalation_recipients,
        internal_addresses=frozenset(internal),
        signature=settings.signature,
        min_confidence=settings.min_confidence_auto_reply,
        max_messages_per_run=settings.max_messages_per_run,
        max_attempts=settings.max_attempts,
        send_acknowledgement=settings.send_acknowledgement,
        process_since=settings.process_since,
        lookback=timedelta(hours=settings.lookback_hours),
    )
