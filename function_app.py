"""Azure Functions: dispara o ciclo de atendimento a cada 10 minutos."""

import logging

import azure.functions as func

from omnis_support.app import run_cycle
from omnis_support.config import get_settings
from omnis_support.logging_config import configure_logging

app = func.FunctionApp()

# Formato NCRONTAB: segundo minuto hora dia mês dia-da-semana
EVERY_TEN_MINUTES = "0 */10 * * * *"


@app.timer_trigger(
    schedule=EVERY_TEN_MINUTES,
    arg_name="timer",
    run_on_startup=False,
    use_monitor=True,
)
def check_support_inbox(timer: func.TimerRequest) -> None:
    settings = get_settings()
    configure_logging(settings.log_level)
    if timer.past_due:
        logging.warning("Execução atrasada; processando agora.")

    report = run_cycle(settings)
    if report.failed:
        # Faz a execução aparecer como falha no Application Insights, disparando alertas.
        raise RuntimeError(f"{report.failed} email(s) falharam neste ciclo: {report}")
