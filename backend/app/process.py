"""Claude Code 进程探测与重启（Windows）。"""
import subprocess
import time
from pathlib import Path

IMAGE_NAMES = ("node.exe", "claude.exe", "claude")


def _find_claude_pids() -> list:
    """通过 wmic 查找命令行中包含 claude 的进程 PID。"""
    try:
        out = subprocess.run(
            ["wmic", "process", "get", "processid,name,commandline"],
            capture_output=True, text=True, timeout=10,
        ).stdout
    except Exception:
        return []
    pids = []
    for line in out.splitlines()[1:]:
        parts = line.split()
        if len(parts) < 2:
            continue
        name = parts[0].lower()
        if name in IMAGE_NAMES and "claude" in line.lower():
            pids.append(parts[1])
    return pids


def is_claude_running() -> bool:
    return bool(_find_claude_pids())


def restart_claude() -> dict:
    """关闭旧进程并重新打开一个新终端运行 claude。"""
    pids = _find_claude_pids()
    killed = 0
    for pid in pids:
        try:
            subprocess.run(["taskkill", "/PID", pid, "/F"],
                           capture_output=True, timeout=10)
            killed += 1
        except Exception:
            pass
    time.sleep(0.5)
    try:
        subprocess.Popen(["cmd", "/c", "start", "claude"], cwd=str(Path.home()))
        started = True
    except Exception:
        started = False
    return {
        "killed": killed,
        "started": started,
        "detail": f"已关闭 {killed} 个 Claude Code 进程" if killed else "未发现 Claude Code 进程",
    }
