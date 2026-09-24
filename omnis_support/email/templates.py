"""Modelos HTML dos emails enviados. Todo texto dinâmico é escapado."""

from __future__ import annotations

from html import escape
from zoneinfo import ZoneInfo

from omnis_support.domain import IncomingEmail, TriageResult

LOCAL_TIMEZONE = ZoneInfo("America/Sao_Paulo")

_FONT = "font-family:Segoe UI,Arial,sans-serif;font-size:14px;color:#1f2933;line-height:1.5"
_MUTED = "color:#61707d;font-size:12px"


def text_to_html(text: str) -> str:
    """Converte texto simples em parágrafos HTML seguros."""
    paragraphs = [block.strip() for block in text.strip().split("\n\n") if block.strip()]
    return "".join(f"<p>{escape(p).replace(chr(10), '<br>')}</p>" for p in paragraphs)


def first_name_of(name: str | None) -> str | None:
    """Primeiro nome para a saudação; None se o nome não parecer um nome de pessoa."""
    if not name or "@" in name:
        return None
    first = name.strip().split()[0] if name.strip() else ""
    return first.capitalize() if first.isalpha() else None


def _interest_label(triage: TriageResult) -> str:
    if not triage.is_interesting:
        return "Não"
    return f"Sim. {triage.interesting_reason}" if triage.interesting_reason else "Sim"


def auto_reply_html(reply_text: str, signature: str, original: IncomingEmail) -> str:
    sent_at = original.received_at.astimezone(LOCAL_TIMEZONE).strftime("%d/%m/%Y %H:%M")
    author = escape(original.sender_name or original.sender_email)
    return (
        f'<div style="{_FONT}">'
        f"{text_to_html(reply_text)}"
        f"<p>Atenciosamente,<br><strong>{escape(signature)}</strong></p>"
        '<hr style="border:none;border-top:1px solid #d9dee3;margin:24px 0">'
        f'<p style="{_MUTED}">Em {sent_at}, {author} escreveu:</p>'
        f'<blockquote style="border-left:3px solid #d9dee3;margin:0;padding-left:12px;{_MUTED}">'
        f"{text_to_html(original.body)}</blockquote>"
        "</div>"
    )


def acknowledgement_html(customer_name: str | None, ticket_number: str, signature: str) -> str:
    first_name = first_name_of(customer_name)
    greeting = f"Olá, {escape(first_name)}!" if first_name else "Olá!"
    return (
        f'<div style="{_FONT}">'
        f"<p>{greeting}</p>"
        "<p>Recebemos a sua mensagem e ela já foi encaminhada para um especialista da "
        "nossa equipe, que vai entrar em contato com você em breve.</p>"
        f"<p>O número do seu atendimento é <strong>{escape(ticket_number)}</strong>. "
        "Se precisar complementar alguma informação, basta responder este email.</p>"
        "<p>Agradecemos a sua paciência.</p>"
        f"<p>Atenciosamente,<br><strong>{escape(signature)}</strong></p>"
        "</div>"
    )


def escalation_intro_html(
    ticket_number: str,
    email: IncomingEmail,
    reason: str,
    triage: TriageResult | None,
) -> str:
    customer = (
        f"{email.sender_name} <{email.sender_email}>" if email.sender_name else email.sender_email
    )
    rows = [
        ("Chamado", ticket_number),
        ("Cliente", customer),
        ("Motivo do encaminhamento", reason),
    ]
    if triage is not None:
        rows += [
            ("Categoria", triage.category.value),
            ("Resumo", triage.summary),
            ("Dúvida interessante", _interest_label(triage)),
        ]
    table_rows = "".join(
        f'<tr><td style="padding:4px 12px 4px 0;{_MUTED};white-space:nowrap">{escape(label)}</td>'
        f'<td style="padding:4px 0">{escape(value)}</td></tr>'
        for label, value in rows
    )
    return (
        f'<div style="{_FONT};background:#f4f7fa;border:1px solid #d9dee3;'
        'border-radius:6px;padding:16px;margin-bottom:16px">'
        '<p style="margin-top:0"><strong>Atendimento encaminhado pelo Agente Omnis</strong></p>'
        f"<table>{table_rows}</table>"
        '<p style="margin-bottom:0">Clique em <strong>Responder</strong> para falar '
        "diretamente com o cliente. O endereço dele já está configurado como destinatário.</p>"
        "</div>"
    )
