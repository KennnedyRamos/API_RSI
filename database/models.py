import logging
from app import db
from sqlalchemy import Column, Integer, String, Float, DateTime
import datetime

logging.basicConfig(level=logging.DEBUG)

class RSIData(db.Model):
    id = Column(Integer, primary_key=True)
    symbol = Column(String(50), nullable=False)
    intervalo = Column(String(10), nullable=False)
    rsi = Column(Float, nullable=False)
    timestamp = Column(DateTime, nullable=False)
    rsi_status = Column(String(20), nullable=False)
    current_price = Column(Float, nullable=False)  

def insert_rsi_data(symbol, intervalo, rsi, timestamp, rsi_status, current_price):
    try:
        logging.debug(f"Inserindo dados: {symbol}, {intervalo}, {rsi}, {timestamp}, {rsi_status}, {current_price}")
        new_data = RSIData(
            symbol=symbol,
            intervalo=intervalo,
            rsi=rsi,
            timestamp=datetime.datetime.fromtimestamp(timestamp / 1000),
            rsi_status=rsi_status,
            current_price=current_price
        )
        db.session.add(new_data)
        db.session.commit()
        logging.debug("Dados inseridos com sucesso!")
    except Exception as e:
        logging.error(f"Erro ao inserir dados: {e}")
        db.session.rollback()
