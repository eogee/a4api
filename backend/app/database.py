"""SQLite 数据库连接与会话管理。"""
import os
import shutil
import sys
from pathlib import Path

from sqlalchemy import create_engine, event
from sqlalchemy.orm import declarative_base, sessionmaker

DATA_DIR_NAME = "a4api"
DB_NAME = "a4api.db"
LEGACY_DATA_DIR_NAME = "api-switch"
LEGACY_DB_NAME = "api_switch.db"


def _legacy_data_dir() -> Path:
    """旧版（api-switch）运行时数据目录。"""
    if getattr(sys, "frozen", False):
        return Path(os.environ.get("APPDATA", Path.home())) / LEGACY_DATA_DIR_NAME
    return Path(__file__).resolve().parent.parent / "database"  # backend/database


def _migrate_legacy_data(new_dir: Path) -> None:
    """一次性迁移旧版（api-switch）运行时数据，避免改名后数据“丢失”。"""
    old_dir = _legacy_data_dir()
    if not old_dir.exists() or old_dir.resolve() == new_dir.resolve():
        return
    try:
        if not (new_dir / DB_NAME).exists():
            old_db = old_dir / LEGACY_DB_NAME
            if old_db.exists():
                shutil.copy2(old_db, new_dir / DB_NAME)
        if not (new_dir / "backups").exists():
            old_backups = old_dir / "backups"
            if old_backups.exists():
                shutil.copytree(old_backups, new_dir / "backups")
        if not (new_dir / "proxy.json").exists():
            old_proxy = old_dir / "proxy.json"
            if old_proxy.exists():
                shutil.copy2(old_proxy, new_dir / "proxy.json")
    except OSError:
        pass  # 迁移失败不阻塞启动，仍使用新目录


def get_data_dir() -> Path:
    """运行时数据目录：打包后写入用户目录，开发时用 backend/database。"""
    override = os.environ.get("A4API_DATA_DIR")
    if override:
        base = Path(override)
    elif getattr(sys, "frozen", False):
        base = Path(os.environ.get("APPDATA", Path.home())) / DATA_DIR_NAME
    else:
        base = Path(__file__).resolve().parent.parent / "database"  # backend/database
    base.mkdir(parents=True, exist_ok=True)
    _migrate_legacy_data(base)
    return base


DATABASE_PATH = get_data_dir() / DB_NAME
DATABASE_URL = f"sqlite:///{DATABASE_PATH.as_posix()}"

engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False},
)


@event.listens_for(engine, "connect")
def _enable_sqlite_foreign_keys(dbapi_connection, connection_record):
    """SQLite 默认不启用外键约束，这里按连接开启，避免产生孤儿数据。"""
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_db():
    """FastAPI 依赖：请求级数据库会话。"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
