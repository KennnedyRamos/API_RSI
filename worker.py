# worker.py

from __future__ import annotations

import logging
import os

from dotenv import load_dotenv


# ==========================================================
# ENV
# ==========================================================

load_dotenv()


# ==========================================================
# LOGGING
# ==========================================================

logging.basicConfig(
    level=os.getenv(
        "LOG_LEVEL",
        "INFO",
    ),
    format=(
        "%(asctime)s | "
        "%(levelname)s | "
        "%(name)s | "
        "%(message)s"
    ),
)

logger = logging.getLogger(
    __name__
)


# ==========================================================
# MAIN
# ==========================================================

def main() -> None:

    # O singleton do worker é criado somente após carregar .env.
    # Isso permite limitar pares e timeframes sem alterar o código.
    from workers.rsi_worker import rsi_worker

    logger.info(
        "Iniciando RSI Worker."
    )

    # O RSIWorker possui uma agenda própria baseada no fechamento
    # real dos candles. Mantê-lo em execução contínua evita que o
    # scheduler reinicialize a agenda a cada disparo.
    rsi_worker.executar()


if __name__ == "__main__":

    main()
