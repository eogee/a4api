"""SQLite 数据库连接与会话管理。"""
import os
import shutil
import stat
import sys
from pathlib import Path

from sqlalchemy import create_engine, event
from sqlalchemy.orm import declarative_base, sessionmaker

DATA_DIR_NAME = "a4api"
DB_NAME = "a4api.db"
LEGACY_DATA_DIR_NAME = "api-switch"
LEGACY_DB_NAME = "api_switch.db"


def _restrict_permissions(path: Path) -> None:
    """尽力把数据目录/数据库文件权限收紧为仅当前用户。

    Windows 上 chmod 不改变 ACL，主要由 APPDATA/项目目录的 NTFS 权限决定；
    这里对非 Windows 环境仍做 700/600 收紧，属于尽力而为的加固。
    """
    if os.name == "nt":
        return
    try:
        if path.is_dir():
            os.chmod(path, stat.S_IRWXU)
        else:
            os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)
    except OSError:
        pass


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
    _restrict_permissions(base)
    _migrate_legacy_data(base)
    return base


DATABASE_PATH = get_data_dir() / DB_NAME
DATABASE_URL = f"sqlite:///{DATABASE_PATH.as_posix()}"

engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False},
)


def ensure_schema() -> None:
    """轻量迁移：为旧库补充新列（SQLAlchemy create_all 不会修改已存在的表）。"""
    from sqlalchemy import text

    with engine.begin() as conn:
        cols = {row[1] for row in conn.execute(text("PRAGMA table_info(configurations)"))}
        if "targets" not in cols:
            conn.execute(
                text(
                    "ALTER TABLE configurations "
                    "ADD COLUMN targets VARCHAR(50) NOT NULL DEFAULT 'claude'"
                )
            )
        pcols = {row[1] for row in conn.execute(text("PRAGMA table_info(providers)"))}
        if "native_responses" not in pcols:
            conn.execute(
                text(
                    "ALTER TABLE providers "
                    "ADD COLUMN native_responses BOOLEAN NOT NULL DEFAULT 0"
                )
            )


@event.listens_for(engine, "connect")
def _enable_sqlite_foreign_keys(dbapi_connection, connection_record):
    """SQLite 默认不启用外键约束，这里按连接开启，避免产生孤儿数据。"""
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


@event.listens_for(engine, "connect")
def _restrict_db_file_permissions(dbapi_connection, connection_record):
    """数据库文件创建/连接后尽力收紧权限。"""
    _restrict_permissions(DATABASE_PATH)


SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_db():
    """FastAPI 依赖：请求级数据库会话。"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
