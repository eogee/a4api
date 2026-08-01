"""Pydantic 请求/响应模型。"""
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class ProviderBase(BaseModel):
    name: str
    api_base: str
    api_type: str = Field(pattern="^(anthropic|openai)$")
    is_custom: bool = False


class ProviderCreate(ProviderBase):
    pass


class ProviderUpdate(BaseModel):
    name: Optional[str] = None
    api_base: Optional[str] = None
    api_type: Optional[str] = Field(default=None, pattern="^(anthropic|openai)$")
    is_custom: Optional[bool] = None


class ProviderOut(ProviderBase):
    id: int
    created_at: datetime

    model_config = {"from_attributes": True}


class ConfigBase(BaseModel):
    name: str
    provider_id: int
    api_key: str = Field(..., description="明文 Key，后端加密存储")
    model: str
    temperature: Optional[float] = 0.7


class ConfigCreate(ConfigBase):
    pass


class ConfigUpdate(BaseModel):
    name: Optional[str] = None
    provider_id: Optional[int] = None
    api_key: Optional[str] = None
    model: Optional[str] = None
    temperature: Optional[float] = None


class ConfigOut(BaseModel):
    id: int
    name: str
    provider_id: int
    model: str
    temperature: Optional[float]
    is_active: bool
    created_at: datetime
    provider: Optional[ProviderOut] = None

    model_config = {"from_attributes": True}


class SwitchRequest(BaseModel):
    restart: bool = False


class SwitchResult(BaseModel):
    success: bool
    message: str
    backup_path: Optional[str] = None
    restart: bool = False
    process_info: Optional[dict] = None


class StatusOut(BaseModel):
    active_config: Optional[ConfigOut] = None
    settings_file_exists: bool
    current_model: Optional[str] = None
