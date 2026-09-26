"""数据目录迁移（品牌改名 a4api → a4agent）测试。"""
from backend.app import database


def test_migrate_whole_dir_rename(tmp_path, monkeypatch):
    """打包态典型路径：旧 %APPDATA%\\a4api 整目录改名迁入 a4agent，旧库名同步替换。"""
    old_dir = tmp_path / "a4api"
    (old_dir / "backups").mkdir(parents=True)
    (old_dir / "a4api.db").write_bytes(b"db")
    (old_dir / "proxy.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(database, "_legacy_data_dir", lambda name: tmp_path / name)

    new_dir = tmp_path / "a4agent"
    new_dir.mkdir()  # get_data_dir 会先建空目录
    database._migrate_legacy_data(new_dir)

    assert not old_dir.exists()  # 整目录已改名
    assert (new_dir / "a4agent.db").read_bytes() == b"db"
    assert (new_dir / "backups").is_dir()
    assert (new_dir / "proxy.json").exists()


def test_migrate_copy_fallback_when_target_has_data(tmp_path, monkeypatch):
    """新目录已有数据时退化为逐项拷贝，旧目录保留原样。"""
    old_dir = tmp_path / "a4api"
    old_dir.mkdir()
    (old_dir / "a4api.db").write_bytes(b"db")
    (old_dir / "proxy.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(database, "_legacy_data_dir", lambda name: tmp_path / name)

    new_dir = tmp_path / "a4agent"
    (new_dir / "updates").mkdir(parents=True)  # 非空 → 不做整目录改名
    database._migrate_legacy_data(new_dir)

    assert old_dir.exists()
    assert (new_dir / "a4agent.db").read_bytes() == b"db"
    assert (new_dir / "proxy.json").exists()


def test_migrate_dev_mode_db_file_rename(tmp_path, monkeypatch):
    """开发态新旧目录同为 backend/database：只做库文件改名 a4api.db → a4agent.db。"""
    data_dir = tmp_path / "database"
    data_dir.mkdir()
    (data_dir / "a4api.db").write_bytes(b"db")
    monkeypatch.setattr(database, "_legacy_data_dir", lambda name: data_dir)

    database._migrate_legacy_data(data_dir)

    assert (data_dir / "a4agent.db").read_bytes() == b"db"
    assert not (data_dir / "a4api.db").exists()


def test_migrate_noop_when_nothing_legacy(tmp_path, monkeypatch):
    """无遗留目录时迁移为零操作，不报错。"""
    monkeypatch.setattr(database, "_legacy_data_dir", lambda name: tmp_path / name)
    new_dir = tmp_path / "a4agent"
    new_dir.mkdir()
    database._migrate_legacy_data(new_dir)
    assert new_dir.is_dir()
    assert not (new_dir / "a4agent.db").exists()
