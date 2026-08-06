import json

from backend.app import config_manager


def test_atomic_write_settings(tmp_path, monkeypatch):
    target = tmp_path / "nested" / "settings.json"
    monkeypatch.setenv("A4API_SETTINGS_PATH", str(target))
    data = {"model": "test-model", "env": {"KEY": "value"}}
    config_manager.atomic_write_settings(data)
    assert target.exists()
    assert json.loads(target.read_text(encoding="utf-8")) == data
    leftovers = [p for p in target.parent.iterdir() if p.name != target.name]
    assert leftovers == []