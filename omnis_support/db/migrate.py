"""Aplica as migrações SQL pendentes, em ordem, uma única vez cada."""

from __future__ import annotations

import logging
from pathlib import Path

import psycopg

logger = logging.getLogger(__name__)

MIGRATIONS_DIR = Path(__file__).parent / "migrations"
# Impede que duas execuções simultâneas apliquem a mesma migração.
_ADVISORY_LOCK_ID = 73_100_001


def pending_migrations(applied: set[str]) -> list[Path]:
    return [path for path in sorted(MIGRATIONS_DIR.glob("*.sql")) if path.stem not in applied]


def apply_migrations(conn: psycopg.Connection) -> list[str]:
    """Aplica as migrações pendentes e retorna os nomes aplicados."""
    applied_now: list[str] = []
    with conn.transaction():
        conn.execute("SELECT pg_advisory_xact_lock(%s)", (_ADVISORY_LOCK_ID,))
        conn.execute(
            "CREATE TABLE IF NOT EXISTS schema_migrations ("
            " version TEXT PRIMARY KEY,"
            " applied_at TIMESTAMPTZ NOT NULL DEFAULT now())"
        )
        applied = {row[0] for row in conn.execute("SELECT version FROM schema_migrations")}
        for path in pending_migrations(applied):
            logger.info("Aplicando migração %s", path.name)
            # Sem parâmetros, o psycopg aceita vários comandos no mesmo execute.
            conn.execute(path.read_text(encoding="utf-8").encode())
            conn.execute("INSERT INTO schema_migrations (version) VALUES (%s)", (path.stem,))
            applied_now.append(path.stem)
    return applied_now
