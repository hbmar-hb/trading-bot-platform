"""Modelo para guardar señales de trading recibidas (TradingView, etc.)"""
import uuid
from datetime import datetime
from decimal import Decimal
from sqlalchemy import Column, String, DateTime, Numeric, ForeignKey, Index, JSON
from sqlalchemy.dialects.postgresql import UUID
from app.services.database import Base


class TradingSignal(Base):
    __tablename__ = "trading_signals"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    
    # Identificación de la señal
    source = Column(String(50), nullable=False)  # 'tradingview', 'manual', 'webhook'
    signal_id = Column(String(100))  # ID único de la señal (para evitar duplicados)
    
    # Datos del símbolo y acción
    symbol = Column(String(50), nullable=False)
    action = Column(String(20), nullable=False)  # 'long', 'short', 'close'
    timeframe = Column(String(10))  # '1h', '4h', '1d', etc.
    
    # Precio de la señal
    price = Column(Numeric(20, 8))
    
    # Indicadores/valores adicionales (JSON)
    indicator_values = Column(JSON, default=dict)  # RSI, EMA, etc.
    
    # Estado de procesamiento
    status = Column(String(20), default='pending')  # 'pending', 'processed', 'error', 'ignored'
    error_message = Column(String(500))
    
    # Relación con posición creada
    position_id = Column(UUID(as_uuid=True), ForeignKey("positions.id", ondelete="SET NULL"))
    
    # Timestamps
    received_at = Column(DateTime(timezone=True), default=datetime.utcnow)
    processed_at = Column(DateTime(timezone=True))
    
    # Índices para búsquedas rápidas
    __table_args__ = (
        Index('idx_signals_user_symbol', 'user_id', 'symbol'),
        Index('idx_signals_received_at', 'user_id', 'received_at'),
        Index('idx_signals_status', 'user_id', 'status'),
        Index('idx_signals_unique', 'user_id', 'signal_id', unique=True),
    )
