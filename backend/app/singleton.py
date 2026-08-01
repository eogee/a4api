"""单实例检测（Windows 命名互斥体）。"""
import ctypes
import sys
from ctypes import wintypes

ERROR_ALREADY_EXISTS = 183
_MUTEX_NAME = "Local\\ApiSwitchDesktopApp"
_mutex_handle = None


def acquire() -> bool:
    """返回 True 表示当前为唯一实例；False 表示已有实例在运行。

    互斥体句柄由模块级引用持有，进程存活期间保持互斥。
    """
    global _mutex_handle
    if sys.platform != "win32":
        return True  # 非 Windows 开发兜底，放行

    kernel32 = ctypes.windll.kernel32
    kernel32.CreateMutexW.argtypes = [wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR]
    kernel32.CreateMutexW.restype = wintypes.HANDLE
    kernel32.GetLastError.restype = wintypes.DWORD
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL

    handle = kernel32.CreateMutexW(None, False, _MUTEX_NAME)
    if not handle:
        return True  # 创建失败时保守放行，避免误拦
    if kernel32.GetLastError() == ERROR_ALREADY_EXISTS:
        kernel32.CloseHandle(handle)
        return False
    _mutex_handle = handle
    return True
