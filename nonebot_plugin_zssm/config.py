from typing import Literal

from nonebot import get_plugin_config
from nonebot.compat import field_validator
from pydantic import BaseModel, Field


class LLMConfig(BaseModel):
    endpoint: str
    token: str
    name: str = Field(alias="model")

    @field_validator("endpoint")
    def check_endpoint(cls, v):  # noqa: N805
        v = str(v)
        if not v.startswith("http://") and not v.startswith("https://"):
            raise ValueError("Endpoint must start with http:// or https://")
        return v

    @field_validator("token")
    def check_token(cls, v):  # noqa: N805
        if not v:
            raise ValueError("Token must not be empty")
        return v

    @field_validator("name")
    def check_model_name(cls, v):  # noqa: N805
        if not v:
            raise ValueError("Model must not be empty")
        return v


class BrowserConfig(BaseModel):
    proxy: str | None = None
    type: Literal["chromium", "firefox", "webkit"] = "chromium"
    install_on_startup: bool = True


class PdfConfig(BaseModel):
    max_size: int = 10 * 1024 * 1024  # 10MB
    max_pages: int = 50  # 最大处理页数
    max_chars: int = 300000  # 最大字符数


class PluginConfig(BaseModel):
    text: LLMConfig
    vl: LLMConfig
    check: LLMConfig | None = None
    browser: BrowserConfig = BrowserConfig()
    pdf: PdfConfig = PdfConfig()


class Config(BaseModel):
    zssm: PluginConfig


plugin_config = get_plugin_config(Config).zssm
