from functools import lru_cache
from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field, field_validator
from typing import Literal

from .galancito_model_config import QWEN_2B


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    app_secret: str = "INSECURE_LOCAL_ONLY"
    database_url: str = "sqlite:///./galant-local.db"
    document_dir: Path = Path("/tmp/galant-post-documents")
    # Solo para el piloto documental: permite habilitar plantillas para PDF sin inventar revisiones profesionales.
    javiera_solo_pilot: bool = True
    max_upload_mb: int = 20
    max_pdf_pages: int = 50
    ocr_language: str = "spa+eng"
    ocr_secondary: str = "disabled"
    secure_cookies: bool = False
    session_hours: int = 8
    worker_poll_seconds: float = 2.0
    public_url: str = ""
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from: str = ""
    javiera_calc_url: str = ""
    javiera_calc_secret: str = ""
    # Facebook: activación explícita por entorno; el token solo vive en el worker.
    facebook_manual_testing_enabled: bool = False
    facebook_autopublish_enabled: bool = False
    facebook_page_id: str = ""
    facebook_page_token: str = ""
    # Mensajería: requiere Webhook firmado, permiso pages_messaging y organización explícita.
    facebook_messaging_enabled: bool = False
    facebook_org_id: str = ""
    facebook_app_secret: str = ""
    facebook_webhook_verify_token: str = ""
    # La IA requiere configuración privada; conversaciones y propuestas nunca se envían
    # a modelos externos cuando esta opción está desactivada.
    facebook_ai_enabled: bool = False
    # Messenger auto-responses use FACEBOOK_AI_ENABLED, Meta permissions and consent.
    facebook_ai_ad_enabled: bool = False
    facebook_worker_poll_seconds: float = Field(default=1.0, ge=0.1, le=5)
    facebook_ai_api_key: str = ""
    facebook_ai_model: str = "gpt-4.1-mini"
    facebook_ai_provider: str = "openai"
    # Exclusivamente Facebook Messenger y asesor de Red de Obras.
    galancito_ai_enabled: bool = False
    galancito_ai_api_key: str = ""
    galancito_ai_model: str = "gpt-4.1-mini"
    galancito_ai_provider: str = "openai"
    # Ollama se habilita solo tras descargar y probar el modelo en el VPS.
    galancito_local_model: Literal["qwen3.5:2b-q4_K_M"] = QWEN_2B
    galancito_local_ai_enabled: bool = False
    galancito_contextual_messenger_enabled: bool = False
    # 2m preserves warm service after 20s idle; generation limits stay bounded.
    galancito_keep_alive: Literal["20s", "2m", "5m"] = "2m"
    galancito_num_predict: int = Field(default=140, ge=40, le=140)
    galancito_num_ctx: int = Field(default=2048, ge=1024, le=4096)
    galancito_num_thread: int = Field(default=1, ge=1, le=4)
    galancito_timeout_seconds: float = Field(default=24, ge=1, le=60)
    galancito_memory_reserve_mb: int = Field(default=1536, ge=512, le=8192)

    @field_validator("galancito_local_model", mode="before")
    @classmethod
    def upgrade_local_model(cls, value):
        if value in ("qwen3:1.7b", "qwen3.5:4b-q4_K_M"):
            return QWEN_2B
        return value


@lru_cache
def settings() -> Settings:
    return Settings()
