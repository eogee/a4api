"""SQLAlchemy 数据模型。"""
from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import relationship

from .database import Base


class Provider(Base):
    __tablename__ = "providers"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), unique=True, nullable=False)
    api_base = Column(String(500), nullable=False)
    api_type = Column(String(20), nullable=False)  # anthropic / openai
    is_custom = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.now)


class Configuration(Base):
    __tablename__ = "configurations"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=False)
    provider_id = Column(Integer, ForeignKey("providers.id"), nullable=False)
    api_key_encrypted = Column(Text, nullable=False)  # DPAPI 加密后的 base64
    model = Column(String(100), nullable=False)
    is_active = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.now)

    provider = relationship("Provider", lazy="joined")


class SwitchLog(Base):
    __tablename__ = "switch_logs"

    id = Column(Integer, primary_key=True, index=True)
    config_id = Column(Integer, nullable=True)
    switch_time = Column(DateTime, default=datetime.now)
    status = Column(String(20), nullable=False)  # success / failed
    detail = Column(Text, default="")


class Backup(Base):
    __tablename__ = "backups"

    id = Column(Integer, primary_key=True, index=True)
    config_id = Column(Integer, nullable=True)
    backup_time = Column(DateTime, default=datetime.now)
    file_path = Column(String(500), nullable=False)
