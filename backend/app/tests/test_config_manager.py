import json
from types import SimpleNamespace

import pytest
import yaml

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


# ---------------- dsh（DeepSeek Harness） ----------------


def test_target_list_includes_dsh():
    assert config_manager.target_list("claude,dsh,codex") == ["claude", "dsh", "codex"]
    assert config_manager.target_list("dsh") == ["dsh"]


def test_build_dsh_settings_merges_and_rtrips_baseurl():
    """合并式生成：保留 ui-onboarding 等其它段；baseURL 去掉尾部斜杠。"""
    existing = {"ui-onboarding": {"welcomeNoticeVersion": "2026-08-13.1"}}
    out = config_manager.build_dsh_settings(
        existing, _provider("openai", "https://api.example.com/v1/"), "deepseek-v4-flash"
    )
    assert out["ui-onboarding"] == existing["ui-onboarding"]
    assert out["llm-deepseek"]["baseURL"] == "https://api.example.com/v1"
    assert out["llm-deepseek"]["apiKeyEnv"] == "DEEPSEEK_API_KEY"
    assert out["llm-deepseek"]["maxTokens"] == 131072
    assert out["agent-default-model"] == {
        "provider": "deepseek-official",
        "model": "deepseek-v4-flash",
    }


def test_build_dsh_settings_without_existing():
    out = config_manager.build_dsh_settings(None, _provider("openai"), "m1")
    assert out["llm-deepseek"]["baseURL"] == "https://api.example.com"
    assert out["llm-deepseek"]["maxTokens"] == 131072
    assert out["agent-default-model"]["model"] == "m1"


def test_build_dsh_settings_preserves_existing_max_tokens():
    """未显式填写 max_tokens 时，保留用户已手动设置过的 maxTokens。"""
    existing = {"llm-deepseek": {"maxTokens": 8192}}
    out = config_manager.build_dsh_settings(existing, _provider("openai"), "m1")
    assert out["llm-deepseek"]["maxTokens"] == 8192


def test_build_dsh_settings_explicit_max_tokens_overrides():
    """a4api 显式填写的 max_tokens 优先于既有手动值。"""
    existing = {"llm-deepseek": {"maxTokens": 8192}}
    out = config_manager.build_dsh_settings(
        existing, _provider("openai"), "m1", max_tokens=100000
    )
    assert out["llm-deepseek"]["maxTokens"] == 100000


def test_build_dsh_credentials_preserves_other_keys():
    out = config_manager.build_dsh_credentials({"OTHER_SECRET": "keep"}, "sk-123")
    assert out == {"OTHER_SECRET": "keep", "DEEPSEEK_API_KEY": "sk-123"}


def test_atomic_write_dsh_settings(tmp_path, monkeypatch):
    target = tmp_path / "settings.yaml"
    monkeypatch.setenv("A4API_DSH_SETTINGS_PATH", str(target))
    data = {
        "llm-deepseek": {"baseURL": "https://x.example.com"},
        "ui-onboarding": {"welcomeNoticeVersion": "2026-08-13.1"},
    }
    config_manager.atomic_write_dsh_settings(data)
    assert yaml.safe_load(target.read_text(encoding="utf-8")) == data
    leftovers = [p for p in target.parent.iterdir() if p.name != target.name]
    assert leftovers == []


def test_atomic_write_dsh_credentials(tmp_path, monkeypatch):
    target = tmp_path / ".credentials.yaml"
    monkeypatch.setenv("A4API_DSH_CREDENTIALS_PATH", str(target))
    data = {"DEEPSEEK_API_KEY": "sk-123"}
    config_manager.atomic_write_dsh_credentials(data)
    assert yaml.safe_load(target.read_text(encoding="utf-8")) == data
    leftovers = [p for p in target.parent.iterdir() if p.name != target.name]
    assert leftovers == []


def test_read_dsh_selection(tmp_path, monkeypatch):
    target = tmp_path / "settings.yaml"
    monkeypatch.setenv("A4API_DSH_SETTINGS_PATH", str(target))
    assert config_manager.read_dsh_selection() == (None, None)
    config_manager.atomic_write_dsh_settings(
        {
            "agent-default-model": {
                "provider": "deepseek-official",
                "model": "deepseek-v4-pro",
            }
        }
    )
    assert config_manager.read_dsh_selection() == ("deepseek-v4-pro", "deepseek-official")