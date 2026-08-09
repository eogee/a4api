"""自更新模块测试：签名、版本比较、清单校验、host 白名单、下载、状态。

不触网：网络相关用 monkeypatch 或本地 ThreadingHTTPServer。
签名用测试内临时生成的 Ed25519 密钥对，与真实发布密钥无关。
"""
import base64
import copy
import hashlib
import http.server
import json
import threading
from pathlib import Path

import pytest

from backend.app import updater
from backend.app.updater import (
    allowed_host,
    build_payload,
    compare,
    is_ignored,
    is_newer,
    is_too_old,
    parse_version,
    validate_manifest,
    verify_signature,
)

# golden：与 release.js 相同算法在固定输入下的输出，防跨实现回归
_GOLDEN_PAYLOAD_HEX = (
    "0000000c61346170692d7570646174650000000131000000013100000005302e"
    "322e3000000005302e302e3000000014323032362d30382d30395431303a3030"
    "3a30305a00000001300000000a74657374206e6f746573000000326874747073"
    "3a2f2f6769746875622e636f6d2f656f6765652f61346170692f72656c656173"
    "65732f7461672f76302e322e300000001561346170692d73657475702d302e32"
    "2e302e6578650000004061616161616161616161616161616161616161616161"
    "6161616161616161616161616161616161616161616161616161616161616161"
    "6161616161616161616100000004313233340000001561346170692d73657475"
    "702d302e322e302e657865000000406161616161616161616161616161616161"
    "6161616161616161616161616161616161616161616161616161616161616161"
    "6161616161616161616161616161610000000431323334"
)

_PAYLOAD_BYTES = b"hello a4api update " * 1024  # 约 19KB，本地下载测试用

_GITHUB_ASSET_URL = (
    "https://github.com/eogee/a4api/releases/download/v0.2.0/a4api-setup-0.2.0.exe"
)
_GITEE_ASSET_URL = (
    "https://gitee.com/eogee/a4api/releases/download/v0.2.0/a4api-setup-0.2.0.exe"
)


@pytest.fixture(autouse=True)
def _reset_state(tmp_path, monkeypatch):
    """隔离测试：独立数据目录 + 清空模块级缓存/下载状态。"""
    monkeypatch.setenv("A4API_DATA_DIR", str(tmp_path / "data"))
    updater._manifest_cache = None
    updater._download = {"status": "idle", "version": None, "downloaded": 0, "total": 0,
                         "path": None, "sha256_ok": False, "error": None}
    updater._dl_thread = None
    updater._cancel_event = None
    yield
    updater._manifest_cache = None


def make_skeleton():
    """未签名的合法清单骨架（含 GitHub+Gitee 两个镜像 asset）。"""
    return {
        "schema_version": "1",
        "version": "0.2.0",
        "min_version": "0.0.0",
        "prerelease": False,
        "published_at": "2026-08-09T10:00:00Z",
        "notes": "test notes",
        "notes_url": "https://github.com/eogee/a4api/releases/tag/v0.2.0",
        "assets": [
            {"name": "a4api-setup-0.2.0.exe", "size": 1234, "sha256": "a" * 64,
             "url": _GITHUB_ASSET_URL},
            {"name": "a4api-setup-0.2.0.exe", "size": 1234, "sha256": "a" * 64,
             "url": _GITEE_ASSET_URL},
        ],
    }


def make_signed(priv, **overrides):
    """基于骨架生成签名后的清单（用测试密钥对签名）。"""
    m = make_skeleton()
    m.update(overrides)
    m["signature"] = base64.b64encode(priv.sign(build_payload(m))).decode("ascii")
    return m


@pytest.fixture
def keys(monkeypatch):
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    priv = Ed25519PrivateKey.generate()
    pub_pem = priv.public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
    ).decode("ascii")
    monkeypatch.setattr(updater, "PUBLIC_KEY_PEM", pub_pem)
    return priv


# ---------- 签名载荷 ----------

def test_build_payload_golden():
    assert build_payload(make_skeleton()).hex() == _GOLDEN_PAYLOAD_HEX


def test_build_payload_url_not_signed():
    """URL 不在签名范围：换 URL 不改变载荷（内容由被签名的 sha256 绑死）。"""
    m = make_skeleton()
    base = build_payload(m)
    m2 = copy.deepcopy(m)
    m2["assets"][0]["url"] = "https://evil.example/x"
    m2["assets"][1]["url"] = "https://evil.example/y"
    assert build_payload(m2) == base


def test_build_payload_asset_order_independent():
    m = make_skeleton()
    m["assets"].reverse()
    assert build_payload(m) == build_payload(make_skeleton())


# ---------- 验签 ----------

def test_verify_signature_ok(keys):
    assert verify_signature(make_signed(keys)) is True


def test_verify_signature_rejects_tamper(keys):
    m = make_signed(keys)
    m["notes"] = "被篡改的说明"
    assert verify_signature(m) is False


def test_verify_signature_rejects_sha_tamper(keys):
    m = make_signed(keys)
    m["assets"][0]["sha256"] = "b" * 64
    assert verify_signature(m) is False


def test_verify_signature_accepts_url_tamper(keys):
    """URL 不在签名范围：换到白名单内另一镜像 URL、内容不变 → 验签仍通过。

    （换成白名单外域会被 validate_manifest 的 host 白名单直接拒绝——那层防护另测。）
    下载后仍以被签名的 sha256 兜底，换 URL 无法换安装包内容。
    """
    m = make_signed(keys)
    m["assets"][0]["url"] = "https://gitee.com/other/releases/download/v0.2.0/a4api-setup-0.2.0.exe"
    assert verify_signature(m) is True


def test_verify_signature_rejects_wrong_key(keys):
    """用另一个密钥签名 → 验签失败（防伪造清单）。"""
    m = make_signed(keys)
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    other = Ed25519PrivateKey.generate()
    m["signature"] = base64.b64encode(other.sign(build_payload(m))).decode("ascii")
    assert verify_signature(m) is False


# ---------- 清单字段校验 ----------

def test_validate_manifest_ok():
    assert validate_manifest(make_skeleton()) is True


def test_validate_manifest_rejects_bad_schema():
    m = make_skeleton()
    m["schema_version"] = "2"
    assert validate_manifest(m) is False


def test_validate_manifest_rejects_bad_version():
    m = make_skeleton()
    m["version"] = "v0.2.0"
    assert validate_manifest(m) is False


def test_validate_manifest_rejects_bad_sha():
    m = make_skeleton()
    m["assets"][0]["sha256"] = "xyz"
    assert validate_manifest(m) is False


def test_validate_manifest_rejects_bad_size():
    m = make_skeleton()
    m["assets"][0]["size"] = "1234"
    assert validate_manifest(m) is False


def test_validate_manifest_rejects_duplicate_name_url():
    m = make_skeleton()
    m["assets"].append(copy.deepcopy(m["assets"][0]))
    assert validate_manifest(m) is False


def test_validate_manifest_accepts_mirror_same_name():
    """同名不同 URL（GitHub/Gitee 镜像）合法。"""
    assert validate_manifest(make_skeleton()) is True


def test_validate_manifest_rejects_empty_assets():
    m = make_skeleton()
    m["assets"] = []
    assert validate_manifest(m) is False


def test_validate_manifest_rejects_foreign_url():
    m = make_skeleton()
    m["assets"][0]["url"] = "https://evil.example/x"
    assert validate_manifest(m) is False


# ---------- 版本比较 ----------

def test_parse_version():
    assert parse_version("0.2.0") == (0, 2, 0)
    assert parse_version("10.0.3") == (10, 0, 3)
    assert parse_version("v0.2.0") is None
    assert parse_version("0.2") is None
    assert parse_version("") is None


def test_compare():
    assert compare("0.2.0", "0.1.0") == 1
    assert compare("0.1.9", "0.1.10") == -1
    assert compare("1.0.0", "1.0.0") == 0
    assert compare("0.2.0", "bad") == 0  # 非法输入保守返回 0


def test_is_newer_and_too_old():
    assert is_newer("0.2.0", "0.1.0") is True
    assert is_newer("0.2.0", "0.2.0") is False
    assert is_newer("0.1.0", "0.2.0") is False
    assert is_too_old("0.1.0", "0.2.0") is True
    assert is_too_old("0.3.0", "0.2.0") is False


# ---------- host 白名单 ----------

def test_allowed_host():
    for ok in (
        "github.com", "gitee.com",
        "release-assets.githubusercontent.com", "objects.githubusercontent.com",
        "camo.githubusercontent.com", "sub.gitee.com",
    ):
        assert allowed_host(ok) is True
    for bad in ("localhost", "127.0.0.1", "evil.com", "github.com.evil.com",
                "10.0.0.1", ""):
        assert allowed_host(bad) is False


# ---------- 忽略版本 / 状态 ----------

def test_ignore_version(monkeypatch):
    assert is_ignored("0.2.0") is False
    updater.ignore_version("0.2.0")
    assert is_ignored("0.2.0") is True
    updater.ignore_version("0.2.0")  # 幂等
    assert is_ignored("0.3.0") is False


def test_state_write_read(tmp_path, monkeypatch):
    p = tmp_path / "update_state.json"
    monkeypatch.setattr(updater, "state_path", lambda: p)
    updater.write_state({"ignored": ["0.1.0"]})
    assert updater.read_state() == {"ignored": ["0.1.0"]}
    # 覆盖往返：再写一次读回
    updater.write_state({"ignored": ["0.1.0", "0.2.0"], "downloaded": {"version": "0.2.0", "path": "x"}})
    assert updater.read_state() == {"ignored": ["0.1.0", "0.2.0"],
                                    "downloaded": {"version": "0.2.0", "path": "x"}}


# ---------- fetch_manifest：GitHub→Gitee 回退 + TTL ----------

def test_fetch_manifest_github_fallback_gitee(monkeypatch, keys):
    m = make_signed(keys)
    calls = []

    def fake_fetch(url, max_bytes):
        calls.append(url)
        if "github.com" in url:
            raise Exception("github down")
        if url == updater.GITEE_API_LATEST_URL:
            return json.dumps({"tag_name": "v0.2.0"}).encode("utf-8")
        return json.dumps(m).encode("utf-8")

    monkeypatch.setattr(updater, "_fetch_url_retry", fake_fetch)
    got = updater.fetch_manifest()
    assert got["version"] == "0.2.0"
    assert any("gitee.com/api" in c for c in calls)
    assert any("releases/download" in c for c in calls)


def test_fetch_manifest_rejects_bad_signature(monkeypatch, keys):
    m = make_signed(keys)
    m["notes"] = "tampered"  # 改后签名失效
    monkeypatch.setattr(updater, "_fetch_url_retry",
                        lambda url, mx: json.dumps(m).encode("utf-8"))
    with pytest.raises(ValueError):
        updater.fetch_manifest()


def test_fetch_manifest_ttl_cache(monkeypatch, keys):
    m = make_signed(keys)
    calls = []

    def fake_fetch(url, max_bytes):
        calls.append(url)
        return json.dumps(m).encode("utf-8")

    monkeypatch.setattr(updater, "_fetch_url_retry", fake_fetch)
    updater.fetch_manifest()
    updater.fetch_manifest()
    assert len(calls) == 1  # 第二次命中缓存，不再触网


def test_fetch_manifest_all_down(monkeypatch, keys):
    def fake_fetch(url, max_bytes):
        raise Exception("all down")

    monkeypatch.setattr(updater, "_fetch_url_retry", fake_fetch)
    with pytest.raises(Exception):
        updater.fetch_manifest()


# ---------- 下载（本地服务器） ----------

class _FileHandler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/a4api-setup-0.2.0.exe":
            self.send_response(200)
            self.send_header("Content-Length", str(len(_PAYLOAD_BYTES)))
            self.end_headers()
            self.wfile.write(_PAYLOAD_BYTES)
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, *args):
        pass


@pytest.fixture
def local_server():
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _FileHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield server.server_address[1]
    server.shutdown()


def _local_manifest(port, keys, **overrides):
    sha = hashlib.sha256(_PAYLOAD_BYTES).hexdigest()
    m = make_signed(keys, assets=[
        {"name": "a4api-setup-0.2.0.exe", "size": len(_PAYLOAD_BYTES), "sha256": sha,
         "url": f"http://127.0.0.1:{port}/a4api-setup-0.2.0.exe"},
    ])
    m.update(overrides)
    m["signature"] = base64.b64encode(keys.sign(build_payload(m))).decode("ascii")
    return m


def test_download_success(monkeypatch, keys, local_server):
    sha = hashlib.sha256(_PAYLOAD_BYTES).hexdigest()
    m = _local_manifest(local_server, keys)
    monkeypatch.setattr(updater, "fetch_manifest", lambda: m)
    monkeypatch.setattr(updater, "allowed_host", lambda h: True)

    assert updater.start_download("0.2.0")["started"] is True
    updater._dl_thread.join(timeout=30)
    p = updater.progress()
    assert p["status"] == "done"
    assert p["sha256_ok"] is True
    assert Path(p["path"]).read_bytes() == _PAYLOAD_BYTES
    assert updater._sha256_of(Path(p["path"])) == sha
    # 已下载待安装状态已持久化
    assert updater.read_state()["downloaded"]["version"] == "0.2.0"


def test_download_sha_mismatch_fails(monkeypatch, keys, local_server):
    m = _local_manifest(local_server, keys)
    m["assets"][0]["sha256"] = "0" * 64  # 与实际文件不符
    m["signature"] = base64.b64encode(keys.sign(build_payload(m))).decode("ascii")
    monkeypatch.setattr(updater, "fetch_manifest", lambda: m)
    monkeypatch.setattr(updater, "allowed_host", lambda h: True)

    updater.start_download("0.2.0")
    updater._dl_thread.join(timeout=30)
    p = updater.progress()
    assert p["status"] == "failed"
    assert "sha256" in (p.get("error") or "").lower()


def test_download_url_fallback(monkeypatch, keys, local_server):
    """首个镜像地址不可达 → 自动回退到第二个地址。"""
    m = _local_manifest(local_server, keys)
    m["assets"] = [
        {"name": "a4api-setup-0.2.0.exe", "size": len(_PAYLOAD_BYTES),
         "sha256": m["assets"][0]["sha256"], "url": "http://127.0.0.1:9/a4api-setup-0.2.0.exe"},
        m["assets"][0],
    ]
    m["signature"] = base64.b64encode(keys.sign(build_payload(m))).decode("ascii")
    monkeypatch.setattr(updater, "fetch_manifest", lambda: m)
    monkeypatch.setattr(updater, "allowed_host", lambda h: True)

    updater.start_download("0.2.0")
    updater._dl_thread.join(timeout=30)
    assert updater.progress()["status"] == "done"


def test_download_file_cancel(tmp_path, local_server, monkeypatch):
    part = tmp_path / "a4api-setup-0.2.0.exe.part"
    cancel = threading.Event()
    cancel.set()  # 已取消 → 立即中断，不写数据
    monkeypatch.setattr(updater, "allowed_host", lambda h: True)
    with pytest.raises(InterruptedError):
        updater._download_file(
            f"http://127.0.0.1:{local_server}/a4api-setup-0.2.0.exe",
            part, hashlib.sha256(_PAYLOAD_BYTES).hexdigest(), len(_PAYLOAD_BYTES), cancel,
        )
    assert not part.exists() or part.stat().st_size == 0


def test_download_reuse_verified_file(monkeypatch, keys, local_server):
    sha = hashlib.sha256(_PAYLOAD_BYTES).hexdigest()
    m = _local_manifest(local_server, keys)
    monkeypatch.setattr(updater, "fetch_manifest", lambda: m)
    monkeypatch.setattr(updater, "allowed_host", lambda h: True)

    # 预置一个校验通过的已下载文件 → 直接复用，不再触网下载
    d = Path(updater.get_data_dir()) / "updates" / "0.2.0"
    d.mkdir(parents=True, exist_ok=True)
    (d / "a4api-setup-0.2.0.exe").write_bytes(_PAYLOAD_BYTES)

    updater.start_download("0.2.0")
    updater._dl_thread.join(timeout=30)
    assert updater.progress()["status"] == "done"
    assert updater._sha256_of(d / "a4api-setup-0.2.0.exe") == sha


# ---------- check() ----------

@pytest.fixture
def _fake_current(monkeypatch):
    """让 check() 认为当前运行版本固定为 0.1.0（不依赖 pyproject 实际版本）。"""
    monkeypatch.setattr(updater, "current_version", lambda: "0.1.0")


def test_check_update_available(monkeypatch, keys, _fake_current):
    monkeypatch.setattr(updater, "fetch_manifest", lambda: make_signed(keys))
    r = updater.check()
    assert r["status"] == "update_available"
    assert r["latest_version"] == "0.2.0"
    assert r["current_version"] == "0.1.0"


def test_check_up_to_date(monkeypatch, keys, _fake_current):
    m = make_signed(keys, version="0.1.0")
    monkeypatch.setattr(updater, "fetch_manifest", lambda: m)
    r = updater.check()
    assert r["status"] == "up_to_date"


def test_check_ignored(monkeypatch, keys, _fake_current):
    monkeypatch.setattr(updater, "fetch_manifest", lambda: make_signed(keys))
    updater.ignore_version("0.2.0")
    r = updater.check()
    assert r["status"] == "ignored"


def test_check_too_old(monkeypatch, keys, _fake_current):
    m = make_signed(keys, min_version="9.9.9")
    monkeypatch.setattr(updater, "fetch_manifest", lambda: m)
    r = updater.check()
    assert r["status"] == "too_old"


def test_check_prerelease_skipped_for_stable(monkeypatch, keys, _fake_current):
    m = make_signed(keys, prerelease=True)
    monkeypatch.setattr(updater, "fetch_manifest", lambda: m)
    r = updater.check()
    assert r["status"] == "up_to_date"


def test_numeric_core():
    assert updater._numeric_core("0.2.0-beta") == "0.2.0"
    assert updater._numeric_core("0.2.0") == "0.2.0"
    assert updater._numeric_core("v0.2.0") == "v0.2.0"  # 剥离失败原样返回
    assert updater._numeric_core("") == ""


def test_check_prerelease_current_sees_stable_update(monkeypatch, keys):
    """预发布当前版本（0.2.0-beta）也能看到后续稳定版更新（防死代码回归）。"""
    m = make_signed(keys, version="0.3.0")
    monkeypatch.setattr(updater, "fetch_manifest", lambda: m)
    monkeypatch.setattr(updater, "current_version", lambda: "0.2.0-beta")
    r = updater.check()
    assert r["status"] == "update_available"
    assert r["current_version"] == "0.2.0-beta"  # 展示仍用完整版本号


def test_check_prerelease_candidate_for_prerelease_current(monkeypatch, keys):
    """预发布当前版本看到预发布候选 → 提示（原 is_newer 分支已死代码）。"""
    m = make_signed(keys, version="0.3.0", prerelease=True)
    monkeypatch.setattr(updater, "fetch_manifest", lambda: m)
    monkeypatch.setattr(updater, "current_version", lambda: "0.2.0-beta")
    r = updater.check()
    assert r["status"] == "update_available"


def test_check_prerelease_current_no_upgrade_on_same_core(monkeypatch, keys):
    """预发布 0.2.0-beta 与稳定 0.2.0 同版本核心 → 不重复提示。"""
    m = make_signed(keys, version="0.2.0")
    monkeypatch.setattr(updater, "fetch_manifest", lambda: m)
    monkeypatch.setattr(updater, "current_version", lambda: "0.2.0-beta")
    r = updater.check()
    assert r["status"] == "up_to_date"


def test_fetch_manifest_network_outside_lock(monkeypatch, keys):
    """网络拉取期间 _lock 应可立即获取 → 不阻塞 progress/start_download 轮询。"""
    m = make_signed(keys)
    acquired_during_network = []

    def fake_fetch(url, max_bytes):
        # 网络 I/O 进行中：若 _lock 空闲说明 fetch 没持锁（修复前此处会超时失败）
        got = updater._lock.acquire(timeout=0.1)
        if got:
            updater._lock.release()
        acquired_during_network.append(got)
        return json.dumps(m).encode("utf-8")

    monkeypatch.setattr(updater, "_fetch_url_retry", fake_fetch)
    assert updater.fetch_manifest()["version"] == "0.2.0"
    assert acquired_during_network and all(acquired_during_network)


def test_check_pending_download_reprompts(monkeypatch, keys, _fake_current, local_server):
    """上次已下载未安装且仍有效 → 再次 check 直接提示应用，避免重复下载。"""
    m = _local_manifest(local_server, keys)
    monkeypatch.setattr(updater, "fetch_manifest", lambda: m)
    monkeypatch.setattr(updater, "allowed_host", lambda h: True)

    updater.start_download("0.2.0")
    updater._dl_thread.join(timeout=30)
    assert updater.progress()["status"] == "done"

    r = updater.check()
    assert r["status"] == "update_available"
    assert r["downloaded"] is True
    assert r["downloaded_version"] == "0.2.0"


def test_check_downloaded_marker_cleared_when_file_missing(monkeypatch, keys, _fake_current):
    """已下载标记指向的文件被删除 → 不再提示应用，清除残留标记。"""
    m = _local_manifest(9999, keys)  # 端口不可达也不重要，check 不走下载
    monkeypatch.setattr(updater, "fetch_manifest", lambda: m)
    updater.write_state({"downloaded": {"version": "0.2.0", "path": "C:/nonexistent/a4api-setup-0.2.0.exe"}})

    r = updater.check()
    assert r["status"] == "update_available"
    assert r.get("downloaded") is None
    assert "downloaded" not in updater.read_state()


def test_check_downstream_reporting(monkeypatch, keys, _fake_current):
    """update_available 结果带 notes/notes_url，前端可直接渲染。"""
    m = make_signed(keys, notes="修复若干问题", notes_url="https://github.com/eogee/a4api/releases/tag/v0.2.0")
    monkeypatch.setattr(updater, "fetch_manifest", lambda: m)
    r = updater.check()
    assert r["status"] == "update_available"
    assert r["notes"] == "修复若干问题"
    assert r["notes_url"].startswith("https://")


def test_check_error_on_fetch_fail(monkeypatch, keys):
    def boom():
        raise Exception("network down")

    monkeypatch.setattr(updater, "fetch_manifest", boom)
    r = updater.check()
    assert r["status"] == "error"


# ---------- apply（离线可更新 / 重启后可应用） ----------

def _mock_apply_side_effects(monkeypatch):
    """mock 停代理与 spawn，收集 spawn 的 argv，避免 apply 的真实副作用。"""
    spawned = []

    class FakePopen:
        def __init__(self, argv, **kw):
            spawned.append(argv)

    monkeypatch.setattr(updater.subprocess, "Popen", FakePopen)
    monkeypatch.setattr("backend.app.proxy_standalone.stop_proxy", lambda: None)
    return spawned


def _download_done(monkeypatch, keys, local_server):
    m = _local_manifest(local_server, keys)
    monkeypatch.setattr(updater, "fetch_manifest", lambda: m)
    monkeypatch.setattr(updater, "allowed_host", lambda h: True)
    updater.start_download("0.2.0")
    updater._dl_thread.join(timeout=30)
    assert updater.progress()["status"] == "done"
    return m


def test_apply_offline_uses_persisted_sha(monkeypatch, keys, local_server):
    """清单拉取失败（断网）也能应用：以持久化的 SHA256 复核。"""
    _download_done(monkeypatch, keys, local_server)
    updater._manifest_cache = None
    monkeypatch.setattr(
        updater, "fetch_manifest",
        lambda: (_ for _ in ()).throw(RuntimeError("offline")),
    )
    spawned = _mock_apply_side_effects(monkeypatch)

    r = updater.apply()
    assert r["applied"] is True
    assert any(str(a[-1]).endswith("a4api-setup-0.2.0.exe") for a in spawned)
    assert "downloaded" not in updater.read_state()  # 应用后清除标记


def test_apply_rejects_tampered_file_offline(monkeypatch, keys, local_server):
    """离线场景下，本地文件被篡改 → 按持久化 SHA256 拒绝，不启动安装器。"""
    _download_done(monkeypatch, keys, local_server)
    installer = Path(updater.progress()["path"])
    installer.write_bytes(b"tampered content")
    updater._manifest_cache = None
    monkeypatch.setattr(
        updater, "fetch_manifest",
        lambda: (_ for _ in ()).throw(RuntimeError("offline")),
    )
    spawned = _mock_apply_side_effects(monkeypatch)

    with pytest.raises(ValueError):
        updater.apply()
    assert not spawned


def test_apply_after_restart_uses_marker(monkeypatch, keys, local_server):
    """下载后重启（内存态清空）→ 从持久化标记恢复并离线应用。"""
    _download_done(monkeypatch, keys, local_server)
    real_path = Path(updater.progress()["path"])
    # 模拟重启：内存态清空，只剩持久化标记
    updater._download = {"status": "idle", "version": None, "downloaded": 0, "total": 0,
                         "path": None, "sha256_ok": False, "error": None}
    updater._manifest_cache = None
    monkeypatch.setattr(
        updater, "fetch_manifest",
        lambda: (_ for _ in ()).throw(RuntimeError("offline")),
    )
    spawned = _mock_apply_side_effects(monkeypatch)

    r = updater.apply()
    assert r["applied"] is True
    assert any(a[-1] == str(real_path) for a in spawned)
    assert "downloaded" not in updater.read_state()


def test_apply_without_download_raises(monkeypatch, keys, _fake_current):
    spawned = _mock_apply_side_effects(monkeypatch)
    with pytest.raises(ValueError):
        updater.apply()
    assert not spawned
