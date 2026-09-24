"""Configuração de logs. No Azure, o Application Insights captura o logger raiz."""

import logging

_FORMAT = "%(asctime)s %(levelname)-8s %(name)s | %(message)s"


def configure_logging(level: str = "INFO") -> None:
    logging.basicConfig(level=level.upper(), format=_FORMAT)
    # Bibliotecas HTTP são muito verbosas em INFO.
    for noisy in ("httpx", "httpcore", "msal", "azure"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
