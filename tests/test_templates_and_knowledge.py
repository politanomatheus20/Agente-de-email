from pathlib import Path

from omnis_support.ai.knowledge import load_knowledge_base
from omnis_support.ai.prompts import MAX_BODY_CHARS, render_email
from omnis_support.config import Settings
from omnis_support.db.migrate import pending_migrations
from omnis_support.email import templates
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
