from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict

DEFAULT_CORS_ORIGINS = [
    "http://localhost:5174",
    "http://127.0.0.1:5174",
    "http://localhost:5175",
    "http://127.0.0.1:5175",
    "http://localhost:3000",
    "http://127.0.0.1:3000",
    "https://app.scentra-ai.online",
    "https://admin.scentra-ai.online",
    "https://api.scentra-ai.online",
    "https://scentra-ai.online",
    "https://www.scentra-ai.online",
    "http://app.scentra-ai.online",
    "http://admin.scentra-ai.online",
    "http://api.scentra-ai.online",
    "http://scentra-ai.online",
    "http://www.scentra-ai.online",
]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = ""
    saas_env: str = "local"
    saas_jwt_secret: str = "dev-only-change-me"
    saas_jwt_issuer: str = "scentra-ai"
    saas_access_token_minutes: int = 15
    saas_refresh_token_days: int = 15
    saas_secret_key: str = ""
    saas_cors_origins: str = ",".join(DEFAULT_CORS_ORIGINS)
    saas_trial_days: int = 30
    saas_trial_plan_code: str = "starter"
    saas_embedded_worker_enabled: bool = True
    saas_worker_idle_sec: int = 5
    saas_worker_batch_size: int = 25
    scentra_api_public_url: str = "https://api.scentra-ai.online"
    scentra_app_public_url: str = "https://app.scentra-ai.online"
    scentra_meta_app_id: str = ""
    scentra_meta_app_secret: str = ""
    scentra_meta_graph_version: str = "v24.0"
    scentra_instagram_webhook_verify_token: str = ""

    @property
    def cors_origins(self) -> list[str]:
        configured = [item.strip().rstrip("/") for item in self.saas_cors_origins.split(",") if item.strip()]
        merged = [*DEFAULT_CORS_ORIGINS, *configured]
        return list(dict.fromkeys(item for item in merged if item))

    @property
    def is_local(self) -> bool:
        return self.saas_env.strip().lower() in {"local", "dev", "development"}


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
