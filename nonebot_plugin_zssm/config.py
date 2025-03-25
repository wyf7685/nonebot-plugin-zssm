from pydantic import BaseModel, field_validator


class Config(BaseModel):
    zssm_ai_endpoint: str = "https://api.deepseek.com/v1"
    zssm_ai_token: str | None = None
    zssm_ai_model: str = "deepseek-chat"

    @field_validator("zssm_ai_endpoint")
    def check_zssm_ai_endpoint(cls, v):
        if not v.startswith("http://") and not v.startswith("https://"):
            raise ValueError("zssm_ai_endpoint must start with http:// or https://")
        return v

    @field_validator("zssm_ai_token")
    def check_zssm_ai_token(cls, v):
        if not v:
            raise ValueError("zssm_ai_token must not be empty")
        return v

    @field_validator("zssm_ai_model")
    def check_zssm_ai_model(cls, v):
        if not v:
            raise ValueError("zssm_ai_model must not be empty")
        return v
