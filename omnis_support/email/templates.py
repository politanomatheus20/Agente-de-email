"""Modelos HTML dos emails enviados. Todo texto dinâmico é escapado."""

from __future__ import annotations

from html import escape

from omnis_support.domain import IncomingEmail, TriageResult

_FONT = "font-family:Segoe UI,Arial,sans-serif;font-size:14px;color:#1f2933;line-height:1.5"
_MUTED = "color:#61707d;font-size:12px"


def text_to_html(text: str) -> str:
    """Converte texto simples em parágrafos HTML seguros."""
    paragraphs = [block.strip() for block in text.strip().split("\n\n") if block.strip()]
    return "".join(f"<p>{escape(p).replace(chr(10), '<br>')}</p>" for p in paragraphs)


def auto_reply_html(reply_text: str, signature: str, original: IncomingEmail) -> str:
    sent_at = original.received_at.strftime("%d/%m/%Y %H:%M")
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
    greeting = f"Olá, {escape(customer_name)}!" if customer_name else "Olá!"
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
            ("Dúvida interessante", triage.interesting_reason or "Não"),
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
