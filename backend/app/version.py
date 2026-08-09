"""运行时版本解析。

版本号单一来源 = pyproject.toml 的 [project].version；打包时 build.py 把版本写入
打包内嵌的 version.json，冻结态从此处读取，开发态直接解析 pyproject.toml。
"""
import json
import re
import sys
from pathlib import Path

_FALLBACK = "0.0.0"
_RE_VERSION = re.compile(r'version\s*=\s*"([\d.]+)"')


def _dev_version() -> str:
    """开发态：解析项目根 pyproject.toml。"""
    root = Path(__file__).resolve().parent.parent.parent  # backend/app/version.py -> 项目根
    try:
        m = _RE_VERSION.search((root / "pyproject.toml").read_text(encoding="utf-8"))
        if m:
            return m.group(1)
    except OSError:
        pass
    return _FALLBACK


def _frozen_version() -> str:
    """冻结态：读取打包时写入 sys._MEIPASS/version.json。"""
    try:
        data = json.loads(
            (Path(getattr(sys, "_MEIPASS", ".")) / "version.json").read_text(encoding="utf-8")
        )
        v = str(data.get("version", ""))
        if v:
            return v
    except (OSError, ValueError, TypeError):
        pass
    return _FALLBACK


def current_version() -> str:
    """当前运行版本号（形如 0.2.0）。解析失败兜底 0.0.0，不阻断启动。"""
    if getattr(sys, "frozen", False):
        return _frozen_version()
    return _dev_version()
