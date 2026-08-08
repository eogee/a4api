"""切换与状态接口。"""
import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ... import config_manager, crud, proxy_standalone, schemas
from ...crypto import decrypt_text
from ...database import get_db
from ...process import is_claude_running, restart_claude

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/status", response_model=schemas.StatusOut)
def get_status(db: Session = Depends(get_db)):
    active = crud.get_active_config(db)
    current = config_manager.read_settings()
    codex = config_manager.read_codex_settings()
    return schemas.StatusOut(
        active_config=active,
        settings_file_exists=config_manager.settings_path().exists(),
        current_model=current.get("model"),
        codex_file_exists=config_manager.codex_settings_path().exists(),
        current_codex_model=codex.get("model"),
        current_codex_provider=codex.get("model_provider"),
    )


@router.get("/proxy/status")
def proxy_status():
    """查询本地翻译代理是否在运行。"""
    return proxy_standalone.is_proxy_running()


@router.post("/proxy/stop")
def proxy_stop():
    """停止本地翻译代理进程。"""
    result = proxy_standalone.stop_proxy()
    if not result.get("stopped"):
        raise HTTPException(409, result.get("detail", "代理未在运行"))
    return result


@router.post("/switch/{config_id}", response_model=schemas.SwitchResult)
def switch_config(config_id: int, body: schemas.SwitchRequest, db: Session = Depends(get_db)):
    config = crud.get_config(db, config_id)
    if not config:
        raise HTTPException(404, "配置方案不存在")
    if config.provider is None:
        raise HTTPException(409, "该配置关联的服务商已被删除，请先编辑或删除此配置方案")

    backup_path = None
    codex_backup_path = None
    try:
        api_key = decrypt_text(config.api_key_encrypted)
        if not api_key:
            raise ValueError("API Key 解密失败")
        targets = config_manager.target_list(config.targets)
        # 目标含 Codex 但服务商非 OpenAI 兼容时，在标记生效 / 写任何文件之前干净失败，
        # 避免出现“Claude 配置已写入但整体报错”的半生效状态
        if "codex" in targets and config.provider.api_type != "openai":
            raise ValueError(
                f"Codex 需要 OpenAI 兼容（Responses）接口，"
                f"请为「{config.name}」选择 OpenAI 兼容的服务商"
            )
        proxy: dict | None = None
        # 先标记生效并提交，独立翻译代理进程才能从数据库找到当前配置
        crud.set_active(db, config)
        if "claude" in targets:
            backup_path = config_manager.backup_settings()
            # 读现有 settings.json 传入合并，保留 hooks / permissions 等用户已有键
            existing = config_manager.read_settings()
            if config.provider.api_type == "openai":
                # 独立代理进程：应用退出后仍然存活，Claude Code 可继续使用
                proxy = proxy_standalone.ensure_proxy_running()
                settings = config_manager.build_settings(
                    existing, config.provider, api_key, config.model, proxy=proxy
                )
            else:
                settings = config_manager.build_settings(
                    existing, config.provider, api_key, config.model
                )
            config_manager.atomic_write_settings(settings)
        if "codex" in targets:
            codex_backup_path = config_manager.backup_codex_settings()
            existing = config_manager.read_codex_settings()
            # 上游原生支持 Responses（如 DeepSeek）时直连上游，无需本地代理；
            # 仅提供 Chat Completions 的上游（如智谱）才经本地翻译代理转发。
            proxy = None
            if not config.provider.native_responses:
                proxy = proxy_standalone.ensure_proxy_running()
            codex_settings = config_manager.build_codex_settings(
                existing, config.provider, api_key, config.model, proxy=proxy
            )
            config_manager.atomic_write_codex_settings(codex_settings)
            config_manager.ensure_model_in_catalog(config.model, existing)
        crud.add_log(
            db, config_id, "success",
            "切换成功" + ("，Codex 配置已写入" if "codex" in targets else ""),
        )
    except Exception as e:
        logger.exception("切换配置「%s」失败", config.name)
        crud.add_log(db, config_id, "failed", str(e))
        raise HTTPException(500, f"切换失败：{e}")

    process_info = None
    restarted = False
    if body.restart and "claude" in targets:
        process_info = restart_claude()
        restarted = True
    elif "claude" in targets and not is_claude_running():
        process_info = {"killed": 0, "started": False, "detail": "未发现运行中的 Claude Code 进程"}

    message = "切换成功"
    if "codex" in targets:
        message += "；Codex 配置已写入（" + ("原生直连" if config.provider.native_responses else "经本地代理") + "），重启 Codex 后生效"
    return schemas.SwitchResult(
        success=True,
        message=message,
        backup_path=str(backup_path) if backup_path else None,
        codex_backup_path=str(codex_backup_path) if codex_backup_path else None,
        restart=restarted,
        process_info=process_info,
    )
