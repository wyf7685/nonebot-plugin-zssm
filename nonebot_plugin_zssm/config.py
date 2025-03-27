from nonebot.compat import field_validator
from pydantic import BaseModel


class Config(BaseModel):
    zssm_ai_text_endpoint: str = "https://api.deepseek.com/v1"
    zssm_ai_text_token: str | None = None
    zssm_ai_text_model: str = "deepseek-chat"

    zssm_ai_vl_endpoint: str = "https://api.siliconflow.cn/v1"
    zssm_ai_vl_token: str | None = None
    zssm_ai_vl_model: str = "Qwen/Qwen2.5-VL-72B-Instruct"

    zssm_browser_proxy: str | None = None

    @field_validator("zssm_ai_text_endpoint")
    def check_zssm_ai_text_endpoint(cls, v):  # noqa: N805
        if not v.startswith("http://") and not v.startswith("https://"):
            raise ValueError("zssm_ai_text_endpoint must start with http:// or https://")
        return v

    @field_validator("zssm_ai_text_token")
    def check_zssm_ai_text_token(cls, v):  # noqa: N805
        if not v:
            raise ValueError("zssm_ai_text_token must not be empty")
        return v

    @field_validator("zssm_ai_text_model")
    def check_zssm_ai_text_model(cls, v):  # noqa: N805
        if not v:
            raise ValueError("zssm_ai_text_model must not be empty")
        return v
