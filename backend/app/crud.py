"""数据库操作封装。"""
from sqlalchemy.orm import Session

from . import models


def get_providers(db: Session) -> list:
    return db.query(models.Provider).order_by(models.Provider.id).all()


def get_provider(db: Session, provider_id: int):
    return db.query(models.Provider).filter(models.Provider.id == provider_id).first()


def create_provider(db: Session, data: dict) -> models.Provider:
    p = models.Provider(**data)
    db.add(p)
    db.commit()
    db.refresh(p)
    return p


def update_provider(db: Session, provider: models.Provider, data: dict) -> models.Provider:
    for k, v in data.items():
        if v is not None:
            setattr(provider, k, v)
    db.commit()
    db.refresh(provider)
    return provider


def delete_provider(db: Session, provider_id: int) -> bool:
    p = get_provider(db, provider_id)
    if not p:
        return False
    db.delete(p)
    db.commit()
    return True


def get_configs(db: Session) -> list:
    return db.query(models.Configuration).order_by(models.Configuration.id).all()


def get_config(db: Session, config_id: int):
    return db.query(models.Configuration).filter(models.Configuration.id == config_id).first()


def get_active_config(db: Session):
    return db.query(models.Configuration).filter(models.Configuration.is_active.is_(True)).first()


def create_config(db: Session, data: dict) -> models.Configuration:
    c = models.Configuration(**data)
    db.add(c)
    db.commit()
    db.refresh(c)
    return c


def update_config(db: Session, config: models.Configuration, data: dict) -> models.Configuration:
    for k, v in data.items():
        if v is not None:
            setattr(config, k, v)
    db.commit()
    db.refresh(config)
    return config


def delete_config(db: Session, config_id: int) -> bool:
    c = get_config(db, config_id)
    if not c:
        return False
    db.delete(c)
    db.commit()
    return True


def set_active(db: Session, config: models.Configuration) -> None:
    """将指定配置设为当前方案，清除其余方案的 active 标记。"""
    db.query(models.Configuration).filter(models.Configuration.is_active.is_(True)).update({"is_active": False})
    config.is_active = True
    db.commit()


def add_log(db: Session, config_id, status: str, detail: str = "") -> None:
    log = models.SwitchLog(config_id=config_id, status=status, detail=detail)
    db.add(log)
    db.commit()
