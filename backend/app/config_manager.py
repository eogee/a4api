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
import yaml

from .database import get_data_dir

CONFIG_FILENAME = "settings.json"
CODEX_CONFIG_FILENAME = "config.toml"
DEFAULT_BACKUP_KEEP = 5
A4API_PROVIDER_PREFIX = "a4api_p"

# dsh（DeepSeek Harness）相关常量
DSH_HOME_ENV = "DSH_HOME"
DSH_SETTINGS_FILENAME = "settings.yaml"
DSH_CREDENTIALS_FILENAME = ".credentials.yaml"
DSH_LLM_NS = "llm-deepseek"
DSH_MODEL_NS = "agent-default-model"
DSH_PROVIDER_ROUTE = "deepseek-official"
DSH_API_KEY_REF = "DEEPSEEK_API_KEY"
# dsh 适配器默认 max_tokens 为 256000，远超多数上游（如智谱）的 131072 输出上限，
# 会把请求直接打回 INVALID_REQUEST；切换时写一个兼容的安全值兜底。
DSH_DEFAULT_MAX_TOKENS = 131072


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
    """规范化配置方案的应用目标列表（claude / codex / dsh）。"""
    result = []
    for t in (targets or "claude").split(","):
        t = (t or "").strip()
        if t in ("claude", "codex", "dsh") and t not in result:
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


def build_settings(
    existing: dict | None,
    provider,
    api_key: str,
    model: str,
    proxy: dict | None = None,
) -> dict:
    """基于现有 settings.json 生成切换后的内容（合并式，保护用户已有配置）。

    anthropic：写 ANTHROPIC_* 环境变量（官方 Claude Code 原生支持）。
    openai：官方 Claude Code 不识别 OPENAI_* 配置，需经由本地翻译代理
    （openai_proxy）把 Anthropic 请求转成 OpenAI 格式；这里把
    ANTHROPIC_BASE_URL 指向本地代理并写入代理鉴权 token。

    只覆盖本工具托管的键（env 中的 ANTHROPIC_AUTH_TOKEN / ANTHROPIC_BASE_URL、
    model、alwaysThinkingEnabled），其余顶层键（hooks、permissions、
    mcpServers、其他 env 变量等）原样保留，避免切换时抹掉用户已有配置。
    """
    if provider.api_type == "openai":
        if not proxy or not proxy.get("base_url") or not proxy.get("token"):
            raise ValueError("OpenAI 类型服务商需要先启动本地翻译代理")
        env = {
            "ANTHROPIC_AUTH_TOKEN": proxy["token"],
            "ANTHROPIC_BASE_URL": proxy["base_url"],
        }
    else:
        env = {
            "ANTHROPIC_AUTH_TOKEN": api_key,
            "ANTHROPIC_BASE_URL": provider.api_base,
        }

    data = dict(existing or {})
    current_env = data.get("env")
    if not isinstance(current_env, dict):
        current_env = {}
    data["env"] = {**current_env, **env}
    data["model"] = model
    data["alwaysThinkingEnabled"] = False
    return data


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


# ---------------- dsh（DeepSeek Harness，~/.dsh） ----------------
#
# dsh 的全局用户文档是 settings.yaml（按 namespace 分段的 YAML），凭证单独存
# 在 .credentials.yaml。llm-deepseek 插件把连接配置放在 `llm-deepseek` 段
# （baseURL / apiKeyEnv），默认模型放在 `agent-default-model` 段
# （provider / model）。dsh 只注册 `deepseek-official` 一个 provider 路由，
# 原生走 OpenAI chat/completions：dsh 目标只支持 openai 类型服务商、直连上游、
# 无需本地翻译代理；配置文件被 watcher 热加载，切换后新会话即生效、免重启。


def dsh_home() -> Path:
    """dsh 数据目录：优先 $DSH_HOME，否则 ~/.dsh。"""
    override = os.environ.get(DSH_HOME_ENV)
    return Path(override) if override else Path.home() / ".dsh"


def dsh_settings_path() -> Path:
    """dsh 全局设置文档路径，可用环境变量 A4API_DSH_SETTINGS_PATH 覆盖。"""
    override = os.environ.get("A4API_DSH_SETTINGS_PATH")
    if override:
        return Path(override)
    return dsh_home() / DSH_SETTINGS_FILENAME


def dsh_credentials_path() -> Path:
    """dsh 凭证文档路径，可用环境变量 A4API_DSH_CREDENTIALS_PATH 覆盖。"""
    override = os.environ.get("A4API_DSH_CREDENTIALS_PATH")
    if override:
        return Path(override)
    return dsh_home() / DSH_CREDENTIALS_FILENAME


def _read_yaml(path: Path) -> dict:
    """读取 YAML 文档为 dict；文件不存在或损坏时返回空字典。"""
    if not path.exists():
        return {}
    try:
        value = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError):
        return {}
    return value if isinstance(value, dict) else {}


def read_dsh_settings() -> dict:
    """读取 dsh settings.yaml。"""
    return _read_yaml(dsh_settings_path())


def read_dsh_credentials() -> dict:
    """读取 dsh .credentials.yaml。"""
    return _read_yaml(dsh_credentials_path())


def _backup_yaml(path: Path, prefix: str) -> Path | None:
    """修改前备份 YAML 文档，返回备份路径；原文件不存在时返回 None。滚动保留最近 N 份。"""
    if not path.exists():
        return None
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    dest = backup_dir() / f"{prefix}.{ts}.yaml.bak"
    shutil.copy2(path, dest)
    backups = sorted(backup_dir().glob(f"{prefix}.*.yaml.bak"))
    for old in backups[:-DEFAULT_BACKUP_KEEP]:
        try:
            old.unlink()
        except OSError:
            pass
    return dest


def backup_dsh_settings() -> Path | None:
    """修改前备份 settings.yaml，返回备份文件路径。"""
    return _backup_yaml(dsh_settings_path(), "dsh.settings")


def backup_dsh_credentials() -> Path | None:
    """修改前备份 .credentials.yaml，返回备份文件路径。"""
    return _backup_yaml(dsh_credentials_path(), "dsh.credentials")


def build_dsh_settings(
    existing: dict | None, provider, model: str, max_tokens: int | None = None,
    proxy: dict | None = None,
) -> dict:
    """基于现有 settings.yaml 生成切换后的内容（合并式，保留 ui-onboarding 等其它段）。

    dsh 只注册 `deepseek-official` 一个 provider 路由，原生走 OpenAI
    chat/completions：baseURL 指向本地翻译代理的 `/chat/completions` 透传
    端点（代理负责归一上游 tool_calls 分片中的 null 字段，规避 dsh 适配器
    把工具名/ID 覆盖为空的问题），apiKeyEnv 固定为 DEEPSEEK_API_KEY 并显式
    写入，key 本体由 build_dsh_credentials() 落到 .credentials.yaml。

    max_tokens：a4api 里为该配置显式填写的单次输出上限，优先于一切既有值；
    留空（None）时保留用户已手动设置的 maxTokens，都没有则用安全默认。
    """
    data = dict(existing or {})
    llm = dict(data.get(DSH_LLM_NS) or {})
    # 经本地翻译代理透传（dsh 始终需要本地代理），代理未就绪时防御性直连。
    proxy_base = (proxy or {}).get("base_url")
    llm["baseURL"] = (
        str(proxy_base).rstrip("/")
        if proxy_base
        else str(provider.api_base).rstrip("/")
    )
    llm["apiKeyEnv"] = DSH_API_KEY_REF
    # 输出上限：显式填写 > 既有手动值 > 安全默认。
    # dsh 适配器默认 256000 会超出多数上游（如智谱）131072 的上限而被打回
    # INVALID_REQUEST，故没有显式值时绝不能放行 dsh 的默认值。
    if max_tokens is not None:
        llm["maxTokens"] = max_tokens
    else:
        llm["maxTokens"] = llm.get("maxTokens") or DSH_DEFAULT_MAX_TOKENS
    data[DSH_LLM_NS] = llm

    model_ns = dict(data.get(DSH_MODEL_NS) or {})
    model_ns["provider"] = DSH_PROVIDER_ROUTE
    model_ns["model"] = model
    data[DSH_MODEL_NS] = model_ns
    return data


def build_dsh_credentials(existing: dict | None, api_key: str, proxy_token: str | None = None) -> dict:
    """在 .credentials.yaml 中写入 DEEPSEEK_API_KEY，保留其它凭证键。

    dsh 经本地翻译代理连接时，写入的应是代理鉴权 token（真实上游 key 由
    代理持有）；proxy_token 缺省时写真实 key（防御性直连场景）。
    """
    creds = dict(existing or {})
    creds[DSH_API_KEY_REF] = proxy_token if proxy_token else api_key
    return creds


def _atomic_write_yaml(path: Path, data: dict) -> None:
    """原子写入 YAML：先写临时文件再替换，避免写入中断损坏配置。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".dsh.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            yaml.safe_dump(
                data, f, allow_unicode=True, sort_keys=False, default_flow_style=False
            )
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


def atomic_write_dsh_settings(data: dict) -> None:
    """原子写入 dsh settings.yaml。"""
    _atomic_write_yaml(dsh_settings_path(), data)


def atomic_write_dsh_credentials(data: dict) -> None:
    """原子写入 dsh .credentials.yaml。"""
    _atomic_write_yaml(dsh_credentials_path(), data)


def read_dsh_selection() -> tuple[str | None, str | None]:
    """读取 dsh 当前生效的默认模型与 provider（agent-default-model 段）。"""
    section = read_dsh_settings().get(DSH_MODEL_NS)
    if not isinstance(section, dict):
        return None, None
    return section.get("model"), section.get("provider")
