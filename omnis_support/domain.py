"""Modelos de domínio: o vocabulário do atendimento, independente de infraestrutura."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum


class Category(StrEnum):
    LOGIN = "login"
    SENHA = "senha"
    USO_FUNCIONALIDADE = "uso_funcionalidade"
    CONEXAO_BANCO = "conexao_banco"
    CRIACAO_AGENTE = "criacao_agente"
    DEPARTAMENTO_GRUPO = "departamento_grupo"
    GOVERNANCA_DADOS = "governanca_dados"
    BUG = "bug"
    LENTIDAO = "lentidao"
    PEDIDO_MELHORIA = "pedido_melhoria"
    OUTRO = "outro"
    NAO_SUPORTE = "nao_suporte"


class Complexity(StrEnum):
    SIMPLES = "simples"
    COMPLEXO = "complexo"


class TicketStatus(StrEnum):
    RECEBIDO = "recebido"
    RESPONDIDO_AUTOMATICAMENTE = "respondido_automaticamente"
    ENCAMINHADO = "encaminhado"
    IGNORADO = "ignorado"
    ERRO = "erro"


# Somente estas categorias podem ser respondidas pelo agente sem a equipe.
AUTO_ANSWERABLE_CATEGORIES = frozenset(
    {Category.LOGIN, Category.SENHA, Category.USO_FUNCIONALIDADE}
)

# Estas categorias sempre são marcadas como dúvida interessante.
ALWAYS_INTERESTING_CATEGORIES = frozenset(
    {Category.BUG, Category.LENTIDAO, Category.PEDIDO_MELHORIA}
)


@dataclass(frozen=True, slots=True)
class IncomingEmail:
    message_id: str
    conversation_id: str | None
    internet_message_id: str | None
    sender_email: str
    sender_name: str | None
    subject: str
    body: str
    received_at: datetime
    headers: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class TriageResult:
    category: Category
    complexity: Complexity
    confidence: float
    summary: str
    is_interesting: bool
    interesting_reason: str | None


@dataclass(frozen=True, slots=True)
class DraftReply:
    can_answer: bool
    body: str
    reason: str


@dataclass(frozen=True, slots=True)
class Ticket:
    id: int
    status: TicketStatus
    attempts: int

    @property
    def number(self) -> str:
        return format_ticket_number(self.id)


def format_ticket_number(ticket_id: int) -> str:
    return f"OMN-{ticket_id:06d}"
