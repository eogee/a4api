"""预置服务商模板初始化（幂等）。"""
from .database import SessionLocal
from .models import Provider

TEMPLATES = [
    {
        "name": "DeepSeek",
        "api_base": "https://api.deepseek.com/anthropic",
        "api_type": "anthropic",
        "is_custom": False,
    },
    {
        "name": "智谱",
        "api_base": "https://open.bigmodel.cn/api/anthropic",
        "api_type": "anthropic",
        "is_custom": False,
    },
    {
        "name": "火山方舟",
        "api_base": "https://ark.cn-beijing.volces.com/api/coding",
        "api_type": "anthropic",
        "is_custom": False,
    },
    {
        "name": "智谱OpenAI兼容接口",
        "api_base": "https://open.bigmodel.cn/api/paas/v4",
        "api_type": "openai",
        "is_custom": False,
    },
    {
        "name": "本地llmstudio接口",
        "api_base": "http://127.0.0.0:1234/v1",
        "api_type": "openai",
        "is_custom": False,
    },
]


def seed_providers() -> None:
    db = SessionLocal()
    try:
        for t in TEMPLATES:
            exists = db.query(Provider).filter(Provider.name == t["name"]).first()
            if not exists:
                db.add(Provider(**t))
        db.commit()
    finally:
        db.close()
