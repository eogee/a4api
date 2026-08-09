"""应用自更新：清单拉取/验签、安装包下载/校验、安装器应用。

安全性设计：
- 传输仅 HTTPS，重定向逐跳校验 host 白名单（防跳转钓鱼）。
- 更新清单 latest.json 由发布侧用 Ed25519 私钥签名，本模块内置公钥验签；
  任何字段校验或签名不通过，清单即作废，不向用户展示更新提示。
- 安装包边下边算 SHA256，与签名过的清单比对，通过才落盘；apply 前再次重校验。
- 版本比较防降级；预发布版本除非当前运行版本也是预发布，否则跳过。
- 下载落在运行时数据目录（%APPDATA%\\a4api\\updates\\），不信任系统临时目录。
"""
import base64
import hashlib
import json
import logging
import os
import re
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import HTTPRedirectHandler, Request, build_opener

from .database import get_data_dir
from .version import current_version

logger = logging.getLogger(__name__)

# ---- 配置常量 ----

# 发布侧签名密钥的公钥（生成方式见 .claude/skills/release/SKILL.md）：
#   openssl genpkey -algorithm ed25519 -out update-signing.pem
#   openssl pkey -in update-signing.pem -pubout -out update-signing.pub.pem
# 私钥保存在 .claude/keys/ 下，绝不入库；公钥是公开信息，随应用分发。
PUBLIC_KEY_PEM = """-----BEGIN PUBLIC KEY-----
MCowBQYDK2VwAyEAv4+TLC3OePq1OPnyOl1TtsY4T8MFDJab/fNNwfgS7rE=
-----END PUBLIC KEY-----"""

# 更新清单地址：GitHub「latest 别名」优先；GitHub 不可达时经 Gitee API 找最新 tag 回退。
GITHUB_MANIFEST_URL = "https://github.com/eogee/a4api/releases/latest/download/latest.json"
GITEE_API_LATEST_URL = "https://gitee.com/api/v5/repos/eogee/a4api/releases/latest"

MANIFEST_TTL = 600  # 清单缓存秒数
MANIFEST_MAX_BYTES = 512 * 1024
MAX_DOWNLOAD_SIZE = 300 * 1024 * 1024
_HTTP_TIMEOUT = 30

_ALLOWED_HOSTS = {
    "github.com",
    "gitee.com",
    "release-assets.githubusercontent.com",
    "objects.githubusercontent.com",
}

# 签名载荷协议常量（与 release.js 严格一致，两端必须输出相同字节）
_NAMESPACE = "a4api-update"
_PAYLOAD_VERSION = "1"
_SCHEMA_VERSION = "1"
_INSTALLER_PREFIX = "a4api-setup-"

_VERSION_RE = re.compile(r"^\d+\.\d+\.\d+$")
_SHA256_RE = re.compile(r"^[a-fA-F0-9]{64}$")
_MAX_ASSETS = 4

# ---- 运行状态（下载线程与请求线程共享，锁保护） ----
_lock = threading.Lock()
# 清单拉取单飞锁：网络 I/O 期间只持这把锁，不占用 _lock（避免阻塞进度轮询）
_fetch_lock = threading.Lock()
_manifest_cache: dict | None = None  # {"data": dict, "fetched_at": float}
_download: dict = {"status": "idle", "version": None, "downloaded": 0, "total": 0,
                   "path": None, "sha256_ok": False, "error": None}
_dl_thread: threading.Thread | None = None
_cancel_event: threading.Event | None = None


# ---------- 版本比较 ----------

def parse_version(v: str):
    """解析 x.y.z 为 (主, 次, 修订) 元组；非法格式返回 None。"""
    if not _VERSION_RE.match(v or ""):
        return None
    return tuple(int(p) for p in v.split("."))


def compare(a: str, b: str) -> int:
    """a > b 返回 1，a == b 返回 0，a < b 返回 -1；任一非法格式返回 0。"""
    pa, pb = parse_version(a), parse_version(b)
    if pa is None or pb is None:
        return 0
    return (pa > pb) - (pa < pb)


def is_newer(candidate: str, current: str) -> bool:
    return compare(candidate, current) > 0


def is_too_old(current: str, min_version: str) -> bool:
    """当前版本低于清单 min_version 时返回 True（该更新需完整安装包，不可直接应用）。"""
    return compare(current, min_version) < 0


def _numeric_core(v: str) -> str:
    """取版本号数字核心用于比较：'0.2.0-beta' → '0.2.0'；无法剥离时原样返回。

    parse_version 只接受严格 x.y.z，预发布当前版本（0.2.0-beta）会解析失败、
    比较恒为 0 → 永远判"无更新"。比较前先剥离非数字后缀，预发布构建才能看到后续更新。
    """
    m = re.match(r"^(\d+\.\d+\.\d+)", v or "")
    return m.group(1) if m else v


# ---------- 签名载荷与清单校验 ----------

def build_payload(manifest: dict) -> bytes:
    """构造签名载荷：固定字段顺序 + 4 字节大端长度前缀，消除 JSON 序列化歧义。

    URL 不在签名范围——两份 latest.json（GitHub/Gitee）因此字节一致、可共用同一份签名；
    URL 指向的内容由被签名的 sha256 绑死，替换 URL 无法替换安装包内容。
    """
    assets = manifest.get("assets") or []

    def push(buf: bytearray, s: str) -> None:
        data = str(s).encode("utf-8")
        buf.extend(len(data).to_bytes(4, "big"))
        buf.extend(data)

    buf = bytearray()
    push(buf, _NAMESPACE)
    push(buf, _PAYLOAD_VERSION)
    push(buf, manifest["schema_version"])
    push(buf, manifest["version"])
    push(buf, manifest.get("min_version", "0.0.0"))
    push(buf, manifest.get("published_at", ""))
    push(buf, "1" if manifest.get("prerelease") else "0")
    push(buf, manifest.get("notes", ""))
    push(buf, manifest.get("notes_url", ""))
    for a in sorted(assets, key=lambda x: str(x["name"])):
        push(buf, a["name"])
        push(buf, str(a["sha256"]).lower())
        push(buf, str(a["size"]))
    return bytes(buf)


def allowed_host(host: str) -> bool:
    """下载/清单主机白名单（后缀匹配，覆盖 CDN 子域）。"""
    host = (host or "").lower()
    if not host:
        return False
    if host in _ALLOWED_HOSTS:
        return True
    return host.endswith(".githubusercontent.com") or host.endswith(".gitee.com")


def validate_manifest(manifest: dict) -> bool:
    """严格校验清单字段类型与取值。不合法一律返回 False（视为签名无效）。"""
    try:
        if str(manifest.get("schema_version")) != _SCHEMA_VERSION:
            return False
        if "version" not in manifest or not _VERSION_RE.match(str(manifest["version"])):
            return False
        if not _VERSION_RE.match(str(manifest.get("min_version", "0.0.0"))):
            return False
        if not isinstance(manifest.get("prerelease", False), bool):
            return False

        assets = manifest.get("assets")
        if not isinstance(assets, list) or not assets:
            return False
        if len(assets) > _MAX_ASSETS:
            return False
        seen: set = set()
        for a in assets:
            if not isinstance(a, dict):
                return False
            name = a.get("name")
            if not isinstance(name, str) or not name:
                return False
            url = a.get("url")
            if not isinstance(url, str) or not allowed_host(_host_of(url)):
                return False
            key = (name, url)
            if key in seen:  # 拒绝「同名同 URL」的重复资产；同名不同镜像允许
                return False
            seen.add(key)
            sha = a.get("sha256")
            if not isinstance(sha, str) or not _SHA256_RE.match(sha.strip()):
                return False
            size = a.get("size")
            if not isinstance(size, int) or size <= 0 or size > MAX_DOWNLOAD_SIZE:
                return False
        return True
    except Exception:
        return False


def verify_signature(manifest: dict) -> bool:
    """Ed25519 验签：先字段严格校验，再重建签名载荷比对。失败即拒。"""
    if not validate_manifest(manifest):
        return False
    sig_b64 = manifest.get("signature")
    if not isinstance(sig_b64, str) or not sig_b64:
        return False
    try:
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

        signature = base64.b64decode(sig_b64, validate=True)
        pub = serialization.load_pem_public_key(PUBLIC_KEY_PEM.encode("ascii"))
        if not isinstance(pub, Ed25519PublicKey):
            return False
        pub.verify(signature, build_payload(manifest))
        return True
    except Exception as e:
        logger.warning("更新清单验签失败：%s", e)
        return False


# ---------- 状态持久化（忽略版本 / 已下载待安装） ----------

def state_path() -> Path:
    return get_data_dir() / "update_state.json"


def read_state() -> dict:
    try:
        data = json.loads(state_path().read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def write_state(state: dict) -> None:
    """原子写状态文件，避免中途崩溃损坏。"""
    path = state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".update_state.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    finally:
        try:
            os.unlink(tmp)
        except OSError:
            pass


def is_ignored(version: str) -> bool:
    return version in read_state().get("ignored", [])


def ignore_version(version: str) -> None:
    state = read_state()
    ignored = state.get("ignored", [])
    if version not in ignored:
        ignored.append(version)
        state["ignored"] = ignored
        write_state(state)


def _mark_downloaded(version: str, path: Path, sha256: str = "", size: int = 0) -> None:
    """持久化「已下载待安装」标记，含校验值（apply 离线时仍可复核）。"""
    state = read_state()
    entry = {"version": version, "path": str(path)}
    if sha256:
        entry["sha256"] = sha256
    if size:
        entry["size"] = int(size)
    state["downloaded"] = entry
    write_state(state)


def _clear_downloaded_marker() -> None:
    state = read_state()
    if "downloaded" in state:
        state.pop("downloaded", None)
        write_state(state)


# ---------- 网络拉取（含逐跳 host 白名单） ----------

def _host_of(url: str) -> str:
    return (urlparse(url or "").netloc or "").split(":")[0].lower()


class _HostCheckRedirectHandler(HTTPRedirectHandler):
    """在每一跳重定向前校验目标 host，拦截跳转到非白名单主机。"""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        host = _host_of(newurl)
        if not allowed_host(host):
            raise URLError(f"redirect blocked: {host}")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _http_get(url: str, max_bytes: int) -> bytes:
    """HTTPS GET + 逐跳 host 白名单 + 最终 URL 复检 + 大小上限。"""
    opener = build_opener(_HostCheckRedirectHandler())
    req = Request(url, headers={"User-Agent": "a4api-updater/1.0"})
    with opener.open(req, timeout=_HTTP_TIMEOUT) as resp:
        if not allowed_host(_host_of(resp.geturl())):
            raise URLError(f"blocked host: {_host_of(resp.geturl())}")
        total = 0
        chunks = []
        while True:
            chunk = resp.read(64 * 1024)
            if not chunk:
                break
            total += len(chunk)
            if total > max_bytes:
                raise URLError("response too large")
            chunks.append(chunk)
    return b"".join(chunks)


def _fetch_url_retry(url: str, max_bytes: int) -> bytes:
    last: Exception | None = None
    for _ in range(2):
        try:
            return _http_get(url, max_bytes)
        except (HTTPError, URLError, OSError, ValueError) as e:
            last = e
            logger.warning("拉取失败 %s：%s", url, e)
            time.sleep(1)
    if last is not None:
        raise last
    raise URLError(url)


def _gitee_latest_manifest_url() -> str:
    """Gitee 无 latest 别名，用公开 API 取最新 release 的 tag 再拼清单地址。"""
    data = json.loads(_fetch_url_retry(GITEE_API_LATEST_URL, MANIFEST_MAX_BYTES).decode("utf-8"))
    tag = data.get("tag_name", "")
    if not tag:
        raise URLError("gitee latest release has no tag")
    return f"https://gitee.com/eogee/a4api/releases/download/{tag}/latest.json"


def _fetch_from_remote() -> dict:
    """拉取清单原始 JSON：GitHub 优先，不可达时回退 Gitee。网络 I/O，锁外调用。"""
    try:
        return json.loads(_fetch_url_retry(GITHUB_MANIFEST_URL, MANIFEST_MAX_BYTES).decode("utf-8"))
    except Exception:
        try:
            url = _gitee_latest_manifest_url()
            return json.loads(_fetch_url_retry(url, MANIFEST_MAX_BYTES).decode("utf-8"))
        except Exception as e:
            logger.warning("更新清单拉取失败（GitHub 与 Gitee 均不可达）：%s", e)
            raise


def fetch_manifest() -> dict:
    """拉取并缓存更新清单，返回已通过验签的清单；失败抛异常。

    GitHub 优先，GitHub 不可达时回退 Gitee。
    网络 I/O 在 _fetch_lock 内、_lock 外执行：单飞（同一时刻只拉一次），
    且不阻塞 progress / start_download / apply 等需要 _lock 的请求。
    """
    global _manifest_cache
    # 快速路径：缓存未过期直接返回（只取 _lock，不碰网络）
    with _lock:
        cached = _manifest_cache
        if cached and time.time() - cached["fetched_at"] < MANIFEST_TTL:
            return cached["data"]

    with _fetch_lock:  # 单飞：并发调用只有一个真正拉取，其余等待后复用结果
        with _lock:  # 双检：等 _fetch_lock 期间其它线程可能已填充缓存
            cached = _manifest_cache
            if cached and time.time() - cached["fetched_at"] < MANIFEST_TTL:
                return cached["data"]
        data = _fetch_from_remote()
        if not verify_signature(data):
            raise ValueError("manifest signature invalid")
        with _lock:
            _manifest_cache = {"data": data, "fetched_at": time.time()}
        return data


# ---------- 更新检查 ----------

def _installer_name(version: str) -> str:
    return f"{_INSTALLER_PREFIX}{version}.exe"


def _asset_for_version(manifest: dict, version: str) -> dict:
    name = _installer_name(version)
    for a in manifest.get("assets", []):
        if a.get("name") == name:
            return a
    raise ValueError(f"更新清单中找不到版本 {version} 的安装包")


def _urls_for_version(manifest: dict, version: str) -> list[str]:
    name = _installer_name(version)
    return [a["url"] for a in manifest.get("assets", []) if a.get("name") == name]


def _cleanup_applied_downloads(current: str) -> None:
    """当前版本已 ≥ 已下载版本时，清理该下载目录与状态（防残留占空间）。"""
    state = read_state()
    dl = state.get("downloaded")
    if not isinstance(dl, dict) or not dl.get("version"):
        return
    version = dl["version"]
    if parse_version(version) is None or compare(version, current) > 0:
        return
    try:
        d = get_data_dir() / "updates" / version
        for p in d.glob("*"):
            p.unlink(missing_ok=True)
        d.rmdir()
    except OSError:
        pass
    state.pop("downloaded", None)
    write_state(state)


def _pending_verified_download(manifest: dict) -> dict | None:
    """返回「已下载且仍校验通过」的安装包信息；无效则清理状态。

    校验优先用持久化的 SHA256（下载时已与签名清单比对），离线也能判定；
    持久化标记缺失（旧版本留下的）时回退用签名清单核对。
    """
    state = read_state()
    dl = state.get("downloaded")
    if not isinstance(dl, dict) or not dl.get("path") or not dl.get("version"):
        return None
    path = Path(dl["path"])
    version = dl["version"]
    if not path.is_file():
        _clear_downloaded_marker()
        return None
    try:
        if dl.get("sha256"):
            valid = _sha256_of(path).lower() == str(dl["sha256"]).lower()
            if valid and dl.get("size"):
                valid = path.stat().st_size == int(dl["size"])
        else:
            asset = _asset_for_version(manifest, version)
            valid = (_sha256_of(path).lower() == asset["sha256"].lower()
                     and path.stat().st_size == int(asset["size"]))
        if valid:
            return {"version": version, "path": str(path)}
    except Exception:
        pass
    _clear_downloaded_marker()
    return None


def check(force: bool = False) -> dict:
    """检查是否有可用更新，返回给前端的状态对象。"""
    global _manifest_cache
    current = current_version()
    # 当前版本可能是预发布（如 0.2.0-beta）：比较用数字核心，展示仍用完整版本号。
    # 否则 parse_version('0.2.0-beta') 失败 → compare 恒 0 → 永远"无更新"（含稳定版）。
    cmp_current = _numeric_core(current)
    if force:
        with _lock:
            _manifest_cache = None
    try:
        manifest = fetch_manifest()
    except Exception as e:
        return {"status": "error", "current_version": current, "error": str(e)}

    _cleanup_applied_downloads(cmp_current)

    candidate = manifest.get("version", "")
    prerelease = bool(manifest.get("prerelease"))
    # 预发布版本：仅当当前运行版本本身带非数字标记时才提示
    current_is_prerelease = not bool(_VERSION_RE.match(current))

    result = {
        "status": "error",
        "current_version": current,
        "latest_version": candidate,
        "notes": manifest.get("notes", ""),
        "notes_url": manifest.get("notes_url", ""),
        "prerelease": prerelease,
    }

    if not is_newer(candidate, cmp_current):
        result["status"] = "up_to_date"
        return result
    if is_too_old(cmp_current, str(manifest.get("min_version", "0.0.0"))):
        result["status"] = "too_old"
        result["error"] = f"当前版本过旧，请直接下载完整安装包更新到 {candidate}"
        return result
    if prerelease and not current_is_prerelease:
        result["status"] = "up_to_date"
        return result
    if is_ignored(candidate):
        result["status"] = "ignored"
        return result

    result["status"] = "update_available"
    # 上次已下载未安装且仍有效 → 直接提示应用，避免重复下载
    pending = _pending_verified_download(manifest)
    if pending and pending["version"] == candidate:
        result["downloaded"] = True
        result["downloaded_version"] = candidate
    else:
        _clear_downloaded_marker()
    return result


# ---------- 下载 ----------

def _sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def _set_download_progress(received: int) -> None:
    with _lock:
        if _download.get("status") == "downloading":
            _download["downloaded"] = received


def _download_file(url: str, dest: Path, expected_sha256: str, expected_size: int,
                   cancel: threading.Event) -> None:
    """下载单个 URL 到 dest，边下边算 SHA256；尺寸/哈希不符抛异常，不留 .part。"""
    opener = build_opener(_HostCheckRedirectHandler())
    req = Request(url, headers={"User-Agent": "a4api-updater/1.0"})
    with opener.open(req, timeout=_HTTP_TIMEOUT) as resp:
        if not allowed_host(_host_of(resp.geturl())):
            raise URLError(f"blocked host: {_host_of(resp.geturl())}")
        hasher = hashlib.sha256()
        received = 0
        with open(dest, "wb") as f:
            while True:
                if cancel.is_set():
                    raise InterruptedError("cancelled")
                chunk = resp.read(64 * 1024)
                if not chunk:
                    break
                hasher.update(chunk)
                received += len(chunk)
                if received > MAX_DOWNLOAD_SIZE:
                    raise URLError("download too large")
                f.write(chunk)
                _set_download_progress(received)
    if received != expected_size:
        raise ValueError(f"size mismatch: expected {expected_size}, got {received}")
    if hasher.hexdigest() != expected_sha256.lower():
        raise ValueError("sha256 mismatch")


def _run_download(version: str) -> None:
    """下载线程主体：GitHub 源失败自动回退 Gitee 源；校验通过才落盘。"""
    try:
        manifest = fetch_manifest()
        asset = _asset_for_version(manifest, version)
        urls = _urls_for_version(manifest, version)
        expected_sha = asset["sha256"].lower()
        expected_size = int(asset["size"])

        update_dir = get_data_dir() / "updates" / version
        update_dir.mkdir(parents=True, exist_ok=True)
        final_path = update_dir / asset["name"]
        part_path = update_dir / (asset["name"] + ".part")

        # 已存在且校验通过 → 直接复用
        if final_path.is_file():
            if _sha256_of(final_path) == expected_sha and final_path.stat().st_size == expected_size:
                with _lock:
                    _download.update(status="done", version=version, path=str(final_path),
                                     downloaded=expected_size, total=expected_size, sha256_ok=True,
                                     error=None)
                _mark_downloaded(version, final_path, expected_sha, expected_size)
                return
            final_path.unlink(missing_ok=True)

        last_err: Exception | None = None
        for url in urls:
            part_path.unlink(missing_ok=True)
            try:
                with _lock:
                    _download.update(status="downloading", version=version, url=url,
                                     downloaded=0, total=expected_size, path=None,
                                     sha256_ok=False, error=None)
                _download_file(url, part_path, expected_sha, expected_size, _cancel_event)
                os.replace(part_path, final_path)
                with _lock:
                    _download.update(status="done", version=version, path=str(final_path),
                                     downloaded=expected_size, total=expected_size, sha256_ok=True,
                                     error=None)
                _mark_downloaded(version, final_path, expected_sha, expected_size)
                return
            except InterruptedError:
                part_path.unlink(missing_ok=True)
                with _lock:
                    _download.update(status="cancelled", error="已取消下载", path=None)
                return
            except Exception as e:
                last_err = e
                logger.warning("下载 %s 失败：%s", url, e)
        part_path.unlink(missing_ok=True)
        with _lock:
            _download.update(status="failed", path=None,
                             error=str(last_err or "下载失败"))
    except Exception as e:
        logger.error("更新下载失败：%s", e)
        with _lock:
            _download.update(status="failed", path=None, error=str(e))


def start_download(version: str) -> dict:
    """启动下载线程。同版本进行中复用进度；不同版本冲突返回错误。"""
    global _dl_thread, _download, _cancel_event
    with _lock:
        status = _download.get("status")
        cur = _download.get("version")
        if status in ("downloading", "queued") and cur == version:
            return {"started": False, "already_running": True}
        if status in ("downloading", "queued") and cur != version:
            return {"started": False, "error": "已有下载任务进行中"}
        _cancel_event = threading.Event()
        _download = {"status": "queued", "version": version, "url": None,
                     "downloaded": 0, "total": 0, "path": None,
                     "sha256_ok": False, "error": None}
        _dl_thread = threading.Thread(target=_run_download, args=(version,), daemon=True)
        _dl_thread.start()
    return {"started": True}


def progress() -> dict:
    with _lock:
        return dict(_download)


def cancel_download() -> dict:
    with _lock:
        if _cancel_event is not None:
            _cancel_event.set()
    return {"cancelled": True}


# ---------- 应用更新 ----------

def apply() -> dict:
    """应用更新：重校验磁盘安装包 → 停后台代理 → spawn 自身副本启动安装器。

    校验以「下载时已与签名清单比对并持久化的 SHA256」为准，离线也能应用；
    若此时能拉到更新清单再做一次交叉核对（可选增强，拉不到不阻断）。
    安装包定位：优先内存态（刚下载完成），重启后回退到持久化的 downloaded 标记。

    调用方（update 路由的 BackgroundTasks）在响应 flush 后执行 os._exit(0)，
    让 GUI 进程退出并释放 AppMutex，安装器才可干净覆盖。
    """
    with _lock:
        dl = dict(_download)
    state = read_state()
    marker = state.get("downloaded")

    # 定位安装包：内存态 > 持久化标记（覆盖"下载后重启再点立即更新"的场景）
    installer_path = dl.get("path") if dl.get("status") == "done" else None
    version = dl.get("version") if installer_path else None
    expected_sha = expected_size = None
    if isinstance(marker, dict) and marker.get("path"):
        installer_path = installer_path or marker.get("path")
        version = version or marker.get("version")
        expected_sha = marker.get("sha256")
        expected_size = marker.get("size")
    if not installer_path or not version:
        raise ValueError("没有已下载并校验通过的安装包，请先下载更新")
    installer = Path(installer_path)
    if not installer.is_file():
        raise ValueError("安装包文件不存在，请重新下载")

    # 1) 本地复核：以持久化校验值为准（下载时已与签名清单比对，离线可信）
    if expected_sha and _sha256_of(installer).lower() != str(expected_sha).lower():
        raise ValueError("安装包校验失败，请重新下载")
    if expected_size and installer.stat().st_size != int(expected_size):
        raise ValueError("安装包大小不符，请重新下载")

    # 2) 可选交叉核对：能拉到签名清单就再核一次；拉不到不阻断（离线可更新）
    try:
        manifest = fetch_manifest()
        asset = _asset_for_version(manifest, version)
        if _sha256_of(installer) != asset["sha256"].lower():
            raise ValueError("安装包校验失败，请重新下载")
        if installer.stat().st_size != int(asset["size"]):
            raise ValueError("安装包大小不符，请重新下载")
    except ValueError:
        raise
    except Exception as e:
        logger.warning("应用更新时拉取清单失败，按已持久化的校验值继续：%s", e)

    # 停后台翻译代理，避免其持有 _internal 的 DLL 句柄阻塞覆盖安装
    from .proxy_standalone import stop_proxy

    stop_proxy()

    if getattr(sys, "frozen", False):
        argv = [sys.executable, "--apply-update", str(installer)]
    else:
        root = Path(__file__).resolve().parent.parent.parent
        argv = [sys.executable, str(root / "desktop.py"), "--apply-update", str(installer)]

    creationflags = 0
    if os.name == "nt":
        creationflags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
    subprocess.Popen(argv, creationflags=creationflags, close_fds=True)
    _clear_downloaded_marker()
    logger.info("已启动更新安装器：%s", installer.name)
    return {"applied": True}
