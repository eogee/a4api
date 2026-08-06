"""Claude Code settings.json 读写、备份、原子写入。"""
import copy
import json
import os
import shutil
import tempfile
from datetime import datetime
from pathlib import Path

try:
    import tomllib  # type: ignore[import-not-found]
except ModuleNotFoundError:  # Python 3.10
    import tomli as tomllib

import tomli_w

from .database import get_data_dir

CONFIG_FILENAME = "settings.json"
CODEX_CONFIG_FILENAME = "config.toml"
DEFAULT_BACKUP_KEEP = 5
A4API_PROVIDER_PREFIX = "a4api_p"


def settings_path() -> Path:
    override = os.environ.get("A4API_SETTINGS_PATH")
    if override:
        return Path(override)
    return Path.home() / ".claude" / "settings.json"


def backup_dir() -> Path:
    d = get_data_dir() / "backups"
    d.mkdir(parents=True, exist_ok=True)
    return d


def target_list(targets) -> list:
    """规范化配置方案的应用目标列表（claude / codex）。"""
    result = []
    for t in (targets or "claude").split(","):
        t = (t or "").strip()
        if t in ("claude", "codex") and t not in result:
            result.append(t)
    return result or ["claude"]


def read_settings() -> dict:
    """读取当前配置；文件不存在或损坏时返回空字典。"""
    path = settings_path()
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))  # type: ignore[no-any-return]
    except json.JSONDecodeError:
        return {}


def backup_settings() -> Path | None:
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


def build_settings(provider, api_key: str, model: str, proxy: dict | None = None) -> dict:
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


# ---------------- Codex（~/.codex/config.toml） ----------------


def codex_settings_path() -> Path:
    """Codex 全局配置文件路径，可用环境变量 A4API_CODEX_CONFIG_PATH 覆盖。"""
    override = os.environ.get("A4API_CODEX_CONFIG_PATH")
    if override:
        return Path(override)
    return Path.home() / ".codex" / CODEX_CONFIG_FILENAME


def read_codex_settings() -> dict:
    """读取 Codex config.toml；文件不存在或损坏时返回空字典。"""
    path = codex_settings_path()
    if not path.exists():
        return {}
    try:
        raw = path.read_bytes()
        if raw.startswith(b"\xef\xbb\xbf"):
            raw = raw[3:]
        return tomllib.loads(raw.decode("utf-8"))  # type: ignore[no-any-return]
    except (OSError, ValueError):
        return {}


def backup_codex_settings() -> Path | None:
    """修改前备份 config.toml，返回备份文件路径；原文件不存在时返回 None。"""
    path = codex_settings_path()
    if not path.exists():
        return None
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    dest = backup_dir() / f"codex.config.{ts}.toml.bak"
    shutil.copy2(path, dest)
    backups = sorted(backup_dir().glob("codex.config.*.toml.bak"))
    for old in backups[:-DEFAULT_BACKUP_KEEP]:
        try:
            old.unlink()
        except OSError:
            pass
    return dest


def build_codex_settings(
    existing: dict, provider, api_key: str, model: str, proxy: dict | None = None
) -> dict:
    """基于现有 config.toml 生成新配置：

    更新顶层 model / model_provider，并用 a4api 托管的服务商条目
    （[model_providers.a4api_p*]）替换旧的 a4api 条目，其余配置原样保留。
    Codex CLI（0.146+）使用 OpenAI Responses 协议，wire_api 固定为 responses。
    传入 proxy 时把 base_url 指向本地翻译代理、token 换成代理鉴权 token，
    用于智谱等只提供 Chat Completions、不支持原生 /responses 的上游。
    """
    data = dict(existing)
    providers = dict(data.get("model_providers") or {})
    for key in [k for k in providers if str(k).startswith(A4API_PROVIDER_PREFIX)]:
        providers.pop(key, None)
    provider_key = f"{A4API_PROVIDER_PREFIX}{provider.id}"
    if proxy and proxy.get("base_url") and proxy.get("token"):
        providers[provider_key] = {
            "name": provider.name,
            "base_url": proxy["base_url"],
            "wire_api": "responses",
            "experimental_bearer_token": proxy["token"],
        }
    else:
        providers[provider_key] = {
            "name": provider.name,
            "base_url": provider.api_base,
            "wire_api": "responses",
            "experimental_bearer_token": api_key,
        }
    data["model_providers"] = providers
    data["model"] = model
    data["model_provider"] = provider_key
    return data


def atomic_write_codex_settings(data: dict) -> None:
    """原子写入 config.toml：先写临时文件再替换，避免写入中断损坏配置。"""
    path = codex_settings_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".codex-config.", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as f:
            tomli_w.dump(data, f)
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


# ---------------- Codex 模型目录（model_catalog_json） ----------------


def codex_catalog_path(existing: dict | None = None) -> Path:
    """Codex 自定义模型目录路径，可用环境变量 A4API_CODEX_CATALOG_PATH 覆盖。"""
    override = os.environ.get("A4API_CODEX_CATALOG_PATH")
    if override:
        return Path(override)
    catalog = (existing or {}).get("model_catalog_json")
    if catalog:
        return Path(str(catalog).strip('"'))
    return Path.home() / ".codex" / "models.json"


_MODEL_CATALOG_TEMPLATE = {
    "slug": "",
    "prefer_websockets": False,
    "support_verbosity": True,
    "default_verbosity": "low",
    "apply_patch_tool_type": "freeform",
    "web_search_tool_type": "text",
    "input_modalities": ["text"],
    "supports_image_detail_original": False,
    "truncation_policy": {"mode": "tokens", "limit": 10000},
    "supports_parallel_tool_calls": True,
    "tool_mode": None,
    "multi_agent_version": "v2",
    "use_responses_lite": False,
    "include_skills_usage_instructions": False,
    "auto_review_model_override": None,
    "context_window": 200000,
    "max_context_window": 200000,
    "effective_context_window_percent": 95,
    "auto_compact_token_limit": None,
    "comp_hash": "3000",
    "reasoning_summary_format": "experimental",
    "default_reasoning_summary": "none",
    "default_reasoning_level": "high",
    "supported_reasoning_levels": [
        {"effort": "low", "description": "Fast responses with lighter reasoning"},
        {"effort": "high", "description": "Extra high reasoning depth for complex problems"},
        {"effort": "max", "description": "Maximum reasoning depth for the hardest problems"},
    ],
    "shell_type": "shell_command",
    "visibility": "list",
    "minimal_client_version": "0.144.0",
    "supported_in_api": True,
    "priority": 1,
}


def ensure_model_in_catalog(model: str, existing: dict | None = None) -> dict:
    """确保模型出现在 model_catalog_json 中，供 Codex 解析自定义模型能力。

    已存在则直接返回；不存在时优先复制目录中已有条目（如 deepseek-v4-flash）
    的完整结构，仅替换标识字段，避免因缺字段导致 Codex 解析失败。
    """
    path = codex_catalog_path(existing)
    data: dict = {"models": []}
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            data = {"models": []}
    models = data.setdefault("models", [])
    existing_entry = next(
        (m for m in models if isinstance(m, dict) and m.get("slug") == model),
        None,
    )
    if existing_entry is not None and (
        "model_messages" in existing_entry or "base_instructions" in existing_entry
    ):
        return data
    if existing_entry is not None:
        # 已有简略条目时移除，按完整模板重建，避免 Codex 无法解析模型元数据
        models.remove(existing_entry)

    template = next((copy.deepcopy(m) for m in models if isinstance(m, dict)), None)
    if template is None:
        # 目标目录为空时，优先从默认用户目录复制完整条目结构（如 deepseek-v4-flash），
        # 避免简略模板缺字段导致 Codex 无法解析模型元数据。
        try:
            default_path = codex_catalog_path()
            if default_path != path and default_path.exists():
                default_data = json.loads(default_path.read_text(encoding="utf-8-sig"))
                template = next(
                    (
                        copy.deepcopy(m)
                        for m in default_data.get("models", [])
                        if isinstance(m, dict)
                    ),
                    None,
                )
        except (OSError, ValueError):
            template = None
    template = template or copy.deepcopy(_MODEL_CATALOG_TEMPLATE)
    entry = template
    entry["slug"] = model
    entry["display_name"] = model
    entry["description"] = f"{model} via a4api local proxy"
    if "context_window" in entry:
        entry["context_window"] = 200000
    if "max_context_window" in entry:
        entry["max_context_window"] = 200000
    if "effective_context_window_percent" in entry:
        entry["effective_context_window_percent"] = 95
    models.append(entry)

    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".models.", suffix=".tmp")
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
    return data
