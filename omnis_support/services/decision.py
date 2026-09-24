"""Regras que decidem o destino de cada email. Funções puras, sem efeitos colaterais."""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import StrEnum

from omnis_support.domain import (
    ALWAYS_INTERESTING_CATEGORIES,
    AUTO_ANSWERABLE_CATEGORIES,
    Category,
    Complexity,
    Ticket,
    TriageResult,
)


class Action(StrEnum):
    AUTO_REPLY = "auto_reply"
    ESCALATE = "escalate"
    IGNORE = "ignore"


@dataclass(frozen=True, slots=True)
class Decision:
    action: Action
    reason: str


def apply_interest_rules(triage: TriageResult) -> TriageResult:
    """Garante que bug, lentidão e pedido de melhoria sempre fiquem marcados."""
    if triage.category not in ALWAYS_INTERESTING_CATEGORIES:
        return triage
    return replace(
        triage,
        is_interesting=True,
        interesting_reason=triage.interesting_reason or f"Categoria {triage.category.value}",
    )


def decide(
    triage: TriageResult,
    previous_ticket: Ticket | None,
    min_confidence: float,
) -> Decision:
    if previous_ticket is not None:
        # O cliente voltou a escrever: uma pessoa deve continuar o atendimento.
        return Decision(Action.ESCALATE, f"Continuação do chamado {previous_ticket.number}")

    confident = triage.confidence >= min_confidence

    if triage.category is Category.NAO_SUPORTE:
        if confident:
            return Decision(Action.IGNORE, "Não é uma solicitação de suporte")
        return Decision(Action.ESCALATE, "Possível mensagem fora do suporte, com baixa confiança")

    if triage.category not in AUTO_ANSWERABLE_CATEGORIES:
        return Decision(
            Action.ESCALATE, f"A categoria {triage.category.value} exige atendimento da equipe"
        )
    if triage.complexity is Complexity.COMPLEXO:
        return Decision(Action.ESCALATE, "Dúvida classificada como complexa")
    if not confident:
        return Decision(
            Action.ESCALATE, f"Confiança baixa na classificação ({triage.confidence:.2f})"
        )

    return Decision(Action.AUTO_REPLY, "Dúvida simples coberta pela base de conhecimento")
