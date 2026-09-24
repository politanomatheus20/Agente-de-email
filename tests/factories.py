"""Construtores de objetos de teste com valores padrão sensatos."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from typing import Any

from omnis_support.domain import Category, Complexity, IncomingEmail, TriageResult

_BASE_EMAIL = IncomingEmail(
    message_id="msg-1",
    conversation_id="conv-1",
    internet_message_id="<abc@cliente.com>",
    sender_email="maria@cliente.com.br",
    sender_name="Maria Souza",
    subject="Não consigo fazer login",
    body="Olá, não estou conseguindo entrar no Omnis.",
    received_at=datetime(2026, 9, 24, 12, 0, tzinfo=UTC),
)

_BASE_TRIAGE = TriageResult(
    category=Category.LOGIN,
    complexity=Complexity.SIMPLES,
    confidence=0.95,
    summary="Cliente não consegue fazer login.",
    is_interesting=False,
    interesting_reason=None,
)


def make_email(**overrides: Any) -> IncomingEmail:
    return replace(_BASE_EMAIL, **overrides)


def make_triage(**overrides: Any) -> TriageResult:
    return replace(_BASE_TRIAGE, **overrides)
