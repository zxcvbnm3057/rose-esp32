"""CustomCommand + PinLock + UartConfig ORM models."""
from datetime import datetime
from sqlalchemy import Column, Integer, String, Text, DateTime
from app.db.database import Base


class CustomCommand(Base):
    __tablename__ = "custom_commands"

    id = Column(Integer, primary_key=True, autoincrement=True)
    slug = Column(String(128), unique=True, nullable=False, index=True)
    name = Column(String(256), nullable=False)
    description = Column(String(1024), default="")
    steps_json = Column(Text, nullable=False)
    enabled = Column(Integer, default=1)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    last_executed_at = Column(DateTime, nullable=True)
    execution_count = Column(Integer, default=0)


class ExecutionLog(Base):
    __tablename__ = "execution_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    command_id = Column(Integer, nullable=False, index=True)
    steps_results = Column(Text, nullable=True)
    success = Column(Integer, default=0)
    error_message = Column(Text, nullable=True)
    duration_ms = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)


class PinLock(Base):
    """Persisted pin state — lock + expected mode/value for mismatch detection."""
    __tablename__ = "pin_locks"

    gpio = Column(Integer, primary_key=True)
    locked = Column(Integer, default=0, nullable=False)
    expected_mode = Column(Integer, nullable=True)
    expected_value = Column(Integer, nullable=True)
    pull = Column(Integer, default=0)
    edge = Column(Integer, default=0)
    config_ts = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class UartConfigModel(Base):
    """Persisted UART configuration so it survives chip reset / page refresh."""
    __tablename__ = "uart_configs"

    uart_id = Column(Integer, primary_key=True)
    baudrate = Column(Integer, nullable=False, default=115200)
    tx_gpio = Column(Integer, nullable=False)
    rx_gpio = Column(Integer, nullable=False)
    data_bits = Column(Integer, default=8)
    parity = Column(Integer, default=0)
    stop_bits = Column(Integer, default=1)
    config_ts = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
