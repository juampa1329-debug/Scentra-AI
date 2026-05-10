from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = ""
    saas_env: str = "local"
    saas_jwt_secret: str = "dev-only-change-me"
    saas_jwt_issuer: str = "scentra-ai"
    saas_access_token_minutes: int = 15
    saas_refresh_token_days: int = 15
    saas_cors_origins: str = "http://localhost:5174,http://127.0.0.1:5174,http://localhost:5175,http://127.0.0.1:5175,http://localhost:3000,http://127.0.0.1:3000"
    saas_trial_days: int = 30
    saas_trial_plan_code: str = "starter"

    @property
    def cors_origins(self) -> list[str]:
        return [item.strip() for item in self.saas_cors_origins.split(",") if item.strip()]

    @property
    def is_local(self) -> bool:
        return self.saas_env.strip().lower() in {"local", "dev", "development"}


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
