"""Testes de integração com um PostgreSQL real, iniciado localmente pelo pgserver."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import psycopg
import pytest

from omnis_support.db.migrate import apply_migrations
from omnis_support.db.repository import PostgresTicketRepository
from omnis_support.domain import Category, TicketStatus
from tests.factories import make_email, make_triage

pgserver = pytest.importorskip("pgserver")


@pytest.fixture(scope="module")
def database_uri(tmp_path_factory: pytest.TempPathFactory) -> Iterator[str]:
    server = pgserver.get_server(Path(tmp_path_factory.mktemp("pgdata")), cleanup_mode="stop")
    yield server.get_uri()
    server.cleanup()


@pytest.fixture
def conn(database_uri: str) -> Iterator[psycopg.Connection]:
    with psycopg.connect(database_uri, autocommit=True) as connection:
        connection.execute("DROP SCHEMA public CASCADE; CREATE SCHEMA public;")
        apply_migrations(connection)
        yield connection


def test_migrations_are_idempotent(conn: psycopg.Connection) -> None:
    assert apply_migrations(conn) == []
    views = {row[0] for row in conn.execute("SELECT viewname FROM pg_views")}
    assert {"vw_duvidas_interessantes", "vw_resumo_por_categoria"} <= views


def test_full_ticket_lifecycle(conn: psycopg.Connection) -> None:
    repo = PostgresTicketRepository(conn)
    email = make_email()

    ticket = repo.claim(email, max_attempts=3)
    assert ticket is not None
    assert ticket.number == "OMN-000001"

    repo.record_triage(
        ticket.id,
        make_triage(
            category=Category.BUG, is_interesting=True, interesting_reason="Erro ao exportar"
        ),
    )
    repo.complete(ticket.id, TicketStatus.ENCAMINHADO, "bug exige a equipe")

    assert repo.claim(email, max_attempts=3) is None
    row = conn.execute("SELECT chamado, categoria, motivo FROM vw_duvidas_interessantes").fetchone()
    assert row == ("OMN-000001", "bug", "Erro ao exportar")

    follow_up = make_email(message_id="msg-2")
    second = repo.claim(follow_up, max_attempts=3)
    assert second is not None
    previous = repo.find_previous_in_conversation(follow_up.conversation_id, second.id)
    assert previous is not None
    assert previous.id == ticket.id


def test_failed_ticket_is_retried_until_max_attempts(conn: psycopg.Connection) -> None:
    repo = PostgresTicketRepository(conn)
    email = make_email()
    ticket = repo.claim(email, max_attempts=2)
    assert ticket is not None

    repo.fail(ticket.id, "erro temporário")
    retry = repo.claim(email, max_attempts=2)
    assert retry is not None
    assert retry.attempts == 2

    repo.fail(retry.id, "erro de novo")
    assert repo.claim(email, max_attempts=2) is None


def test_interrupted_ticket_is_reclaimed_only_after_stale_period(
    conn: psycopg.Connection,
) -> None:
    repo = PostgresTicketRepository(conn)
    email = make_email()
    ticket = repo.claim(email, max_attempts=3)
    assert ticket is not None

    assert repo.claim(email, max_attempts=3) is None

    conn.execute(
        "ALTER TABLE tickets DISABLE TRIGGER trg_tickets_updated_at;"
        "UPDATE tickets SET updated_at = now() - interval '30 minutes';"
        "ALTER TABLE tickets ENABLE TRIGGER trg_tickets_updated_at;"
    )
    resumed = repo.claim(email, max_attempts=3)
    assert resumed is not None
    assert resumed.attempts == 2
