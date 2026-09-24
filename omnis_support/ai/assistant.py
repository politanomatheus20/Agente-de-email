"""Triagem e redação de respostas usando a API do Claude."""

from __future__ import annotations

import logging
from typing import Literal, TypeVar

import anthropic
from anthropic.types import TextBlockParam
from pydantic import BaseModel, Field

from omnis_support.ai.prompts import RESPONDER_SYSTEM_PROMPT, TRIAGE_SYSTEM_PROMPT, render_email
from omnis_support.domain import Category, Complexity, DraftReply, IncomingEmail, TriageResult

logger = logging.getLogger(__name__)

Effort = Literal["low", "medium", "high"]
OutputT = TypeVar("OutputT", bound=BaseModel)

# Se o modelo principal recusar por política de segurança, a própria API
# refaz a chamada no modelo substituto recomendado pela Anthropic.
_FALLBACK_BETA = "server-side-fallback-2026-07-01"


class AssistantError(RuntimeError):
    """O Claude não retornou uma resposta utilizável."""


class _TriageOutput(BaseModel):
    category: Category
    complexity: Complexity
    confidence: float = Field(description="Entre 0 e 1")
    summary: str
    is_interesting: bool
    interesting_reason: str | None


class _ReplyOutput(BaseModel):
    can_answer: bool
    reply: str = Field(description="Texto da resposta ao cliente; vazio se can_answer for falso")
    reason: str = Field(description="Por que a dúvida pode ou não ser respondida")


class ClaudeSupportAssistant:
    def __init__(self, client: anthropic.Anthropic, model: str, knowledge_base: str) -> None:
        self._client = client
        self._model = model
        self._knowledge_base = knowledge_base

    def triage(self, email: IncomingEmail) -> TriageResult:
        output = self._structured_call(
            system=TRIAGE_SYSTEM_PROMPT,
            email=email,
            output_type=_TriageOutput,
            effort="low",
            max_tokens=4_000,
        )
        return TriageResult(
            category=output.category,
            complexity=output.complexity,
            confidence=min(max(output.confidence, 0.0), 1.0),
            summary=output.summary.strip(),
            is_interesting=output.is_interesting,
            interesting_reason=(output.interesting_reason or "").strip() or None,
        )

    def draft_reply(self, email: IncomingEmail) -> DraftReply:
        if not self._knowledge_base:
            return DraftReply(False, "", "base de conhecimento ainda não preenchida")

        output = self._structured_call(
            system=RESPONDER_SYSTEM_PROMPT.format(knowledge_base=self._knowledge_base),
            email=email,
            output_type=_ReplyOutput,
            effort="medium",
            max_tokens=8_000,
        )
        can_answer = output.can_answer and bool(output.reply.strip())
        return DraftReply(can_answer, output.reply.strip(), output.reason.strip())

    def _structured_call(
        self,
        *,
        system: str,
        email: IncomingEmail,
        output_type: type[OutputT],
        effort: Effort,
        max_tokens: int,
    ) -> OutputT:
        # O prompt de sistema é estável entre chamadas; o cache reduz custo e latência.
        system_blocks: list[TextBlockParam] = [
            {"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}
        ]
        response = self._client.messages.parse(
            model=self._model,
            max_tokens=max_tokens,
            system=system_blocks,
            messages=[{"role": "user", "content": render_email(email)}],
            output_format=output_type,
            output_config={"effort": effort},
            extra_headers={"anthropic-beta": _FALLBACK_BETA},
            extra_body={"fallbacks": "default"},
        )

        if response.stop_reason == "refusal":
            raise AssistantError(f"O modelo recusou a solicitação ({response.stop_details})")
        if response.stop_reason == "max_tokens":
            raise AssistantError("A resposta do modelo foi cortada por limite de tokens")
        if response.parsed_output is None:
            raise AssistantError("O modelo não retornou a estrutura esperada")

        logger.debug(
            "Claude %s: entrada=%s saída=%s cache=%s request_id=%s",
            output_type.__name__,
            response.usage.input_tokens,
            response.usage.output_tokens,
            response.usage.cache_read_input_tokens,
            response._request_id,
        )
        return response.parsed_output
