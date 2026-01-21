from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # -------------------------
    # App
    # -------------------------
    app_name: str = "TH8 Backend"
    api_prefix: str = "/api"
    cors_allow_origins: str = "*"

    # -------------------------
    # Supabase
    # -------------------------
    supabase_url: str
    supabase_service_role_key: str
 # ✅ ADD THIS
    supabase_service_key: str
    # -------------------------
    # Optional / future integrations
    # -------------------------
    supabase_key: str | None = None

    line_channel_access_token: str | None = None
    line_channel_secret: str | None = None

    openai_api_key: str | None = None
    ENABLE_ORCHESTRATOR: bool = False
    # -------------------------
    # Pydantic v2 config
    # -------------------------
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
    )
    API_BASE_URL: str = "http://127.0.0.1:8000/api"
    # LlamaCloud (สำหรับ LlamaParse) ✅ เพิ่มตรงนี้
    LLAMA_CLOUD_API_KEY: str
 

settings = Settings()
