import pytest

from omnis_support.domain import Category, Complexity, Ticket, TicketStatus
from omnis_support.services.decision import Action, apply_interest_rules, decide
from tests.factories import make_triage

MIN_CONFIDENCE = 0.8


@pytest.mark.parametrize("category", [Category.LOGIN, Category.SENHA, Category.USO_FUNCIONALIDADE])
def test_simple_confident_question_is_auto_replied(category: Category) -> None:
    decision = decide(make_triage(category=category), None, MIN_CONFIDENCE)
    assert decision.action is Action.AUTO_REPLY


@pytest.mark.parametrize(
    "category",
    [
        Category.CONEXAO_BANCO,
        Category.CRIACAO_AGENTE,
        Category.DEPARTAMENTO_GRUPO,
        Category.GOVERNANCA_DADOS,
        Category.BUG,
        Category.LENTIDAO,
        Category.PEDIDO_MELHORIA,
        Category.OUTRO,
    ],
)
def test_complex_categories_are_always_escalated(category: Category) -> None:
    # Mesmo que o modelo erre e diga "simples", a regra de negócio prevalece.
    triage = make_triage(category=category, complexity=Complexity.SIMPLES)
    assert decide(triage, None, MIN_CONFIDENCE).action is Action.ESCALATE


def test_simple_category_marked_complex_is_escalated() -> None:
    triage = make_triage(complexity=Complexity.COMPLEXO)
    assert decide(triage, None, MIN_CONFIDENCE).action is Action.ESCALATE


def test_low_confidence_is_escalated() -> None:
    decision = decide(make_triage(confidence=0.6), None, MIN_CONFIDENCE)
    assert decision.action is Action.ESCALATE
    assert "0.60" in decision.reason


def test_follow_up_in_same_conversation_is_escalated() -> None:
    previous = Ticket(id=42, status=TicketStatus.RESPONDIDO_AUTOMATICAMENTE, attempts=1)
    decision = decide(make_triage(), previous, MIN_CONFIDENCE)
    assert decision.action is Action.ESCALATE
    assert "OMN-000042" in decision.reason


def test_confident_non_support_is_ignored() -> None:
    triage = make_triage(category=Category.NAO_SUPORTE, confidence=0.9)
    assert decide(triage, None, MIN_CONFIDENCE).action is Action.IGNORE


def test_uncertain_non_support_is_escalated_to_avoid_losing_customers() -> None:
    triage = make_triage(category=Category.NAO_SUPORTE, confidence=0.5)
    assert decide(triage, None, MIN_CONFIDENCE).action is Action.ESCALATE


@pytest.mark.parametrize("category", [Category.BUG, Category.LENTIDAO, Category.PEDIDO_MELHORIA])
def test_bug_slowness_and_improvements_are_always_interesting(category: Category) -> None:
    result = apply_interest_rules(make_triage(category=category, is_interesting=False))
    assert result.is_interesting
    assert result.interesting_reason


def test_interest_rules_keep_model_reason() -> None:
    triage = make_triage(category=Category.BUG, interesting_reason="Erro ao exportar relatório")
    assert apply_interest_rules(triage).interesting_reason == "Erro ao exportar relatório"


def test_interest_rules_do_not_touch_other_categories() -> None:
    triage = make_triage(category=Category.LOGIN, is_interesting=False)
    assert apply_interest_rules(triage) is triage
