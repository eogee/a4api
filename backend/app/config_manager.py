"""Claude Code settings.json 读写、备份、原子写入。"""
import json
import os
import shutil
import tempfile
from datetime import datetime
from pathlib import Path

from .database import get_data_dir

CONFIG_FILENAME = "settings.json"
DEFAULT_BACKUP_KEEP = 5


def settings_path() -> Path:
    override = os.environ.get("A4API_SETTINGS_PATH")
    if override:
        return Path(override)
    return Path.home() / ".claude" / "settings.json"


def backup_dir() -> Path:
    d = get_data_dir() / "backups"
    d.mkdir(parents=True, exist_ok=True)
    return d


def read_settings() -> dict:
    """读取当前配置；文件不存在或损坏时返回空字典。"""
    path = settings_path()
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def backup_settings() -> Path:
    """修改前备份，返回备份文件路径；原文件不存在时返回 None。滚动保留最近 N 份。"""
    path = settings_path()
    if not path.exists():
        return None
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    dest = backup_dir() / f"settings.{ts}.json.bak"
    shutil.copy2(path, dest)
    backups = sorted(backup_dir().glob("settings.*.json.bak"))
    for old in backups[:-DEFAULT_BACKUP_KEEP]:
        try:
            old.unlink()
        except OSError:
            pass
    return dest


def atomic_write_settings(data: dict) -> None:
    """原子写入：先写临时文件再替换，避免写入中断导致配置损坏。"""
    path = settings_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".settings.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except Exception:
        if os.path.exists(tmp):
            try:
                os.unlink(tmp)
            except OSError:
                pass
        raise


def build_settings(provider, api_key: str, model: str, proxy: dict = None) -> dict:
    """按服务商协议类型生成 settings.json 内容。

    anthropic：写 ANTHROPIC_* 环境变量（官方 Claude Code 原生支持）。
    openai：官方 Claude Code 不识别 OPENAI_* 配置，需经由本地翻译代理
    （openai_proxy）把 Anthropic 请求转成 OpenAI 格式；这里把
    ANTHROPIC_BASE_URL 指向本地代理并写入代理鉴权 token。
    """
    if provider.api_type == "openai":
        if not proxy or not proxy.get("base_url") or not proxy.get("token"):
            raise ValueError("OpenAI 类型服务商需要先启动本地翻译代理")
        return {
            "env": {
                "ANTHROPIC_AUTH_TOKEN": proxy["token"],
                "ANTHROPIC_BASE_URL": proxy["base_url"],
            },
            "model": model,
            "alwaysThinkingEnabled": False,
        }
    return {
        "env": {
            "ANTHROPIC_AUTH_TOKEN": api_key,
            "ANTHROPIC_BASE_URL": provider.api_base,
        },
        "model": model,
        "alwaysThinkingEnabled": False,
    }
