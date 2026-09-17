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

if "--apply-update" in sys.argv:
    # 自更新应用阶段（由 updater.apply 以 DETACHED_PROCESS 独立拉起）：
    # 等待主实例退出并释放 AppMutex，然后启动安装器并立即退出。
    # 必须短路在 import webview / FastAPI / acquire() 之前，仅用 stdlib。
    import ctypes
    import subprocess
    import time
    from ctypes import wintypes

    _MUTEX = "Local\\A4ApiDesktopApp"
    _ERROR_ALREADY_EXISTS = 183

    def _wait_mutex_released(timeout_s: float = 20) -> bool:
        """轮询等待主实例释放 AppMutex；拿到所有权立即释放给安装器。"""
        if sys.platform != "win32":
            time.sleep(2)  # 非 Windows 开发兜底
            return True
        kernel32 = ctypes.windll.kernel32
        kernel32.CreateMutexW.argtypes = [wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR]
        kernel32.CreateMutexW.restype = wintypes.HANDLE
        kernel32.GetLastError.restype = wintypes.DWORD
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel32.CloseHandle.restype = wintypes.BOOL
        deadline = time.time() + timeout_s
        while time.time() < deadline:
            handle = kernel32.CreateMutexW(None, False, _MUTEX)
            if not handle:  # 创建失败（如权限）→ 重试，不当作已就绪
                time.sleep(0.2)
                continue
            if kernel32.GetLastError() != _ERROR_ALREADY_EXISTS:
                kernel32.CloseHandle(handle)  # 立即释放，让安装器能创建互斥体
                return True
            kernel32.CloseHandle(handle)
            time.sleep(0.2)
        return False

    idx = sys.argv.index("--apply-update")
    installer = sys.argv[idx + 1] if idx + 1 < len(sys.argv) else ""
    if not installer:
        sys.exit(2)
    # 主实例未在超时内释放 AppMutex（如异常卡死）→ 放弃应用，避免 Inno 覆盖失败/残留
    if not _wait_mutex_released():
        sys.exit(3)
    # 用 Popen 启动可见安装向导后立即退出：不 run 等待，否则本进程会一直占用
    # _internal 的 DLL 句柄，Inno 升级时 DelTree(_internal) 将残留旧文件。
    subprocess.Popen([installer], close_fds=True)
    time.sleep(1)
    os._exit(0)

import webview  # noqa: E402

from backend.app.main import app  # noqa: E402
from backend.app.singleton import acquire  # noqa: E402


class DesktopApi:
    """暴露给前端 JS 的原生对话框能力（window.pywebview.api.*）。

    仅在 pywebview 桌面环境存在；纯浏览器打开时前端自动退回手动输入路径。
    """

    def select_folder(self):
        """弹出系统文件夹选择对话框，返回所选路径；取消返回 None。"""
        import webview as _webview

        win = _webview.windows[0] if _webview.windows else None
        if win is None:
            return None
        result = win.create_file_dialog(_webview.FileDialog.FOLDER)
        return result[0] if result else None

    def select_file(self):
        """弹出系统文件选择对话框（单选），返回所选路径；取消返回 None。"""
        import webview as _webview

        win = _webview.windows[0] if _webview.windows else None
        if win is None:
            return None
        try:
            result = win.create_file_dialog(
                _webview.FileDialog.OPEN, allow_multiple=False,
                file_types=("所有文件 (*.*)", "所有文件 (*.*)"),
            )
        except Exception:
            result = win.create_file_dialog(_webview.FileDialog.OPEN)
        return result[0] if result else None


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
        js_api=DesktopApi(),
    )
    webview.start()
    # 窗口关闭后先回收本地推理引擎（llama-server 子进程），再强制退出，
    # 避免后台线程/子进程挂住进程
    try:
        from backend.app.llama import runtime as llama_runtime

        llama_runtime.shutdown()
    except Exception:
        pass
    os._exit(0)


if __name__ == "__main__":
    main()
