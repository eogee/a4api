"""环境变量新旧名兼容读取。

品牌改名（a4api → a4agent）后，全部环境变量改用 A4AGENT_ 前缀；已发布的
脚本/文档可能仍在设置旧 A4API_ 名，读取侧统一走 env_first()：新名优先，
缺省时回退旧名，保证外部用法向后兼容。
"""
import os


def env_first(*names: str) -> str | None:
    """按顺序返回第一个非空的环境变量值；都未设置返回 None。"""
    for name in names:
        value = os.environ.get(name)
        if value:
            return value
    return None
