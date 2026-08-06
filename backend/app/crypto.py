"""API Key 加解密。

优先使用 Windows DPAPI（直接调用 crypt32.dll，无第三方依赖）；
非 Windows 环境提供 base64 兜底（仅开发调试用，不具备安全性）。
"""
import base64
import ctypes
import logging
import sys
from ctypes import wintypes

logger = logging.getLogger(__name__)


class DATA_BLOB(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_ubyte))]


def _blob_to_bytes(blob: DATA_BLOB) -> bytes:
    return ctypes.string_at(blob.pbData, blob.cbData)


def _bytes_to_blob(data: bytes) -> DATA_BLOB:
    buf = ctypes.create_string_buffer(data, len(data))
    blob = DATA_BLOB(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_ubyte)))
    return blob


def _protect(data: bytes) -> bytes:
    blob_in = _bytes_to_blob(data)
    blob_out = DATA_BLOB()
    if not ctypes.windll.crypt32.CryptProtectData(
        ctypes.byref(blob_in),
        None, None, None, None, 0, ctypes.byref(blob_out),
    ):
        raise ctypes.WinError()
    try:
        return _blob_to_bytes(blob_out)
    finally:
        ctypes.windll.kernel32.LocalFree(blob_out.pbData)


def _unprotect(data: bytes) -> bytes:
    blob_in = _bytes_to_blob(data)
    blob_out = DATA_BLOB()
    if not ctypes.windll.crypt32.CryptUnprotectData(
        ctypes.byref(blob_in),
        None, None, None, None, 0, ctypes.byref(blob_out),
    ):
        raise ctypes.WinError()
    try:
        return _blob_to_bytes(blob_out)
    finally:
        ctypes.windll.kernel32.LocalFree(blob_out.pbData)


def _encrypt(plain: str) -> str:
    if sys.platform == "win32":
        return base64.b64encode(_protect(plain.encode("utf-8"))).decode("ascii")
    # 非 Windows 开发兜底：仅 base64，不加密
    return base64.b64encode(plain.encode("utf-8")).decode("ascii")


def _decrypt(cipher_b64: str) -> str:
    try:
        raw = base64.b64decode(cipher_b64.encode("ascii"))
    except Exception as e:
        logger.error("API Key 解密失败：base64 解码异常（%s）", e)
        return ""
    if sys.platform == "win32":
        try:
            return _unprotect(raw).decode("utf-8")
        except Exception as e:
            logger.error("API Key 解密失败：DPAPI 解密异常（%s）", e)
            return ""
    try:
        return raw.decode("utf-8", errors="replace")
    except Exception as e:
        logger.error("API Key 解密失败：UTF-8 解码异常（%s）", e)
        return ""


def encrypt_text(plain: str) -> str:
    """加密明文，返回可入库的 base64 字符串。"""
    return _encrypt(plain)


def decrypt_text(cipher_b64: str) -> str:
    """解密密文，返回明文；失败返回空字符串并记录日志。"""
    return _decrypt(cipher_b64)
