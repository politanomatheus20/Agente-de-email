"""Carrega a base de conhecimento do Omnis a partir de arquivos Markdown."""

from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger(__name__)

# Arquivos com este marcador ainda não foram preenchidos e são ignorados,
# para que o agente nunca responda com informação provisória.
PLACEHOLDER_MARKER = "[PREENCHER]"


def load_knowledge_base(directory: Path) -> str:
    """Concatena os arquivos .md prontos da pasta, em ordem alfabética."""
    if not directory.is_dir():
        logger.warning("Pasta da base de conhecimento não encontrada: %s", directory)
        return ""

    sections: list[str] = []
    for path in sorted(directory.glob("*.md")):
        if path.name.lower() == "readme.md":
            continue
        content = path.read_text(encoding="utf-8").strip()
        if not content:
            continue
        if PLACEHOLDER_MARKER in content:
            logger.warning("Ignorando %s: ainda contém %s", path.name, PLACEHOLDER_MARKER)
            continue
        sections.append(f'<documento nome="{path.stem}">\n{content}\n</documento>')

    if not sections:
        logger.warning("Base de conhecimento vazia: todas as dúvidas serão encaminhadas.")
    return "\n\n".join(sections)
