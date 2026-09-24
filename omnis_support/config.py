"""Configuração da aplicação, lida de variáveis de ambiente ou do arquivo .env."""

from __future__ import annotations

from datetime import datetime
from functools import lru_cache
from pathlib import Path
from typing import Annotated

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Email
    mailbox_address: str = "suporte@dataomnis.com.br"
    graph_tenant_id: str = ""
    graph_client_id: str = ""
    graph_client_secret: SecretStr = SecretStr("")
    escalation_recipients: Annotated[list[str], NoDecode] = Field(default_factory=list)

    # Claude
    anthropic_api_key: SecretStr = SecretStr("")
    claude_model: str = "claude-opus-5"

    # Banco de dados
    database_url: SecretStr = SecretStr("")

    # Regras de atendimento
    dry_run: bool = True
    min_confidence_auto_reply: float = Field(default=0.8, ge=0.0, le=1.0)
    max_messages_per_run: int = Field(default=25, ge=1, le=100)
    max_attempts: int = Field(default=3, ge=1)
    send_acknowledgement: bool = True
    signature: str = "Equipe de Suporte Omnis"
    process_since: datetime | None = None
    lookback_hours: int = Field(default=24, ge=1, le=24 * 7)
    knowledge_dir: Path = PROJECT_ROOT / "knowledge"
    log_level: str = "INFO"

    @field_validator("escalation_recipients", mode="before")
    @classmethod
    def _split_recipients(cls, value: object) -> object:
        if isinstance(value, str):
            return [item.strip().lower() for item in value.split(",") if item.strip()]
        return value

    @field_validator("process_since", mode="before")
    @classmethod
    def _empty_as_none(cls, value: object) -> object:
        # No Azure, uma configuração não preenchida chega como texto vazio.
        return None if isinstance(value, str) and not value.strip() else value

    @field_validator("knowledge_dir", mode="after")
    @classmethod
    def _resolve_knowledge_dir(cls, value: Path) -> Path:
        return value if value.is_absolute() else PROJECT_ROOT / value

    def require_production_settings(self) -> None:
        """Falha cedo, com mensagem clara, quando falta configuração obrigatória."""
        missing = [
            name
            for name, value in {
                "GRAPH_TENANT_ID": self.graph_tenant_id,
                "GRAPH_CLIENT_ID": self.graph_client_id,
                "GRAPH_CLIENT_SECRET": self.graph_client_secret.get_secret_value(),
                "ANTHROPIC_API_KEY": self.anthropic_api_key.get_secret_value(),
                "ESCALATION_RECIPIENTS": ",".join(self.escalation_recipients),
            }.items()
            if not value
        ]
        if not self.dry_run and not self.database_url.get_secret_value():
            missing.append("DATABASE_URL")
        if missing:
            raise RuntimeError(f"Configuração obrigatória ausente: {', '.join(missing)}")


@lru_cache
def get_settings() -> Settings:
    return Settings()
