from __future__ import annotations

from collections.abc import Iterable

from app import db
from database.models.rsi import RSIData
from database.models.rsi_snapshot import RSISnapshot


class RSISnapshotRepository:
    """Acesso ao estado mais recente de cada par/timeframe."""

    @staticmethod
    def atualizar(
        *,
        symbol: str,
        intervalo: str,
        rsi_data_id: int,
    ) -> RSISnapshot:
        snapshot = RSISnapshot.query.filter_by(
            symbol=symbol,
            intervalo=intervalo,
        ).first()

        if snapshot is None:
            snapshot = RSISnapshot(
                symbol=symbol,
                intervalo=intervalo,
                rsi_data_id=rsi_data_id,
            )
            db.session.add(snapshot)
        else:
            snapshot.rsi_data_id = rsi_data_id

        db.session.commit()

        return snapshot

    @staticmethod
    def buscar(
        *,
        symbol: str,
        intervalo: str,
    ) -> RSISnapshot | None:
        return RSISnapshot.query.filter_by(
            symbol=symbol,
            intervalo=intervalo,
        ).first()

    @staticmethod
    def buscar_rsi_atuais(
        *,
        symbol: str,
        intervalos: Iterable[str],
    ) -> dict[str, float]:
        """Retorna o RSI atual de vários períodos em uma única consulta.

        A consulta usa ``rsi_snapshots`` para não misturar candles antigos
        com o estado mais recente de cada par/período.
        """

        intervalos_unicos = tuple(
            dict.fromkeys(
                str(intervalo).strip()
                for intervalo in intervalos
                if str(intervalo).strip()
            )
        )

        if not symbol or not intervalos_unicos:
            return {}

        registros = (
            db.session.query(
                RSISnapshot.intervalo,
                RSIData.rsi,
            )
            .join(
                RSIData,
                RSIData.id == RSISnapshot.rsi_data_id,
            )
            .filter(
                RSISnapshot.symbol == symbol,
                RSISnapshot.intervalo.in_(intervalos_unicos),
            )
            .all()
        )

        return {
            str(intervalo): float(rsi)
            for intervalo, rsi in registros
        }
