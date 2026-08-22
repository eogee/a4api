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
    native_responses = Column(Boolean, default=False)  # OpenAI 兼容且原生支持 /responses，Codex 可直连
    is_custom = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.now)


class Configuration(Base):
    __tablename__ = "configurations"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=False)
    provider_id = Column(Integer, ForeignKey("providers.id"), nullable=False)
    api_key_encrypted = Column(Text, nullable=False)  # DPAPI 加密后的 base64
    model = Column(String(100), nullable=False)
    targets = Column(String(50), nullable=False, default="claude")  # claude / codex / dsh，逗号分隔可多选
    max_tokens = Column(Integer, nullable=True)  # dsh 单次输出上限；None 时用兜底值（131072）
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


class SkillMigration(Base):
    """Skill 迁移日志（复制语义，一次 source×target 一条）。"""

    __tablename__ = "skill_migrations"

    id = Column(Integer, primary_key=True, index=True)
    skill_name = Column(String(200), nullable=False)
    source_tool = Column(String(20), nullable=False)  # claude / codex / dsh
    source_scope = Column(String(10), nullable=False)  # global / project
    source_project = Column(String(200), nullable=True)
    source_path = Column(String(500), nullable=False)
    target_tool = Column(String(20), nullable=False)
    target_scope = Column(String(10), nullable=False)
    target_project = Column(String(200), nullable=True)
    status = Column(String(20), nullable=False)  # success / failed
    detail = Column(Text, default="")
    migrate_time = Column(DateTime, default=datetime.now)


class SkillTrash(Base):
    """Skill 回收站条目；超 30 天惰性清理，可恢复原位。"""

    __tablename__ = "skill_trash"

    id = Column(Integer, primary_key=True, index=True)
    skill_name = Column(String(200), nullable=False)  # frontmatter name
    dir_name = Column(String(200), nullable=False)  # 目录名（回收站目录前缀）
    tool = Column(String(20), nullable=True)  # 来源端 claude / codex / dsh
    scope = Column(String(10), nullable=True)  # global / project
    project = Column(String(200), nullable=True)  # 项目级来源项目名
    original_path = Column(String(500), nullable=False)  # 原位置（恢复目标）
    trash_path = Column(String(500), nullable=False)  # 回收站中的当前路径
    trash_time = Column(DateTime, default=datetime.now)
