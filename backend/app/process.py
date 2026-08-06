"""Claude Code 进程探测与重启（Windows）。"""
import logging
import subprocess
import time
from pathlib import Path

logger = logging.getLogger(__name__)

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
    except Exception as e:
        logger.warning("探测 Claude Code 进程失败：%s", e)
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
    """关闭旧进程并重新打开一个新终端运行 claude，等待并验证新进程是否真正启动。"""
    pids = _find_claude_pids()
    killed = 0
    for pid in pids:
        try:
            subprocess.run(["taskkill", "/PID", pid, "/F"],
                           capture_output=True, timeout=10)
            killed += 1
        except Exception as e:
            logger.warning("结束 Claude Code 进程 %s 失败：%s", pid, e)
    time.sleep(0.5)
    try:
        subprocess.Popen(["cmd", "/c", "start", "claude"], cwd=str(Path.home()))
    except Exception as e:
        logger.error("启动 Claude Code 失败：%s", e)
        return {
            "killed": killed,
            "started": False,
            "detail": f"启动 Claude Code 失败：{e}",
        }

    # 启动命令立刻返回，但新进程可能延迟出现；最多等待 10 秒确认
    for _ in range(10):
        if is_claude_running():
            return {
                "killed": killed,
                "started": True,
                "detail": "已重启 Claude Code 进程",
            }
        time.sleep(1)

    logger.warning("Claude Code 启动后 10 秒内未探测到进程，可能未正确安装")
    return {
        "killed": killed,
        "started": False,
        "detail": "Claude Code 启动超时，请检查是否已安装",
    }
