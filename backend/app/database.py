"""SQLite 数据库连接与会话管理。"""
import os
import sys
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker


def get_data_dir() -> Path:
    """运行时数据目录：打包后写入用户目录，开发时用 backend/database。"""
    if getattr(sys, "frozen", False):
        base = Path(os.environ.get("APPDATA", Path.home())) / "api-switch"
    else:
        base = Path(__file__).resolve().parent.parent / "database"  # backend/database
    base.mkdir(parents=True, exist_ok=True)
    return base


DATABASE_PATH = get_data_dir() / "api_switch.db"
DATABASE_URL = f"sqlite:///{DATABASE_PATH.as_posix()}"

engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False},
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_db():
    """FastAPI 依赖：请求级数据库会话。"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
