"""Skill 管理业务层测试：发现聚合 / 迁移复制 / 回收站往返 / 过期清理。

全部通过 tmp_path + monkeypatch 隔离路径，绝不触碰真实用户目录。
"""
import pathlib
from datetime import datetime, timedelta

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.app import schemas, skill_manager
from backend.app.api.v1 import skills as skills_api
from backend.app.database import Base
from backend.app.models import SkillMigration, SkillTrash


# ---------------- 基础设施 ----------------


@pytest.fixture()
def env(tmp_path, monkeypatch):
    """隔离三端 skill 根、数据目录与项目根列表。返回上下文字典。"""
    ctx = {
        "data": tmp_path / "data",
        "claude": tmp_path / "claude-skills",
        "codex": tmp_path / "codex-skills",
        "dsh": tmp_path / "dsh-skills",
        "projects_root": tmp_path / "projects",
    }
    monkeypatch.setenv("A4API_DATA_DIR", str(ctx["data"]))
    monkeypatch.setenv("A4API_CLAUDE_SKILLS_PATH", str(ctx["claude"]))
    monkeypatch.setenv("A4API_CODEX_SKILLS_PATH", str(ctx["codex"]))
    monkeypatch.setenv("A4API_DSH_SKILLS_PATH", str(ctx["dsh"]))
    for key in ("claude", "codex", "dsh"):
        ctx[key].mkdir(parents=True)
    ctx["projects_root"].mkdir(parents=True)
    # 项目根指向临时目录下的 projects_root
    skill_manager.save_project_roots([str(ctx["projects_root"])])
    return ctx


@pytest.fixture()
def db(env):
    engine = create_engine(f"sqlite:///{env['data'] / 'skills_test.db'}")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()


def make_project(env, name: str):
    p = env["projects_root"] / name
    p.mkdir(parents=True, exist_ok=True)
    return p


def make_skill(root, dir_name: str, name: str | None = None, description: str = ""):
    """在 root 下创建一个合法 skill bundle，返回其目录。"""
    d = root / dir_name
    d.mkdir(parents=True, exist_ok=True)
    fm = ["---"]
    if name:
        fm.append(f"name: {name}")
    fm.append(f'description: "{description}"')
    fm.append("---")
    (d / skill_manager.SKILL_FILE).write_text(
        "\n".join(fm) + f"\n\n# {name or dir_name}\n正文内容\n", encoding="utf-8"
    )
    return d


# ---------------- 发现 ----------------


def test_discover_aggregates_and_marks_duplicates(env):
    """同名 skill 跨端聚合并标注端数；.system 与非法目录被跳过。"""
    make_skill(env["claude"], "git-commit", "git-commit", "Claude 版提交技能")
    make_skill(env["dsh"], "git-commit-dsh-dir", "git-commit", "dsh 版提交技能")
    # codex 保留目录 .system 不视为用户 skill
    sys_dir = env["codex"] / ".system" / "builtin"
    sys_dir.mkdir(parents=True)
    make_skill(sys_dir, "builtin-skill", "builtin-skill", "内置")
    # 无 SKILL.md 的目录不是合法 bundle
    orphan = env["codex"] / "not-a-bundle"
    orphan.mkdir()

    data = skill_manager.discover()
    global_names = {g["name"]: g for g in data["global"]}
    assert set(global_names) == {"git-commit"}  # .system / 孤儿目录均被跳过
    g = global_names["git-commit"]
    assert g["end_count"] == 2
    assert g["duplicate"] is True
    assert g["ends"] == ["claude", "dsh"]
    assert len(g["copies"]) == 2
    assert g["description"] == "Claude 版提交技能"


def test_discover_projects_only_include_ones_with_skills(env):
    """仅收录含至少一个 skill 的项目；项目内跨端聚合并标注。"""
    pa = make_project(env, "proj-a")
    pb = make_project(env, "proj-b")  # 无任何 skill，不应出现在结果里
    make_skill(pa / ".claude" / "skills", "deploy", "deploy", "部署")
    make_skill(pa / ".codex" / "skills", "deploy-codex", "deploy", "部署")

    data = skill_manager.discover()
    projects = {p["project"]: p for p in data["projects"]}
    assert "proj-a" in projects
    assert "proj-b" not in projects
    groups = {g["name"]: g for g in projects["proj-a"]["skills"]}
    assert set(groups) == {"deploy"}
    assert groups["deploy"]["end_count"] == 2
    assert groups["deploy"]["duplicate"] is True
    tools = sorted(c["tool"] for c in groups["deploy"]["copies"])
    assert tools == ["claude", "codex"]


def test_project_roots_roundtrip_and_validation(env):
    """项目根列表 GET/PUT 往返；非法输入被拒绝。"""
    assert len(skill_manager.load_project_roots()) == 1

    other = env["projects_root"].parent / "other-roots"
    other.mkdir()
    body = schemas.ProjectRootsIn(roots=[str(other)])
    resp = skills_api.put_project_roots(body)
    assert resp["roots"] == [str(other)]
    assert skill_manager.load_project_roots() == [str(other)]

    with pytest.raises(ValueError):
        skill_manager.save_project_roots(["relative/path"])
    with pytest.raises(ValueError):
        skill_manager.save_project_roots([str(env["projects_root"] / "nope")])
    # API 层把 ValueError 包装为 400
    with pytest.raises(HTTPException) as exc:
        skills_api.put_project_roots(schemas.ProjectRootsIn(roots=[]))
    assert exc.value.status_code == 400


# ---------------- 迁移（复制语义） ----------------


def test_migrate_copies_to_multiple_targets_keeps_source(env, db):
    """多目标迁移：目标各得一份副本，源端保留，日志逐对落库。"""
    src = make_skill(env["claude"], "git-commit", "git-commit", "v1")
    result = skill_manager.migrate(
        db,
        [{"scope": "global", "tool": "claude", "project": None, "name": "git-commit"}],
        [
            {"scope": "global", "tool": "codex", "project": None},
            {"scope": "global", "tool": "dsh", "project": None},
        ],
    )
    assert result["migrated"] == 2 and result["failed"] == 0
    assert src.exists()  # 复制语义：源保留
    assert (env["codex"] / "git-commit" / "SKILL.md").exists()
    assert (env["dsh"] / "git-commit" / "SKILL.md").exists()
    logs = db.query(SkillMigration).all()
    assert len(logs) == 2
    assert all(l.status == "success" for l in logs)


def test_migrate_skips_identical_location(env, db):
    """源与目标完全一致时跳过，不做复制。"""
    make_skill(env["claude"], "git-commit", "git-commit")
    result = skill_manager.migrate(
        db,
        [{"scope": "global", "tool": "claude", "project": None, "name": "git-commit"}],
        [{"scope": "global", "tool": "claude", "project": None}],
    )
    assert result["skipped"] == 1
    assert result["migrated"] == 0


def test_migrate_trashes_same_name_conflict_before_write(env, db):
    """目标端已有同名 skill（同目录名或同 frontmatter name）先进回收站再写入。"""
    make_skill(env["claude"], "deploy", "deploy", "新版本内容")
    old_same_dir = make_skill(env["codex"], "deploy", "deploy", "旧版本-同目录名")
    old_diff_dir = make_skill(env["dsh"], "deploy-old", "deploy", "旧版本-不同目录名但同名")

    result = skill_manager.migrate(
        db,
        [{"scope": "global", "tool": "claude", "project": None, "name": "deploy"}],
        [
            {"scope": "global", "tool": "codex", "project": None},
            {"scope": "global", "tool": "dsh", "project": None},
        ],
    )
    assert result["conflicts_trashed"] == 2

    # codex 目标：旧版已进回收站，新内容就位（新旧目录名相同，需看内容区分）
    new_codex = env["codex"] / "deploy"
    assert "新版本内容" in (new_codex / "SKILL.md").read_text(encoding="utf-8")
    # dsh 目标：不同目录名的同名旧版同样被移入回收站
    assert not (env["dsh"] / "deploy-old").exists()

    trash_rows = db.query(SkillTrash).all()
    assert len(trash_rows) == 2
    origins = {pathlib.Path(r.original_path) for r in trash_rows}
    assert old_same_dir in origins
    assert old_diff_dir in origins
    recycle = skill_manager.trash_dir()
    for row in trash_rows:
        tp = pathlib.Path(row.trash_path)
        assert recycle in tp.parents
        assert tp.exists()


def test_migrate_to_project_target_requires_known_project(env, db):
    """项目级迁移需指定已知项目；未知项目报错且不留日志。"""
    make_skill(env["claude"], "deploy", "deploy", "x")
    with pytest.raises(ValueError, match="未找到项目"):
        skill_manager.migrate(
            db,
            [{"scope": "global", "tool": "claude", "project": None, "name": "deploy"}],
            [{"scope": "project", "tool": "codex", "project": "ghost"}],
        )

    proj = make_project(env, "real-proj")
    result = skill_manager.migrate(
        db,
        [{"scope": "global", "tool": "claude", "project": None, "name": "deploy"}],
        [{"scope": "project", "tool": "codex", "project": "real-proj"}],
    )
    assert result["migrated"] == 1
    assert (proj / ".codex" / "skills" / "deploy" / "SKILL.md").exists()


def test_migrate_unknown_source_fails_cleanly(env, db):
    with pytest.raises(ValueError, match="未找到 skill"):
        skill_manager.migrate(
            db,
            [{"scope": "global", "tool": "codex", "project": None, "name": "nope"}],
            [{"scope": "global", "tool": "dsh", "project": None}],
        )
    assert db.query(SkillMigration).count() == 0


def test_migrate_api_route_writes_log(env, db):
    """API 路由层直调：schema 校验 + 业务落库贯通。"""
    make_skill(env["claude"], "release", "release", "发布")
    body = schemas.SkillMigrateIn(
        sources=[schemas.SkillSourceIn(scope="global", tool="claude", name="release")],
        targets=[schemas.SkillTargetIn(scope="global", tool="dsh")],
    )
    result = skills_api.migrate_skills(body, db)
    assert result["migrated"] == 1
    logs = skills_api.migration_logs(db)
    assert len(logs) == 1
    assert logs[0]["status"] == "success"
    assert "全局" in logs[0]["target"]


# ---------------- 删除 → 回收站 → 恢复 ----------------


def test_delete_restore_roundtrip(env, db):
    proj = make_project(env, "proj-x")
    skill_dir = make_skill(proj / ".dsh" / "skills", "note-taker", "note-taker", "笔记")
    path_text = str(skill_dir)

    deleted = skill_manager.delete_to_trash(db, path_text)
    assert deleted["deleted"] is True
    assert not skill_dir.exists()  # 原位置已空

    listing = skill_manager.list_trash(db)
    assert listing["purged_expired"] == 0
    assert len(listing["items"]) == 1
    item = listing["items"][0]
    assert item["name"] == "note-taker"
    assert item["scope"] == "project"
    assert item["project"] == "proj-x"

    restored = skill_manager.restore_from_trash(db, item["id"])
    assert restored["restored"] is True
    assert skill_dir.exists()
    assert "笔记" in (skill_dir / "SKILL.md").read_text(encoding="utf-8")
    assert skill_manager.list_trash(db)["items"] == []


def test_restore_blocked_when_original_occupied(env, db):
    proj = make_project(env, "proj-y")
    skill_dir = make_skill(proj / ".claude" / "skills", "guard", "guard", "占用测试")
    info = skill_manager.delete_to_trash(db, str(skill_dir))
    item_id = skill_manager.list_trash(db)["items"][0]["id"]

    occupant = make_skill(proj / ".claude" / "skills", "guard", "guard", "新住户")
    with pytest.raises(ValueError, match="原位置已存在"):
        skill_manager.restore_from_trash(db, item_id)
    assert occupant.exists()


def test_delete_rejects_paths_outside_known_roots(env, db):
    outside = env["projects_root"].parent / "random" / "evil-skill"
    outside.mkdir(parents=True)
    make_skill(outside.parent, "evil-skill", "evil-skill")
    with pytest.raises(ValueError, match="不在任何已知 skill 存放区"):
        skill_manager.delete_to_trash(db, str(outside))


# ---------------- 过期清理 ----------------


def test_expired_trash_purged_lazily_with_count(env, db):
    """超过 30 天的回收站条目在下次访问时被惰性清理，并返回清理条数。"""
    proj = make_project(env, "proj-z")
    stale_dir = make_skill(proj / ".claude" / "skills", "stale", "stale", "过期条目")
    fresh_dir = make_skill(proj / ".claude" / "skills", "fresh", "fresh", "新鲜条目")
    skill_manager.delete_to_trash(db, str(stale_dir))
    skill_manager.delete_to_trash(db, str(fresh_dir))

    items = skill_manager.list_trash(db)["items"]
    stale_item = next(i for i in items if i["name"] == "stale")

    # 把 stale 的 trash_time 拨回 31 天前
    row = db.query(SkillTrash).filter(SkillTrash.id == stale_item["id"]).first()
    assert row is not None and row.trash_path
    stale_trash_path = pathlib.Path(row.trash_path)
    assert stale_trash_path.exists()
    row.trash_time = datetime.now() - timedelta(days=31)
    db.commit()

    listing = skill_manager.list_trash(db)
    assert listing["purged_expired"] == 1
    names = {i["name"] for i in listing["items"]}
    assert names == {"fresh"}
    # 过期条目的回收站目录已被删除，新鲜条目完好且剩余天数正确
    assert not stale_trash_path.exists()
    fresh = next(i for i in listing["items"] if i["name"] == "fresh")
    assert fresh["days_left"] >= 29


def test_permanent_delete_single_item(env, db):
    proj = make_project(env, "proj-purge")
    skill_dir = make_skill(proj / ".codex" / "skills", "gone", "gone", "将被彻底删除")
    skill_manager.delete_to_trash(db, str(skill_dir))
    item = skill_manager.list_trash(db)["items"][0]

    result = skill_manager.delete_permanent(db, item["id"])
    assert result["deleted_permanently"] is True
    assert not pathlib.Path(item["original_path"]).exists()
    assert skill_manager.list_trash(db)["items"] == []


# ---------------- 打开 / 预览 ----------------


def test_content_preview_parses_frontmatter_and_body(env):
    d = make_skill(env["claude"], "preview-me", "preview-me", "预览描述")
    content = skill_manager.read_content(str(d))
    assert content["name"] == "preview-me"
    assert content["description"] == "预览描述"
    assert content["frontmatter"]["name"] == "preview-me"
    assert "正文内容" in content["body"]

    with pytest.raises(ValueError, match="不在任何已知 skill 存放区"):
        skill_manager.read_content(str(env["projects_root"]))
