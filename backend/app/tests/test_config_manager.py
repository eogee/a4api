import json
from types import SimpleNamespace

import pytest

from backend.app import config_manager


def _provider(api_type="anthropic", api_base="https://api.example.com"):
    return SimpleNamespace(api_type=api_type, api_base=api_base)


def test_build_settings_preserves_existing_keys():
    """合并式生成：hooks / permissions / 其他 env 等用户已有键原样保留。"""
    existing = {
        "model": "old-model",
        "hooks": {
            "Stop": [
                {"hooks": [{"type": "command", "command": "a4p hook claude"}]}
            ]
        },
        "permissions": {"allow": ["Bash(echo *)"]},
        "env": {
            "CUSTOM_VAR": "keep-me",
            "ANTHROPIC_BASE_URL": "https://old.example.com",
        },
        "alwaysThinkingEnabled": True,
    }
    out = config_manager.build_settings(
        existing, _provider(), "sk-123", "new-model"
    )

    assert out["model"] == "new-model"
    assert out["hooks"] == existing["hooks"]
    assert out["permissions"] == existing["permissions"]
    assert out["env"]["CUSTOM_VAR"] == "keep-me"
    assert out["env"]["ANTHROPIC_AUTH_TOKEN"] == "sk-123"
    assert out["env"]["ANTHROPIC_BASE_URL"] == "https://api.example.com"
    assert out["alwaysThinkingEnabled"] is False


def test_build_settings_without_existing():
    """无现有配置时生成全新的三键内容。"""
    out = config_manager.build_settings(None, _provider(), "sk-123", "m")
    assert out == {
        "env": {
            "ANTHROPIC_AUTH_TOKEN": "sk-123",
            "ANTHROPIC_BASE_URL": "https://api.example.com",
        },
        "model": "m",
        "alwaysThinkingEnabled": False,
    }


def test_build_settings_openai_requires_proxy():
    """OpenAI 类型服务商未提供本地代理时应报错。"""
    with pytest.raises(ValueError, match="本地翻译代理"):
        config_manager.build_settings(None, _provider("openai"), "sk-123", "m")


def test_build_settings_openai_with_proxy():
    """OpenAI 类型服务商写入指向本地代理的 env。"""
    out = config_manager.build_settings(
        None,
        _provider("openai"),
        "sk-123",
        "m",
        proxy={"base_url": "http://127.0.0.1:17890", "token": "t"},
    )
    assert out["env"]["ANTHROPIC_BASE_URL"] == "http://127.0.0.1:17890"
    assert out["env"]["ANTHROPIC_AUTH_TOKEN"] == "t"


def test_atomic_write_settings(tmp_path, monkeypatch):
    target = tmp_path / "nested" / "settings.json"
    monkeypatch.setenv("A4API_SETTINGS_PATH", str(target))
    data = {"model": "test-model", "env": {"KEY": "value"}}
    config_manager.atomic_write_settings(data)
    assert target.exists()
    assert json.loads(target.read_text(encoding="utf-8")) == data
    leftovers = [p for p in target.parent.iterdir() if p.name != target.name]
    assert leftovers == []