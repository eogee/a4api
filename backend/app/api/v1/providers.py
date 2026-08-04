"""服务商接口。"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ... import crud, schemas
from ...database import get_db

router = APIRouter(prefix="/providers")


@router.get("", response_model=list[schemas.ProviderOut])
def list_providers(db: Session = Depends(get_db)):
    return crud.get_providers(db)


@router.post("", response_model=schemas.ProviderOut)
def create_provider(body: schemas.ProviderCreate, db: Session = Depends(get_db)):
    exists = db.query(crud.models.Provider).filter(
        crud.models.Provider.name == body.name
    ).first()
    if exists:
        raise HTTPException(409, f"服务商「{body.name}」已存在")
    return crud.create_provider(db, body.model_dump())


@router.get("/{provider_id}", response_model=schemas.ProviderOut)
def get_provider(provider_id: int, db: Session = Depends(get_db)):
    p = crud.get_provider(db, provider_id)
    if not p:
        raise HTTPException(404, "服务商不存在")
    return p


@router.put("/{provider_id}", response_model=schemas.ProviderOut)
def update_provider(provider_id: int, body: schemas.ProviderUpdate, db: Session = Depends(get_db)):
    p = crud.get_provider(db, provider_id)
    if not p:
        raise HTTPException(404, "服务商不存在")
    return crud.update_provider(db, p, body.model_dump(exclude_unset=True))


@router.delete("/{provider_id}")
def delete_provider(provider_id: int, db: Session = Depends(get_db)):
    p = crud.get_provider(db, provider_id)
    if not p:
        raise HTTPException(404, "服务商不存在")
    linked = (
        db.query(crud.models.Configuration)
        .filter(crud.models.Configuration.provider_id == provider_id)
        .count()
    )
    if linked:
        raise HTTPException(
            409,
            f"该服务商下还有 {linked} 个配置方案，请先删除这些配置方案",
        )
    db.delete(p)
    db.commit()
    return {"success": True}
