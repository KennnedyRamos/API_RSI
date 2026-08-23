# app/__init__.py

from __future__ import annotations

import os
from typing import Any

from dotenv import load_dotenv
from flask import Flask, request
from flask_migrate import Migrate
from flask_sqlalchemy import SQLAlchemy


# ==========================================================
# CARREGAR VARIÁVEIS DE AMBIENTE
# ==========================================================

load_dotenv()


# ==========================================================
# EXTENSÕES
# ==========================================================

db = SQLAlchemy()

migrate = Migrate()


# ==========================================================
# CORS
# ==========================================================

def _origens_cors(configuracao: Any) -> set[str]:
    """Normaliza as origens explicitamente permitidas para o frontend."""

    if isinstance(configuracao, str):
        valores = configuracao.split(",")
    elif isinstance(configuracao, (list, tuple, set, frozenset)):
        valores = configuracao
    else:
        return set()

    return {
        str(valor).strip().rstrip("/")
        for valor in valores
        if str(valor).strip()
    }


# ==========================================================
# CREATE APP
# ==========================================================

def create_app(
    config: dict[str, Any] | None = None,
) -> Flask:
    """
    Factory responsável por criar e configurar
    a aplicação Flask.
    """

    app = Flask(__name__)

    app.config["CORS_ALLOWED_ORIGINS"] = os.getenv(
        "CORS_ALLOWED_ORIGINS",
        "",
    )

    # ======================================================
    # CONFIGURAÇÕES
    # ======================================================

    database_url = (
        config.get("SQLALCHEMY_DATABASE_URI")
        if config is not None
        else None
    ) or os.getenv("DATABASE_URL")

    if not database_url:

        raise RuntimeError(
            "DATABASE_URL não foi configurada "
            "no arquivo .env."
        )

    app.config[
        "SQLALCHEMY_DATABASE_URI"
    ] = database_url

    app.config[
        "SQLALCHEMY_TRACK_MODIFICATIONS"
    ] = False

    if config is not None:
        app.config.update(config)

    @app.after_request
    def adicionar_cabecalhos_cors(response):
        """Libera somente as origens configuradas para a API pública."""

        origem = request.headers.get("Origin", "").strip().rstrip("/")
        origens_permitidas = _origens_cors(
            app.config.get("CORS_ALLOWED_ORIGINS"),
        )

        if origem and origem in origens_permitidas:
            response.headers["Access-Control-Allow-Origin"] = origem
            response.headers["Access-Control-Allow-Methods"] = "GET, OPTIONS"
            response.headers["Access-Control-Allow-Headers"] = "Content-Type"
            response.headers["Access-Control-Max-Age"] = "86400"
            response.headers.add("Vary", "Origin")

        return response

    # ======================================================
    # INICIALIZAR EXTENSÕES
    # ======================================================

    db.init_app(app)

    migrate.init_app(
        app,
        db,
    )

    # ======================================================
    # IMPORTAR MODELS
    # ======================================================
    #
    # Importante para o SQLAlchemy reconhecer os models
    # durante migrations/autogenerate.
    #

    from database.models import (
        NotificationDelivery,
        RSIData,
        RSISnapshot,
        SignalEvent,
    )

    # Evita warning de import não utilizado.
    _ = (
        RSIData,
        RSISnapshot,
        SignalEvent,
        NotificationDelivery,
    )

    # ======================================================
    # REGISTRAR ROTAS
    # ======================================================
    #
    # Todas as rotas da aplicação ficam centralizadas
    # em app/routes.py.
    #

    from app.routes import init_routes

    init_routes(app)

    # ======================================================
    # RETORNAR APLICAÇÃO
    # ======================================================

    return app
