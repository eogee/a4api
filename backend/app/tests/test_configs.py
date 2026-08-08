"""配置方案保存时的目标应用 × 服务商协议校验测试。"""
import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.app.api.v1 import configs
from backend.app.crypto import encrypt_text
from backend.app.database import Base
from backend.app.models import Configuration, Provider
from backend.app import schemas


def _make_session(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'configs_test.db'}")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)


def _seed_provider(db, api_type="anthropic"):
    p = Provider(
        name=f"provider-{api_type}",
        api_base="https://api.example.com",
        api_type=api_type,
        is_custom=True,
    )
    db.add(p)
    db.commit()
    return p


def test_create_config_rejects_anthropic_provider_with_codex_target(tmp_path):
    """Anthropic 服务商 + targets 含 codex：创建时直接 400，不落库。"""
    Session = _make_session(tmp_path)
    db = Session()
    p = _seed_provider(db, api_type="anthropic")

    with pytest.raises(HTTPException) as exc:
        configs.create_config(
            schemas.ConfigCreate(
                name="双目标",
                provider_id=p.id,
                api_key="sk-test",
                model="claude-test",
                targets="claude,codex",
            ),
            db,
        )

    assert exc.value.status_code == 400
    assert "Codex 需使用 OpenAI 兼容" in str(exc.value.detail)
    assert db.query(Configuration).count() == 0
    db.close()


def test_create_config_allows_openai_provider_with_codex_target(tmp_path):
    """OpenAI 兼容服务商 + targets 含 codex：可正常创建。"""
    Session = _make_session(tmp_path)
    db = Session()
    p = _seed_provider(db, api_type="openai")

    c = configs.create_config(
        schemas.ConfigCreate(
            name="双目标",
            provider_id=p.id,
            api_key="sk-test",
            model="claude-test",
            targets="claude,codex",
        ),
        db,
    )

    assert c.targets == "claude,codex"
    assert c.api_key_encrypted != "sk-test"  # 已加密存储
    db.close()


def test_update_config_rejects_adding_codex_target_to_anthropic_provider(tmp_path):
    """已有配置改为 targets 含 codex 但服务商仍为 Anthropic：更新时 400。"""
    Session = _make_session(tmp_path)
    db = Session()
    p = _seed_provider(db, api_type="anthropic")
    c = Configuration(
        name="仅 Claude",
        provider_id=p.id,
        api_key_encrypted=encrypt_text("sk-test"),
        model="claude-test",
        targets="claude",
    )
    db.add(c)
    db.commit()

    with pytest.raises(HTTPException) as exc:
        configs.update_config(
            c.id,
            schemas.ConfigUpdate(targets="claude,codex"),
            db,
        )

    assert exc.value.status_code == 400
    assert "Codex 需使用 OpenAI 兼容" in str(exc.value.detail)
    db.refresh(c)
    assert c.targets == "claude"  # 目标未变更
    db.close()


def test_update_config_allows_keeping_codex_when_provider_is_openai(tmp_path):
    """OpenAI 服务商 + 双目标更新其它字段：校验通过。"""
    Session = _make_session(tmp_path)
    db = Session()
    p = _seed_provider(db, api_type="openai")
    c = Configuration(
        name="双目标",
        provider_id=p.id,
        api_key_encrypted=encrypt_text("sk-test"),
        model="old-model",
        targets="claude,codex",
    )
    db.add(c)
    db.commit()

    updated = configs.update_config(c.id, schemas.ConfigUpdate(model="new-model"), db)

    assert updated.model == "new-model"
    assert updated.targets == "claude,codex"
    db.close()
