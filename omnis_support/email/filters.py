"""Regras para descartar emails que não devem ser atendidos (respostas automáticas, loops)."""

from __future__ import annotations

from collections.abc import Collection

from omnis_support.domain import IncomingEmail

_AUTOMATED_SENDER_MARKERS = ("noreply", "no-reply", "donotreply", "mailer-daemon", "postmaster")
_BULK_PRECEDENCE = frozenset({"bulk", "junk", "list", "auto_reply"})
_AUTOREPLY_HEADERS = ("x-autoreply", "x-autorespond")
_AUTOREPLY_SUBJECT_PREFIXES = (
    "resposta automática",
    "automatic reply",
    "auto reply",
    "autoreply",
    "out of office",
    "ausência temporária",
    "fora do escritório",
    "undeliverable",
    "não é possível entregar",
)


def skip_reason(email: IncomingEmail, internal_addresses: Collection[str]) -> str | None:
    """Retorna o motivo para ignorar o email, ou None se ele deve ser atendido."""
    sender = email.sender_email.lower()
    if not sender:
        return "remetente ausente"
    if sender in internal_addresses:
        return "remetente interno (evita loop de respostas)"
    local_part = sender.split("@", 1)[0]
    if any(marker in local_part for marker in _AUTOMATED_SENDER_MARKERS):
        return "remetente automático"

    headers = email.headers
    if headers.get("auto-submitted", "no").strip().lower() != "no":
        return "resposta automática (Auto-Submitted)"
    if headers.get("precedence", "").strip().lower() in _BULK_PRECEDENCE:
        return "email em massa (Precedence)"
    if any(name in headers for name in _AUTOREPLY_HEADERS):
        return "resposta automática"
    if email.subject.strip().lower().startswith(_AUTOREPLY_SUBJECT_PREFIXES):
        return "resposta automática (assunto)"
    return None
