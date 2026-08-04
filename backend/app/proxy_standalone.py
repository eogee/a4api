"""独立运行的 OpenAI 翻译代理进程。

工具在切换 OpenAI 类型服务商时启动本进程（开发：python -m backend.app.proxy_standalone；
打包：a4api.exe --proxy）。应用退出后代理仍然存活，Claude Code 可继续使用。
代理轮询数据库：当前生效配置不再是 openai 类型时自动退出。
"""

import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

POLL_INTERVAL = 3.0


def _active_openai_config():
    from .database import SessionLocal
    from .config_manager import target_list
    from .models import Configuration

    db = SessionLocal()
    try:
        c = db.query(Configuration).filter(Configuration.is_active.is_(True)).first()
        if c is None or c.provider is None or c.provider.api_type != "openai":
            return None
        if "claude" not in target_list(c.targets):
            return None  # 仅 Codex 目标的方案不需要翻译代理
        return c
    finally:
        db.close()


def _status_file():
    from .database import get_data_dir

    return get_data_dir() / "proxy.json"


def _port_alive(port) -> bool:
    if not port:
        return False
    try:
        with socket.create_connection(("127.0.0.1", int(port)), timeout=1):
            return True
    except OSError:
        return False


def _port_owner_pid(port):
    """按监听端口反查占用进程 PID（状态文件 pid 可能过期时兜底）。"""
    if not port:
        return None
    try:
        out = subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-NonInteractive",
                "-Command",
                (
                    f"(Get-NetTCPConnection -LocalPort {int(port)} -State Listen "
                    "-ErrorAction SilentlyContinue | "
                    "Select-Object -First 1 -ExpandProperty OwningProcess)"
                ),
            ],
            capture_output=True,
            text=True,
            timeout=10,
        ).stdout.strip()
        return int(out) if out.isdigit() else None
    except Exception:
        return None


def _spawn() -> None:
    """以独立进程方式启动代理（应用退出后仍然存活）。"""
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    if getattr(sys, "frozen", False):
        cmd = [sys.executable, "--proxy"]
        cwd = None
    else:
        root = Path(__file__).resolve().parents[2]
        cmd = [sys.executable, "-m", "backend.app.proxy_standalone"]
        cwd = str(root)
    subprocess.Popen(
        cmd,
        cwd=cwd,
        creationflags=flags,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def ensure_proxy_running() -> dict:
    """确保翻译代理进程在运行，返回 {"base_url", "token"} 供写 settings.json。"""
    status_file = _status_file()
    if status_file.exists():
        try:
            st = json.loads(status_file.read_text(encoding="utf-8"))
            if _port_alive(st.get("port")) and st.get("token"):
                return {
                    "base_url": f"http://127.0.0.1:{st['port']}",
                    "token": st["token"],
                }
        except (OSError, ValueError, KeyError):
            pass

    _spawn()
    deadline = time.time() + 20
    while time.time() < deadline:
        if status_file.exists():
            try:
                st = json.loads(status_file.read_text(encoding="utf-8"))
                if _port_alive(st.get("port")) and st.get("token"):
                    return {
                        "base_url": f"http://127.0.0.1:{st['port']}",
                        "token": st["token"],
                    }
            except (OSError, ValueError, KeyError):
                pass
        time.sleep(0.5)
    raise RuntimeError("本地翻译代理启动失败，请查看日志")


def is_proxy_running() -> dict:
    """返回代理运行状态：{"running": bool, "port": int|None, "pid": int|None}。"""
    status_file = _status_file()
    port = None
    pid = None
    if status_file.exists():
        try:
            st = json.loads(status_file.read_text(encoding="utf-8"))
            port = st.get("port")
            pid = st.get("pid")
        except (OSError, ValueError):
            pass
    if port and _port_alive(port):
        # 以实际占用端口的进程为准，防止状态文件 pid 过期
        return {"running": True, "port": port, "pid": _port_owner_pid(port) or pid}
    return {"running": False, "port": None, "pid": None}


def stop_proxy() -> dict:
    """停止本地翻译代理进程。"""
    st = is_proxy_running()
    if not st["running"]:
        return {"stopped": False, "detail": "代理未在运行"}
    status_file = _status_file()
    pids = set()
    if st.get("pid"):
        pids.add(str(st["pid"]))
    owner = _port_owner_pid(st.get("port"))
    if owner:
        pids.add(str(owner))
    for pid in pids:
        try:
            subprocess.run(
                ["taskkill", "/PID", pid, "/F"],
                capture_output=True,
                timeout=10,
            )
        except Exception:
            pass
    try:
        status_file.unlink()
    except OSError:
        pass
    return {"stopped": True, "detail": f"已停止代理进程 {sorted(pids)}"}


def main() -> None:
    from . import openai_proxy
    from .crypto import decrypt_text

    status_file = _status_file()
    previous = {}
    if status_file.exists():
        try:
            previous = json.loads(status_file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            previous = {}
    token = previous.get("token") or None

    first = True
    last_signature = None
    while True:
        cfg = _active_openai_config()
        if cfg is None:
            if not first:
                break
            time.sleep(POLL_INTERVAL)
            continue

        key = decrypt_text(cfg.api_key_encrypted)
        signature = (cfg.id, cfg.provider.id, cfg.provider.api_base, cfg.model)
        if signature != last_signature:
            info = openai_proxy.start(cfg.provider.api_base, key, token=token)
            token = info["token"]
            status_file.write_text(
                json.dumps({"pid": os.getpid(), "port": info["port"], "token": token}),
                encoding="utf-8",
            )
            last_signature = signature

        first = False
        time.sleep(POLL_INTERVAL)

    openai_proxy.stop()
    try:
        status_file.unlink()
    except OSError:
        pass


if __name__ == "__main__":
    main()
