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


def _ensure_icon(resources: Path) -> Path | None:
    """从 resources/logo.png 生成多尺寸 logo.ico，作为 exe 图标。

    png 更新或 ico 缺失时重新生成；无图标或缺少 Pillow 时返回 None，
    打包不因缺图标而失败。
    """
    png = resources / "logo.png"
    ico = resources / "logo.ico"
    if png.exists() and (not ico.exists() or png.stat().st_mtime > ico.stat().st_mtime):
        try:
            from PIL import Image
        except ImportError:
            print("提示：生成图标需要 Pillow（uv add --dev pillow），本次跳过图标生成")
            return None
        im = Image.open(png).convert("RGBA")
        w, h = im.size
        side = max(w, h)
        canvas = Image.new("RGBA", (side, side), (0, 0, 0, 0))
        canvas.paste(im, ((side - w) // 2, (side - h) // 2), im)
        # 先放大到 256 主图再保存：Pillow 会静默丢弃大于源图尺寸的目标尺寸
        master = canvas.resize((256, 256), Image.LANCZOS)
        master.save(
            ico,
            format="ICO",
            sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)],
        )
        print(f"已生成图标：{ico}")
    return ico if ico.exists() else None


def main() -> None:
    frontend = ROOT / "frontend"
    resources = ROOT / "resources"
    entry = ROOT / "desktop.py"
    sep = os.pathsep
    ico = _ensure_icon(resources)

    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--onefile",
        "--windowed",
        "--name", "a4api",
        "--add-data", f"{frontend}{sep}frontend",
    ]
    if ico is not None:
        cmd += ["--icon", str(ico)]
    if resources.exists() and any(resources.iterdir()):
        cmd += ["--add-data", f"{resources}{sep}resources"]
    for mod in HIDDEN_IMPORTS:
        cmd += ["--hidden-import", mod]
    cmd.append(str(entry))

    print("执行命令：", " ".join(cmd))
    subprocess.run(cmd, cwd=str(ROOT), check=True)
    print("\n打包完成：dist/a4api.exe")


if __name__ == "__main__":
    main()
