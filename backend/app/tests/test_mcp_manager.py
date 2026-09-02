"""MCP 管理业务层测试：发现聚合 / 跨端迁移 / 回收站往返 / 传输能力限制。

三端配置均为「配置文件内子结构」：claude.json 顶层 mcpServers、
config.toml 的 [mcp_servers.*]、cordis.patch.yml 的 dsh-mcp-client insert。
全部通过 tmp_path + monkeypatch 隔离路径，绝不触碰真实用户目录。
"""
import json
import pathlib
from datetime import datetime, timedelta

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.app import mcp_manager, schemas
from backend.app.api.v1 import mcp as mcp_api
from backend.app.database import Base
from backend.app.models import McpMigration, McpTrash


# ---------------- 基础设施 ----------------


@pytest.fixture()
def env(tmp_path, monkeypatch):
    """隔离四端配置文件、dsh patch、数据目录与项目根列表。"""
    ctx = {
        "data": tmp_path / "data",
        "claude_json": tmp_path / "claude.json",
        "codex_toml": tmp_path / "codex.toml",
        "dsh_patch": tmp_path / "cordis.patch.yml",
        "zcode_cli": tmp_path / "zcode-cli.json",
        "projects_root": tmp_path / "projects",
    }
    monkeypatch.setenv("A4API_DATA_DIR", str(ctx["data"]))
    monkeypatch.setenv("A4API_CLAUDE_MCP_PATH", str(ctx["claude_json"]))
    monkeypatch.setenv("A4API_CODEX_CONFIG_PATH", str(ctx["codex_toml"]))
    monkeypatch.setenv("A4API_DSH_MCP_PATCH_PATH", str(ctx["dsh_patch"]))
    monkeypatch.setenv("A4API_ZCODE_CLI_CONFIG_PATH", str(ctx["zcode_cli"]))
    # 项目根指向临时目录下的 projects_root（skill 的 project_roots 复用于 MCP）
    ctx["projects_root"].mkdir(parents=True)
    from backend.app import skill_manager

    skill_manager.save_project_roots([str(ctx["projects_root"])])
    return ctx


@pytest.fixture()
def db(env):
    engine = create_engine(f"sqlite:///{env['data'] / 'mcp_test.db'}")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()


def make_project(env, name: str):
    p = env["projects_root"] / name
    p.mkdir(parents=True, exist_ok=True)
    return p


def make_claude_global(env, name, command="npx", args=("-y", "server"), env_vars=None):
    """向 claude.json 写入一个 stdio server，返回文件路径。"""
    data = {"mcpServers": {name: {"type": "stdio", "command": command, "args": list(args)}}}
    if env_vars:
        data["mcpServers"][name]["env"] = dict(env_vars)
    env["claude_json"].write_text(json.dumps(data), encoding="utf-8")
    return env["claude_json"]


def make_zcode_global(env, name, entry):
    """向 zcode cli/config.json 的 mcp.servers 写入一个 server，保留其它顶层键。"""
    loaded = {}
    if env["zcode_cli"].exists():
        try:
            loaded = json.loads(env["zcode_cli"].read_text(encoding="utf-8-sig"))
        except (OSError, ValueError):
            loaded = {}
    loaded = loaded if isinstance(loaded, dict) else {}
    mcp = dict(loaded.get("mcp") or {})
    servers = dict(mcp.get("servers") or {})
    servers[name] = entry
    mcp["servers"] = servers
    loaded["mcp"] = mcp
    env["zcode_cli"].write_text(json.dumps(loaded, ensure_ascii=False), encoding="utf-8")
    return env["zcode_cli"]


def make_zcode_project(env, project, name, entry):
    """向 <项目>/.zcode/config.json 的 mcp.servers 写入一个 server。"""
    p = make_project(env, project)
    zc = p / ".zcode" / "config.json"
    zc.parent.mkdir(parents=True, exist_ok=True)
    data = {"mcp": {"servers": {name: entry}}}
    zc.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return zc


# ---------------- 发现 / 读取 ----------------

TEST_PATCH = """
# 手动保留条目（非 dsh-mcp-client，必须原样保留）
- insert:
    - id: dsh-hook
      name: "../../a4phone/dsh/lib/index.js"
"""


def make_dsh_patch(env, servers):
    """写入带 dsh-mcp-client 条目的 cordis.patch.yml；servers 为归一 dict 列表。"""
    import yaml

    entries = [
        {"insert": [mcp_manager.render_dsh(s) for s in servers]},
    ]
    # 保留一个非管理条目，验证重写不丢失
    raw = yaml.safe_load(TEST_PATCH)
    entries = raw + entries
    env["dsh_patch"].write_text(
        yaml.safe_dump(entries, allow_unicode=True, sort_keys=False), encoding="utf-8"
    )
    return env["dsh_patch"]


def make_codex_global(env, name, command="npx", args=("server",)):
    env["codex_toml"].write_text(
        f'[mcp_servers."{name}"]\ncommand = "{command}"\nargs = {json.dumps(args)}\n',
        encoding="utf-8",
    )
    return env["codex_toml"]


def test_discover_aggregates_across_tools_and_masks_env(env):
    """同名 server 跨端聚合标注端数；env 值在响应中脱敏。"""
    make_claude_global(env, "open-web", env_vars={"API_KEY": "secret-value"})
    make_dsh_patch(
        env,
        [
            {
                "name": "open-web",
                "transport": "stdio",
                "command": "node",
                "args": ["server.js"],
                "env": {"MODE": "stdio"},
                "url": None,
                "headers": {},
                "cwd": None,
            }
        ],
    )
    data = mcp_manager.discover()
    groups = {g["name"]: g for g in data["global"]}
    assert set(groups) == {"open-web"}
    g = groups["open-web"]
    assert g["end_count"] == 2
    assert g["duplicate"] is True
    assert g["ends"] == ["claude", "dsh"]
    # copies 中的 env 已脱敏
    for c in g["copies"]:
        assert all(v == mcp_manager.MASK for v in c["env"].values())
    assert "secret-value" not in json.dumps(data)


def test_discover_projects_only_include_ones_with_servers(env):
    """项目级：仅收录含 server 的项目；claude 读 .mcp.json，codex 读 .codex/config.toml。"""
    pa = make_project(env, "proj-a")
    pb = make_project(env, "proj-b")  # 无 server
    pa_mcp = pa / ".mcp.json"
    pa_mcp.write_text(json.dumps({"mcpServers": {"deploy": {"command": "npx", "args": ["d"]}}}), encoding="utf-8")
    (pa / ".codex").mkdir()
    (pa / ".codex" / "config.toml").write_text('[mcp_servers."deploy"]\ncommand = "x"\n', encoding="utf-8")

    data = mcp_manager.discover()
    projects = {p["project"]: p for p in data["projects"]}
    assert "proj-a" in projects
    assert "proj-b" not in projects
    groups = {g["name"]: g for g in projects["proj-a"]["servers"]}
    assert set(groups) == {"deploy"}
    assert groups["deploy"]["end_count"] == 2
    assert groups["deploy"]["ends"] == ["claude", "codex"]


def test_dsh_patch_preserves_non_managed_entries(env):
    """dsh patch 重写时保留非 dsh-mcp-client 条目（如 a4phone hook）。"""
    make_dsh_patch(env, [])
    servers = mcp_manager.read_dsh_servers(env["dsh_patch"])  # 初始空
    assert servers == []
    # 写回一个 server 后，手动条目仍在
    server = {
        "name": "web",
        "transport": "stdio",
        "command": "node",
        "args": ["index.js"],
        "env": {},
        "url": None,
        "headers": {},
        "cwd": None,
    }
    mcp_manager.write_servers("global", "dsh", None, [server])
    data = mcp_manager.discover()
    names = {g["name"] for g in data["global"]}
    assert "web" in names
    # 手动 hook 条目保留（dsh-mcp-client 只重写它自己的块）
    import yaml

    entries = yaml.safe_load(env["dsh_patch"].read_text(encoding="utf-8"))
    hooks = [e for e in entries if isinstance(e, dict) and any(
        isinstance(i, dict) and i.get("name", "").startswith("..") for i in (e.get("insert") or [])
    )]
    assert hooks, "手动条目被重写丢失"


# ---------------- zcode 端 ----------------

def test_discover_includes_zcode_global_and_project(env):
    """zcode 端：全局 mcp.servers 与项目级 .zcode/config.json 均被发现、聚合标注。"""
    make_zcode_global(env, "git-mcp", {"type": "stdio", "command": "npx", "args": ["-y", "@git/mcp"]})
    make_claude_global(env, "git-mcp", command="npx", args=("-y", "@git/mcp"))
    make_zcode_project(env, "proj-z", "deploy", {"command": "node", "args": ["d.js"]})

    data = mcp_manager.discover()
    # roots 含 zcode
    assert data["roots"]["zcode"] == str(env["zcode_cli"])
    assert "zcode" in data["capability"]
    assert data["capability"]["zcode"] == ["http", "sse", "stdio"]

    groups = {g["name"]: g for g in data["global"]}
    assert "git-mcp" in groups
    assert groups["git-mcp"]["end_count"] == 2
    assert groups["git-mcp"]["ends"] == ["claude", "zcode"]

    projects = {p["project"]: p for p in data["projects"]}
    assert "proj-z" in projects
    zg = projects["proj-z"]["servers"][0]
    assert zg["name"] == "deploy"
    assert zg["ends"] == ["zcode"]
    assert zg["copies"][0]["scope"] == "project"
    # 项目级 zcode 定位正确
    location = mcp_manager.mcp_config_file("project", "zcode", "proj-z")
    assert location == env["projects_root"] / "proj-z" / ".zcode" / "config.json"


def test_zcode_normalize_infers_type_and_keeps_whitelisted_keys(env):
    """type 省略推断（command→stdio / url→http）；enabled/timeoutMs 白名单保留。"""
    make_zcode_global(
        env,
        "mixed",
        {"command": "node", "args": ["s.js"], "enabled": True, "timeoutMs": 60000, "zzUnknown": "x"},
    )
    make_zcode_global(
        env,
        "remote",
        {"type": "http", "url": "http://localhost:3331/mcp", "headers": {"Authorization": "Bearer t"}},
    )
    servers = mcp_manager.read_servers("global", "zcode")
    by_name = {s["name"]: s for s in servers}
    assert by_name["mixed"]["transport"] == "stdio"  # 无 type + command → stdio
    assert by_name["mixed"]["extra"] == {"enabled": True, "timeoutMs": 60000}  # 未知键丢弃
    assert by_name["remote"]["transport"] == "http"
    assert by_name["remote"]["headers"] == {"Authorization": "Bearer t"}

    # 写回 round-trip：白名单键保留、未知键不出现
    mcp_manager.write_servers("global", "zcode", None, servers)
    raw = json.loads(env["zcode_cli"].read_text(encoding="utf-8"))
    written = raw["mcp"]["servers"]
    assert written["mixed"]["enabled"] is True
    assert written["mixed"]["timeoutMs"] == 60000
    assert "zzUnknown" not in written["mixed"]


def test_migrate_stdio_to_zcode_global_and_project_keeps_source(env, db):
    """stdio server 迁移到 zcode 全局 + 项目级，源端保留，mcp.servers 正确写入。"""
    make_claude_global(env, "git-mcp", env_vars={"GIT_TOKEN": "tok123"})
    make_project(env, "proj-z")

    result = mcp_manager.migrate(
        db,
        [{"scope": "global", "tool": "claude", "project": None, "name": "git-mcp"}],
        [
            {"scope": "global", "tool": "zcode", "project": None},
            {"scope": "project", "tool": "zcode", "project": "proj-z"},
        ],
    )
    assert result["migrated"] == 2, result
    assert result["failed"] == 0

    # 全局：写入 cli/config.json 的 mcp.servers，且其它顶层键（hooks）保留
    raw = json.loads(env["zcode_cli"].read_text(encoding="utf-8"))
    assert "git-mcp" in raw["mcp"]["servers"]
    # 项目级：写入 <proj>/.zcode/config.json
    proj_cfg = env["projects_root"] / "proj-z" / ".zcode" / "config.json"
    assert proj_cfg.exists()
    proj_raw = json.loads(proj_cfg.read_text(encoding="utf-8"))
    assert "git-mcp" in proj_raw["mcp"]["servers"]
    assert proj_raw["mcp"]["servers"]["git-mcp"]["env"] == {"GIT_TOKEN": "tok123"}
    # 源端保留
    assert {s["name"] for s in mcp_manager.read_servers("global", "claude")} == {"git-mcp"}
    logs = db.query(McpMigration).all()
    assert len(logs) == 2
    assert all(l.status == "success" for l in logs)
    assert {l.target_tool for l in logs} == {"zcode"}


def test_migrate_sse_and_http_to_zcode_supported(env, db):
    """sse / http 传输 zcode 均支持：从 claude 迁移到 zcode 成功。"""
    env["claude_json"].write_text(
        json.dumps({"mcpServers": {
            "a-sse": {"type": "sse", "url": "http://x:1/sse"},
            "b-http": {"type": "http", "url": "http://x:2/mcp"},
        }}),
        encoding="utf-8",
    )
    result = mcp_manager.migrate(
        db,
        [
            {"scope": "global", "tool": "claude", "project": None, "name": "a-sse"},
            {"scope": "global", "tool": "claude", "project": None, "name": "b-http"},
        ],
        [{"scope": "global", "tool": "zcode", "project": None}],
    )
    assert result["migrated"] == 2, result
    assert result["failed"] == 0
    raw = json.loads(env["zcode_cli"].read_text(encoding="utf-8"))
    servers = raw["mcp"]["servers"]
    assert servers["a-sse"]["type"] == "sse"
    assert servers["b-http"]["type"] == "http"
    assert servers["a-sse"]["url"] == "http://x:1/sse"


def test_mcp_schemas_accept_zcode_tool(env, db):
    """McpSourceIn / McpTargetIn / McpServerRefIn 的 tool 校验接受 zcode。"""
    make_zcode_global(env, "from-zc", {"command": "node", "args": ["z.js"]})
    body = schemas.McpMigrateIn(
        sources=[schemas.McpSourceIn(scope="global", tool="zcode", name="from-zc")],
        targets=[schemas.McpTargetIn(scope="global", tool="claude")],
    )
    result = mcp_api.migrate_mcp(body, db)
    assert result["migrated"] == 1
    assert {s["name"] for s in mcp_manager.read_servers("global", "claude")} == {"from-zc"}
    # McpServerRefIn
    ref = schemas.McpServerRefIn(scope="global", tool="zcode", name="from-zc")
    assert ref.tool == "zcode"


# ---------------- 迁移 ----------------

STDIO_SERVER = {
    "name": "git-mcp",
    "transport": "stdio",
    "command": "npx",
    "args": ["-y", "@git/mcp"],
    "env": {"GIT_TOKEN": "tok123"},
    "url": None,
    "headers": {},
    "cwd": None,
}


def test_migrate_stdio_to_all_three_keeps_source(env, db):
    """stdio server 可迁移到三端，源端保留，日志逐对落库。"""
    make_claude_global(env, "git-mcp", env_vars={"GIT_TOKEN": "tok123"})

    result = mcp_manager.migrate(
        db,
        [{"scope": "global", "tool": "claude", "project": None, "name": "git-mcp"}],
        [
            {"scope": "global", "tool": "codex", "project": None},
            {"scope": "global", "tool": "dsh", "project": None},
        ],
    )
    assert result["migrated"] == 2, result
    assert result["failed"] == 0
    # codex 端出现
    codex_servers = mcp_manager.read_codex_servers(env["codex_toml"])
    assert {s["name"] for s in codex_servers} == {"git-mcp"}
    # dsh 端出现
    dsh_servers = mcp_manager.read_dsh_servers(env["dsh_patch"])
    assert {s["name"] for s in dsh_servers} == {"git-mcp"}
    assert dsh_servers[0]["env"] == {"GIT_TOKEN": "tok123"}
    # 源端（claude）保留
    assert {s["name"] for s in mcp_manager.read_servers("global", "claude")} == {"git-mcp"}
    logs = db.query(McpMigration).all()
    assert len(logs) == 2
    assert all(l.status == "success" for l in logs)


def test_migrate_skips_identical_location(env, db):
    make_claude_global(env, "git-mcp")
    result = mcp_manager.migrate(
        db,
        [{"scope": "global", "tool": "claude", "project": None, "name": "git-mcp"}],
        [{"scope": "global", "tool": "claude", "project": None}],
    )
    assert result["skipped"] == 1
    assert result["migrated"] == 0


def test_migrate_sse_to_dsh_fails_with_reason(env, db):
    """sse 传输 dsh 不支持：整对失败并留日志，dsh 端不写入。"""
    env["claude_json"].write_text(
        json.dumps({"mcpServers": {"remote": {"type": "sse", "url": "http://localhost:3331/sse"}}}),
        encoding="utf-8",
    )
    result = mcp_manager.migrate(
        db,
        [{"scope": "global", "tool": "claude", "project": None, "name": "remote"}],
        [{"scope": "global", "tool": "dsh", "project": None}],
    )
    assert result["migrated"] == 0
    assert result["failed"] == 1
    assert "不支持 sse 传输" in result["results"][0]["detail"]
    assert mcp_manager.read_dsh_servers(env["dsh_patch"]) == []
    log = db.query(McpMigration).first()
    assert log.status == "failed"


def test_migrate_trashes_same_name_conflict_before_write(env, db):
    """目标端已有同名 server：先快照进回收站再写入新配置。"""
    make_claude_global(env, "deploy")
    # codex 端已有旧版 deploy
    make_codex_global(env, "deploy", command="old-server")
    # dsh 端已有旧版 deploy
    make_dsh_patch(
        env,
        [
            {
                "name": "deploy",
                "transport": "stdio",
                "command": "node",
                "args": ["old.js"],
                "env": {},
                "url": None,
                "headers": {},
                "cwd": None,
            }
        ],
    )
    result = mcp_manager.migrate(
        db,
        [{"scope": "global", "tool": "claude", "project": None, "name": "deploy"}],
        [
            {"scope": "global", "tool": "codex", "project": None},
            {"scope": "global", "tool": "dsh", "project": None},
        ],
    )
    assert result["conflicts_trashed"] == 2
    # 两个旧版进入回收站
    rows = db.query(McpTrash).all()
    assert len(rows) == 2
    assert {r.tool for r in rows} == {"codex", "dsh"}
    # 新内容已就位（Windows 上 npx 被归一为 npx.cmd）
    expected_cmd = "npx.cmd" if mcp_manager._portable_command("npx") == "npx.cmd" else "npx"
    codex_servers = mcp_manager.read_codex_servers(env["codex_toml"])
    assert codex_servers[0]["command"] == expected_cmd
    dsh_servers = mcp_manager.read_dsh_servers(env["dsh_patch"])
    assert dsh_servers[0]["command"] == expected_cmd
    # 回收站目录包含快照文件
    trashes = mcp_manager.trash_dir().glob("deploy.*.json")
    assert len(list(trashes)) == 2


def test_migrate_http_to_dsh_uses_streamable(env, db):
    """http 传输迁移到 dsh 时写回为 streamable-http。"""
    env["claude_json"].write_text(
        json.dumps({"mcpServers": {"srv": {"type": "http", "url": "http://x:1/mcp"}}}),
        encoding="utf-8",
    )
    # dsh 端不检查 url 类型能力外，验证写回字段
    result = mcp_manager.migrate(
        db,
        [{"scope": "global", "tool": "claude", "project": None, "name": "srv"}],
        [{"scope": "global", "tool": "dsh", "project": None}],
    )
    assert result["migrated"] == 1
    import yaml

    entries = yaml.safe_load(env["dsh_patch"].read_text(encoding="utf-8"))
    configs = [
        i["config"]
        for e in entries
        if isinstance(e, dict)
        for i in (e.get("insert") or [])
        if isinstance(i, dict) and i.get("name") == mcp_manager.DSH_MCP_CLIENT_PLUGIN
    ]
    assert configs[0]["transport"] == "streamable-http"
    assert configs[0]["url"] == "http://x:1/mcp"


def test_migrate_http_to_codex_fails(env, db):
    env["claude_json"].write_text(
        json.dumps({"mcpServers": {"srv": {"type": "http", "url": "http://x:1/mcp"}}}),
        encoding="utf-8",
    )
    result = mcp_manager.migrate(
        db,
        [{"scope": "global", "tool": "claude", "project": None, "name": "srv"}],
        [{"scope": "global", "tool": "codex", "project": None}],
    )
    assert result["failed"] == 1
    assert "不支持 http 传输" in result["results"][0]["detail"]


def test_migrate_unknown_source_fails_cleanly(env, db):
    with pytest.raises(ValueError, match="未找到 MCP server"):
        mcp_manager.migrate(
            db,
            [{"scope": "global", "tool": "claude", "project": None, "name": "nope"}],
            [{"scope": "global", "tool": "dsh", "project": None}],
        )
    assert db.query(McpMigration).count() == 0


def test_migrate_to_project_target_writes_project_files(env, db):
    """项目级迁移：claude 写 .mcp.json，codex 写 .codex/config.toml。"""
    make_claude_global(env, "deploy")
    make_project(env, "real-proj")
    result = mcp_manager.migrate(
        db,
        [{"scope": "global", "tool": "claude", "project": None, "name": "deploy"}],
        [{"scope": "project", "tool": "codex", "project": "real-proj"}],
    )
    assert result["migrated"] == 1
    proj = env["projects_root"] / "real-proj"
    assert (proj / ".codex" / "config.toml").exists()
    assert {s["name"] for s in mcp_manager.read_servers("project", "codex", "real-proj")} == {"deploy"}


def test_migrate_dsh_project_scope_rejected(env, db):
    make_claude_global(env, "deploy")
    make_project(env, "real-proj")
    with pytest.raises(ValueError, match="dsh 端不支持项目级"):
        mcp_manager.migrate(
            db,
            [{"scope": "global", "tool": "claude", "project": None, "name": "deploy"}],
            [{"scope": "project", "tool": "dsh", "project": "real-proj"}],
        )


def test_migrate_api_route_writes_log(env, db):
    """API 路由层直调：schema 校验 + 业务落库贯通。"""
    make_claude_global(env, "release")
    body = schemas.McpMigrateIn(
        sources=[schemas.McpSourceIn(scope="global", tool="claude", name="release")],
        targets=[schemas.McpTargetIn(scope="global", tool="dsh")],
    )
    result = mcp_api.migrate_mcp(body, db)
    assert result["migrated"] == 1
    logs = mcp_api.mcp_migration_logs(db)
    assert len(logs) == 1
    assert logs[0]["status"] == "success"
    assert "全局" in logs[0]["target"]


# ---------------- 删除 → 回收站 → 恢复 ----------------


def test_delete_restore_roundtrip_keeps_encrypted_env_secret(env, db):
    proj = make_project(env, "proj-x")
    path = proj / ".mcp.json"
    path.write_text(
        json.dumps({"mcpServers": {"note": {"type": "stdio", "command": "node", "args": ["s.js"], "env": {"TOKEN": "shh"}}}}),
        encoding="utf-8",
    )
    deleted = mcp_manager.delete_to_trash(
        db,
        {"scope": "project", "tool": "claude", "project": "proj-x", "name": "note"},
    )
    assert deleted["deleted"] is True
    # 文件里已无该 server
    assert mcp_manager.read_servers("project", "claude", "proj-x") == []
    # 快照文件里没有明文密钥
    row = db.query(McpTrash).filter(McpTrash.server_name == "note").first()
    assert row is not None
    snap = json.loads(pathlib.Path(row.trash_path).read_text(encoding="utf-8"))
    snap_text = json.dumps(snap)
    assert "shh" not in snap_text
    assert "TOKEN" in snap_text

    item_id = row.id
    restored = mcp_manager.restore_from_trash(db, item_id)
    assert restored["restored"] is True
    servers = mcp_manager.read_servers("project", "claude", "proj-x")
    assert servers[0]["name"] == "note"
    assert servers[0]["env"] == {"TOKEN": "shh"}  # 恢复时解密回明文
    assert mcp_manager.list_trash(db)["items"] == []


def test_restore_blocked_when_same_name_present(env, db):
    proj = make_project(env, "proj-y")
    path = proj / ".mcp.json"
    path.write_text(json.dumps({"mcpServers": {"guard": {"command": "node"}}}), encoding="utf-8")
    mcp_manager.delete_to_trash(db, {"scope": "project", "tool": "claude", "project": "proj-y", "name": "guard"})
    item_id = mcp_manager.list_trash(db)["items"][0]["id"]
    # 原位置出现同名 server
    path.write_text(json.dumps({"mcpServers": {"guard": {"command": "new"}}}), encoding="utf-8")
    with pytest.raises(ValueError, match="原位置已存在同名"):
        mcp_manager.restore_from_trash(db, item_id)


def test_expired_trash_purged_lazily(env, db):
    env["claude_json"].write_text(
        json.dumps({"mcpServers": {"stale": {"command": "a"}, "fresh": {"command": "b"}}}),
        encoding="utf-8",
    )
    mcp_manager.delete_to_trash(db, {"scope": "global", "tool": "claude", "name": "stale"})
    mcp_manager.delete_to_trash(db, {"scope": "global", "tool": "claude", "name": "fresh"})

    items = mcp_manager.list_trash(db)["items"]
    stale = next(i for i in items if i["name"] == "stale")
    row = db.query(McpTrash).filter(McpTrash.id == stale["id"]).first()
    stale_path = pathlib.Path(row.trash_path)
    row.trash_time = datetime.now() - timedelta(days=31)
    db.commit()

    listing = mcp_manager.list_trash(db)
    assert listing["purged_expired"] == 1
    names = {i["name"] for i in listing["items"]}
    assert names == {"fresh"}
    assert not stale_path.exists()


def test_permanent_delete_single_item(env, db):
    make_claude_global(env, "gone")
    mcp_manager.delete_to_trash(db, {"scope": "global", "tool": "claude", "name": "gone"})
    item = mcp_manager.list_trash(db)["items"][0]
    result = mcp_manager.delete_permanent(db, item["id"])
    assert result["deleted_permanently"] is True
    assert mcp_manager.list_trash(db)["items"] == []


# ---------------- 内容预览 / API 包装 ----------------


def test_server_content_masks_env(env):
    make_claude_global(env, "open-web", env_vars={"API_KEY": "secret-value"})
    content = mcp_manager.server_content("global", "claude", None, "open-web")
    assert content["env"] == {"API_KEY": mcp_manager.MASK}
    assert "secret-value" not in json.dumps(content)

    with pytest.raises(ValueError, match="未找到 MCP server"):
        mcp_manager.server_content("global", "claude", None, "ghost")


def test_api_delete_wraps_valueerror(env):
    with pytest.raises(HTTPException) as exc:
        mcp_api.delete_mcp_server(
            schemas.McpServerRefIn(scope="global", tool="claude", name="ghost"), None
        )
    assert exc.value.status_code == 400