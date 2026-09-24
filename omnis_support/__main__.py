"""Execução local.

python -m omnis_support            executa um ciclo (respeita DRY_RUN do .env)
python -m omnis_support migrate    aplica as migrações no DATABASE_URL
"""

from __future__ import annotations

import argparse
import sys

import psycopg

from omnis_support.app import run_cycle
from omnis_support.config import get_settings
from omnis_support.db.migrate import apply_migrations
from omnis_support.logging_config import configure_logging


def main() -> int:
    parser = argparse.ArgumentParser(prog="omnis_support", description="Agente de suporte Omnis")
    parser.add_argument("command", nargs="?", default="run", choices=["run", "migrate"])
    args = parser.parse_args()

    settings = get_settings()
    configure_logging(settings.log_level)

    if args.command == "migrate":
        with psycopg.connect(settings.database_url.get_secret_value(), autocommit=True) as conn:
            applied = apply_migrations(conn)
        print(f"Migrações aplicadas: {', '.join(applied) or 'nenhuma pendente'}")
        return 0

    report = run_cycle(settings)
    return 1 if report.failed else 0


if __name__ == "__main__":
    sys.exit(main())
