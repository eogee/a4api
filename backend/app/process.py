"""Claude Code 进程探测与重启（Windows）。"""
import subprocess
import time
from pathlib import Path

IMAGE_NAMES = ("node.exe", "claude.exe", "claude")

# 使用 PowerShell CIM 查询：wmic 已被弃用，且其表格输出列顺序不稳定、长命令行会折行，
# 按固定列序解析并不可靠。CIM 输出每行一个纯数字 PID，解析简单稳定。
_CIM_QUERY = (
    "Get-CimInstance Win32_Process | "
    "Where-Object { $_.Name -in ('node.exe','claude.exe','claude') -and "
    "$_.CommandLine -match 'claude' } | "
    "ForEach-Object { $_.ProcessId }"
)


def _find_claude_pids() -> list:
    """查找命令行中包含 claude 的进程 PID。"""
    try:
        out = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", _CIM_QUERY],
            capture_output=True, text=True, timeout=15,
        ).stdout
    except Exception:
        return []
    pids = []
    for line in out.splitlines():
        line = line.strip()
        if line.isdigit():
            pids.append(line)
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
