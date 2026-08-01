"""PyInstaller 单 exe 打包脚本（一期）。

用法：
    uv run python build.py
"""
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent

HIDDEN_IMPORTS = [
    # uvicorn 动态加载的模块
    "uvicorn.logging",
    "uvicorn.loops",
    "uvicorn.loops.auto",
    "uvicorn.protocols",
    "uvicorn.protocols.http",
    "uvicorn.protocols.http.auto",
    "uvicorn.protocols.websockets",
    "uvicorn.protocols.websockets.auto",
    "uvicorn.lifespan",
    "uvicorn.lifespan.on",
    # pywebview / pythonnet 运行时
    "clr_loader",
    "webview",
    "webview.platforms.winforms",
]


def main() -> None:
    frontend = ROOT / "frontend"
    resources = ROOT / "resources"
    entry = ROOT / "desktop.py"
    sep = os.pathsep

    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--onefile",
        "--windowed",
        "--name", "api-switch",
        "--add-data", f"{frontend}{sep}frontend",
    ]
    if resources.exists() and any(resources.iterdir()):
        cmd += ["--add-data", f"{resources}{sep}resources"]
    for mod in HIDDEN_IMPORTS:
        cmd += ["--hidden-import", mod]
    cmd.append(str(entry))

    print("执行命令：", " ".join(cmd))
    subprocess.run(cmd, cwd=str(ROOT), check=True)
    print("\n打包完成：dist/api-switch.exe")


if __name__ == "__main__":
    main()
