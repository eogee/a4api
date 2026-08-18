"""预置服务商模板初始化（幂等，并按模板定义同步预置行）。"""
from .database import SessionLocal
from .models import Provider

TEMPLATES = [
    {
        "name": "DeepSeek-anthropic",
        "api_base": "https://api.deepseek.com/anthropic",
        "api_type": "anthropic",
        "native_responses": False,
        "is_custom": False,
    },
    {
        "name": "智谱-anthropic",
        "api_base": "https://open.bigmodel.cn/api/anthropic",
        "api_type": "anthropic",
        "native_responses": False,
        "is_custom": False,
    },
    {
        "name": "DeepSeek-openai",
        "api_base": "https://api.deepseek.com/",
        "api_type": "openai",
        "native_responses": True,  # DeepSeek 官方原生支持 OpenAI Responses，Codex 可直连上游
        "is_custom": False,
    },
    {
        "name": "智谱-openai",
        "api_base": "https://open.bigmodel.cn/api/paas/v4",
        "api_type": "openai",
        "native_responses": False,
        "is_custom": False,
    },
    {
        "name": "OpenRouter-openai",
        "api_base": "https://openrouter.ai/api/v1",
        "api_type": "openai",
        "native_responses": False,
        "is_custom": False,
    },
    {
        "name": "OpenCodeGo-openai",
        "api_base": "https://opencode.ai/zen/go/v1",
        "api_type": "openai",
        "native_responses": False,
        "is_custom": False,
    },
    {
        "name": "本地llmstudio-openai",
        "api_base": "http://127.0.0.1:1234/v1",
        "api_type": "openai",
        "native_responses": False,
        "is_custom": False,
    }
]

# 预置行可被应用托管同步的字段（以模板定义为准）
SYNC_FIELDS = ("api_base", "api_type", "native_responses")


def seed_providers() -> None:
    """按名称幂等补种缺失的预置模板。

    已有的预置行（is_custom=False）若与模板定义不一致会同步更新，
    如 DeepSeek 升级为原生 Responses 后自动补齐 native_responses；
    自定义行（is_custom=True）始终不做任何改动。
    """
    db = SessionLocal()
    try:
        for t in TEMPLATES:
            exists = db.query(Provider).filter(Provider.name == t["name"]).first()
            if not exists:
                db.add(Provider(**t))
                continue
            if getattr(exists, "is_custom", False):
                continue
            for field in SYNC_FIELDS:
                if field not in t:
                    continue
                if getattr(exists, field, None) != t[field]:
                    setattr(exists, field, t[field])
        db.commit()
    finally:
        db.close()
