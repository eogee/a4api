"""桌面入口：pywebview 加载 FastAPI 服务。

用法：
    python desktop.py
"""
import os
import socket
import sys
import threading

# 允许从项目根目录导入 backend 包（pyinstaller 打包时也依赖此路径策略）
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

if "--proxy-stop" in sys.argv:
    # 卸载/升级时停止后台翻译代理。必须在此处短路，
    # 避免拉入 backend.app.main 触发 FastAPI 初始化（建库、seed 等副作用）。
    from backend.app.proxy_standalone import stop_proxy

    stop_proxy()
    sys.exit(0)

import webview  # noqa: E402

from backend.app.main import app  # noqa: E402
from backend.app.singleton import acquire  # noqa: E402


def find_free_port() -> int:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def start_server(port: int) -> None:
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")


def main() -> None:
    if "--proxy" in sys.argv:
        from backend.app.proxy_standalone import main as proxy_main

        proxy_main()
        return

    if not acquire():
        import ctypes
        ctypes.windll.user32.MessageBoxW(None, "a4api 已在运行中。", "提示", 0x40)
        return

    port = find_free_port()
    t = threading.Thread(target=start_server, args=(port,), daemon=True)
    t.start()

    webview.create_window(
        "a4api",
        f"http://127.0.0.1:{port}",
        width=1000,
        height=720,
        min_size=(800, 560),
    )
    webview.start()
    # 窗口关闭后强制退出，避免后台线程挂住进程
    os._exit(0)


if __name__ == "__main__":
    main()
