"""统一日志配置。"""
import logging
import sys
from pathlib import Path


def setup_logging(level: int = logging.INFO) -> None:
    """配置根日志器：控制台 + 用户目录下的日志文件。重复调用不会重复添加 handler。"""
    root = logging.getLogger()
    if root.handlers:
        return

    fmt = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
    handlers: list = [logging.StreamHandler(sys.stdout)]

    log_dir = Path.home() / ".a4api" / "logs"
    try:
        log_dir.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(log_dir / "a4api.log", encoding="utf-8")
        file_handler.setFormatter(fmt)
        handlers.append(file_handler)
    except OSError:
        # 日志目录不可写时退化到仅控制台，不能让应用因此启动失败
        pass

    logging.basicConfig(
        level=level,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        handlers=handlers,
        force=True,
    )
