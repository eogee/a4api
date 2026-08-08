"""预置模板播种测试。"""
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.app import seed
from backend.app.database import Base
from backend.app.models import Provider


def _make_session(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'seed_test.db'}")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)


def test_seed_providers_inserts_all_templates(tmp_path, monkeypatch):
    """首次播种补齐全部 6 个预置模板。"""
    Session = _make_session(tmp_path)
    monkeypatch.setattr(seed, "SessionLocal", Session)

    seed.seed_providers()

    db = Session()
    names = {p.name for p in db.query(Provider).all()}
    assert names == {t["name"] for t in seed.TEMPLATES}
    assert len(names) == 6
    db.close()


def test_seed_providers_idempotent_and_preserves_custom(tmp_path, monkeypatch):
    """重复播种不产生重复；用户自定义行不被改动。"""
    Session = _make_session(tmp_path)
    monkeypatch.setattr(seed, "SessionLocal", Session)

    db = Session()
    db.add(Provider(name="my-custom", api_base="http://127.0.0.1:9999/v1", api_type="openai", is_custom=True))
    db.commit()
    db.close()

    seed.seed_providers()
    seed.seed_providers()  # 再跑一遍

    db = Session()
    names = [p.name for p in db.query(Provider).all()]
    assert names.count("my-custom") == 1
    for t in seed.TEMPLATES:
        assert names.count(t["name"]) == 1
    db.close()


def test_seed_providers_syncs_prebuilt_native_responses(tmp_path, monkeypatch):
    """预置行与模板定义不一致时同步更新（DeepSeek-openai 补上原生 Responses）。"""
    Session = _make_session(tmp_path)
    monkeypatch.setattr(seed, "SessionLocal", Session)

    db = Session()
    db.add(Provider(
        name="DeepSeek-openai",
        api_base="https://api.deepseek.com/",
        api_type="openai",
        native_responses=False,  # 旧数据：未标记原生 Responses
        is_custom=False,
    ))
    db.commit()
    db.close()

    seed.seed_providers()

    db = Session()
    row = db.query(Provider).filter(Provider.name == "DeepSeek-openai").one()
    assert bool(row.native_responses) is True
    assert row.api_base == "https://api.deepseek.com/"
    db.close()


def test_seed_providers_syncs_prebuilt_api_base(tmp_path, monkeypatch):
    """预置行 api_base 与模板不一致时按模板修正。"""
    Session = _make_session(tmp_path)
    monkeypatch.setattr(seed, "SessionLocal", Session)

    db = Session()
    db.add(Provider(
        name="DeepSeek-anthropic",
        api_base="https://example.com/stale",
        api_type="anthropic",
        native_responses=False,
        is_custom=False,
    ))
    db.commit()
    db.close()

    seed.seed_providers()

    db = Session()
    row = db.query(Provider).filter(Provider.name == "DeepSeek-anthropic").one()
    assert row.api_base == "https://api.deepseek.com/anthropic"
    db.close()


def test_seed_providers_does_not_sync_custom_rows(tmp_path, monkeypatch):
    """自定义行即使与模板同名也不被播种同步覆盖。"""
    Session = _make_session(tmp_path)
    monkeypatch.setattr(seed, "SessionLocal", Session)

    db = Session()
    db.add(Provider(
        name="DeepSeek-openai",
        api_base="https://example.com/custom",
        api_type="openai",
        native_responses=False,
        is_custom=True,
    ))
    db.commit()
    db.close()

    seed.seed_providers()

    db = Session()
    row = db.query(Provider).filter(Provider.name == "DeepSeek-openai").one()
    assert row.is_custom is True
    assert bool(row.native_responses) is False
    assert row.api_base == "https://example.com/custom"
    db.close()
