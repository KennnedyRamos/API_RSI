# workers/scheduler.py

from __future__ import annotations

import logging
import os
from apscheduler.schedulers.blocking import (
    BlockingScheduler,
)
from apscheduler.triggers.interval import (
    IntervalTrigger,
)

from workers.rsi_worker import (
    rsi_worker,
)


logger = logging.getLogger(__name__)


class RSIScheduler:
    """
    Scheduler responsável pela execução periódica
    do processamento RSI.
    """

    def __init__(self) -> None:

        self.scheduler = (
            BlockingScheduler(
                timezone="UTC"
            )
        )

        self.interval_minutes = int(
            os.getenv(
                "RSI_WORKER_INTERVAL_MINUTES",
                "5",
            )
        )

    # ==========================================================
    # JOB
    # ==========================================================

    def executar_job(self) -> None:

        logger.info(
            "Executando job automático RSI."
        )

        try:

            resultado = rsi_worker.executar_uma_vez(
                forcar=False,
            )

            logger.info(
                "Job concluído | "
                "resultados=%s | "
                "erros=%s",
                resultado["total_results"],
                resultado["total_errors"],
            )

        except Exception:

            logger.exception(
                "Erro durante execução do job RSI."
            )

    # ==========================================================
    # CONFIGURAR
    # ==========================================================

    def configurar(self) -> None:

        self.scheduler.add_job(
            self.executar_job,
            trigger=IntervalTrigger(
                minutes=self.interval_minutes
            ),
            id="rsi_processing_job",
            replace_existing=True,
            max_instances=1,
            coalesce=True,
        )

        logger.info(
            "Scheduler configurado | "
            "intervalo=%s minutos",
            self.interval_minutes,
        )

    # ==========================================================
    # INICIAR
    # ==========================================================

    def iniciar(self) -> None:

        self.configurar()

        logger.info(
            "Scheduler RSI iniciado."
        )

        try:

            self.scheduler.start()

        except (KeyboardInterrupt, SystemExit):

            logger.info(
                "Scheduler RSI encerrado."
            )

    # ==========================================================
    # PARAR
    # ==========================================================

    def parar(self) -> None:

        if self.scheduler.running:

            self.scheduler.shutdown(
                wait=True
            )


def iniciar_scheduler() -> None:

    scheduler = RSIScheduler()

    scheduler.iniciar()


if __name__ == "__main__":

    iniciar_scheduler()
