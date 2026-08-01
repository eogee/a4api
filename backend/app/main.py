"""FastAPI 应用入口（含静态文件托管）。"""
import sys
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from . import models  # noqa: F401  # 注册模型建表
from .api.v1 import configs, providers, switch
from .database import Base, engine
from .seed import seed_providers


def _frontend_dir() -> Path:
    """定位前端目录：打包后用 sys._MEIPASS，开发时用项目根。"""
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", ".")) / "frontend"
    return Path(__file__).resolve().parent.parent.parent / "frontend"


def create_app() -> FastAPI:
    app = FastAPI(title="api-switch", version="0.1.0")

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    Base.metadata.create_all(bind=engine)
    seed_providers()

    app.include_router(providers.router, prefix="/api/v1", tags=["providers"])
    app.include_router(configs.router, prefix="/api/v1", tags=["configs"])
    app.include_router(switch.router, prefix="/api/v1", tags=["switch"])

    # 前端静态资源：开发/桌面运行时由后端统一托管
    frontend_dir = _frontend_dir()
    if frontend_dir.exists():
        app.mount("/", StaticFiles(directory=str(frontend_dir), html=True), name="frontend")

    return app


app = create_app()
