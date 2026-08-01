"""切换与状态接口。"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ... import config_manager, crud, schemas
from ...crypto import decrypt_text
from ...database import get_db
from ...process import is_claude_running, restart_claude

router = APIRouter()


@router.get("/status", response_model=schemas.StatusOut)
def get_status(db: Session = Depends(get_db)):
    active = crud.get_active_config(db)
    current = config_manager.read_settings()
    return schemas.StatusOut(
        active_config=active,
        settings_file_exists=config_manager.settings_path().exists(),
        current_model=current.get("model"),
    )


@router.post("/switch/{config_id}", response_model=schemas.SwitchResult)
def switch_config(config_id: int, body: schemas.SwitchRequest, db: Session = Depends(get_db)):
    config = crud.get_config(db, config_id)
    if not config:
        raise HTTPException(404, "配置方案不存在")

    backup_path = None
    try:
        api_key = decrypt_text(config.api_key_encrypted)
        if not api_key:
            raise ValueError("API Key 解密失败")
        backup_path = config_manager.backup_settings()
        settings = config_manager.build_settings(
            config.provider, api_key, config.model, config.temperature
        )
        config_manager.atomic_write_settings(settings)
        crud.set_active(db, config)
        crud.add_log(db, config_id, "success", "切换成功")
    except Exception as e:
        crud.add_log(db, config_id, "failed", str(e))
        raise HTTPException(500, f"切换失败：{e}")

    process_info = None
    restarted = False
    if body.restart:
        process_info = restart_claude()
        restarted = True
    elif not is_claude_running():
        process_info = {"killed": 0, "started": False, "detail": "未发现运行中的 Claude Code 进程"}

    return schemas.SwitchResult(
        success=True,
        message="切换成功",
        backup_path=str(backup_path) if backup_path else None,
        restart=restarted,
        process_info=process_info,
    )
