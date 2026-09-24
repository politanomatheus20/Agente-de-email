from datetime import UTC, datetime
from pathlib import Path

import pytest

from omnis_support.ai.knowledge import load_knowledge_base
from omnis_support.ai.prompts import MAX_BODY_CHARS, render_email
from omnis_support.config import Settings
from omnis_support.db.migrate import pending_migrations
from omnis_support.email import templates
from omnis_support.email.filters import skip_reason
from tests.factories import make_email, make_triage


def test_text_to_html_escapes_and_builds_paragraphs() -> None:
    html = templates.text_to_html("Olá <script>\nlinha 2\n\nParágrafo 2")
    assert html == "<p>Olá &lt;script&gt;<br>linha 2</p><p>Parágrafo 2</p>"


def test_escalation_intro_escapes_customer_content() -> None:
    email = make_email(sender_name="<b>Hacker</b>")
    html = templates.escalation_intro_html("OMN-000001", email, "motivo", make_triage())
    assert "<b>Hacker</b>" not in html
    assert "&lt;b&gt;Hacker&lt;/b&gt;" in html


def test_render_email_truncates_long_bodies() -> None:
    rendered = render_email(make_email(body="x" * (MAX_BODY_CHARS + 100)))
    assert "omitido por tamanho" in rendered
    assert rendered.startswith("<email>")


def test_knowledge_base_skips_readme_and_unfinished_files(tmp_path: Path) -> None:
    (tmp_path / "README.md").write_text("instruções", encoding="utf-8")
    (tmp_path / "01-login.md").write_text("# Login\nUse o link Esqueci a senha.", encoding="utf-8")
    (tmp_path / "02-rascunho.md").write_text("Link: [PREENCHER]", encoding="utf-8")

    knowledge = load_knowledge_base(tmp_path)

    assert "Esqueci a senha" in knowledge
    assert "instruções" not in knowledge
    assert "PREENCHER" not in knowledge


def test_knowledge_base_missing_directory_returns_empty(tmp_path: Path) -> None:
    assert load_knowledge_base(tmp_path / "nao-existe") == ""


def test_settings_split_recipients() -> None:
    settings = Settings(
        _env_file=None,
        escalation_recipients=" A@x.com , b@y.com,",  # type: ignore[arg-type]
    )
    assert settings.escalation_recipients == ["a@x.com", "b@y.com"]


def test_migrations_are_found_in_order() -> None:
    names = [path.stem for path in pending_migrations(set())]
    assert names == sorted(names)
    assert names[0] == "001_criar_tabela_chamados"
    assert pending_migrations(set(names)) == []


def test_auto_reply_shows_brasilia_time() -> None:
    email = make_email(received_at=datetime(2026, 9, 24, 15, 30, tzinfo=UTC))
    html = templates.auto_reply_html("Olá!", "Equipe", email)
    assert "24/09/2026 12:30" in html


@pytest.mark.parametrize(
    ("name", "expected"),
    [("Juliana Prado", "Juliana"), ("ana", "Ana"), ("joao@x.com", None), (None, None), ("", None)],
)
def test_first_name_of(name: str | None, expected: str | None) -> None:
    assert templates.first_name_of(name) == expected


def test_acknowledgement_uses_first_name() -> None:
    html = templates.acknowledgement_html("Juliana Prado", "OMN-000003", "Equipe")
    assert "Olá, Juliana!" in html


def test_escalation_shows_interesting_without_reason_as_yes() -> None:
    triage = make_triage(is_interesting=True, interesting_reason=None)
    html = templates.escalation_intro_html("OMN-000001", make_email(), "motivo", triage)
    assert ">Sim<" in html


@pytest.mark.parametrize(
    "subject", ["Resposta automática: Erro de login", "Automatic reply: Ajuda", "Out of Office"]
)
def test_auto_reply_subjects_are_ignored(subject: str) -> None:
    assert skip_reason(make_email(subject=subject), set()) is not None


def test_empty_process_since_from_azure_is_none() -> None:
    settings = Settings(_env_file=None, process_since="")  # type: ignore[arg-type]
    assert settings.process_since is None
