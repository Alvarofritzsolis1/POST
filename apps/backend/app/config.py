from functools import lru_cache
from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict


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
    facebook_ai_auto_reply_enabled: bool = False
    facebook_ai_ad_enabled: bool = False
    facebook_ai_api_key: str = ""
    facebook_ai_model: str = "gpt-4.1-mini"
    # GALANCITO interno. Separado del acceso externo a conversaciones de Messenger.
    galancito_ai_enabled: bool = False
    galancito_ai_api_key: str = ""
    galancito_ai_model: str = "gpt-4.1-mini"



@lru_cache
def settings() -> Settings:
    return Settings()
