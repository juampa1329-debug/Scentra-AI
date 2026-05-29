from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict

DEFAULT_CORS_ORIGINS = [
    "http://localhost:5174",
    "http://127.0.0.1:5174",
    "http://localhost:5175",
    "http://127.0.0.1:5175",
    "http://localhost:8011",
    "http://127.0.0.1:8011",
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
    saas_worker_idle_sec: int = 10
    saas_worker_batch_size: int = 10
    saas_db_pool_size: int = 10
    saas_db_max_overflow: int = 20
    saas_db_pool_timeout_sec: int = 20
    saas_db_pool_recycle_sec: int = 1800
    saas_captcha_enabled: bool = False
    saas_captcha_provider: str = "turnstile"
    saas_rate_limit_enabled: bool = True
    saas_login_lock_failed_attempts: int = 6
    saas_login_lock_minutes: int = 15
    saas_password_reset_minutes: int = 30
    saas_password_reset_path: str = "/?reset_token="
    saas_mfa_otp_minutes: int = 10
    saas_mfa_otp_length: int = 6
    saas_mfa_max_attempts: int = 5
    saas_mfa_required_roles: str = ""
    saas_admin_mfa_required_roles: str = ""
    saas_security_notify_enabled: bool = True
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_username: str = ""
    smtp_password: str = ""
    smtp_from_email: str = ""
    smtp_starttls: bool = True
    saas_meta_token_refresh_enabled: bool = True
    saas_meta_token_refresh_interval_hours: int = 12
    saas_meta_token_refresh_batch_size: int = 10
    scentra_api_public_url: str = "https://api.scentra-ai.online"
    scentra_app_public_url: str = "https://app.scentra-ai.online"
    scentra_meta_app_id: str = ""
    scentra_meta_app_secret: str = ""
    scentra_meta_graph_version: str = "v24.0"
    scentra_instagram_webhook_verify_token: str = ""
    turnstile_secret_key: str = ""
    billing_default_provider: str = "manual"
    saas_billing_lifecycle_interval_minutes: int = 30
    billing_past_due_grace_days: int = 7
    billing_success_url: str = "https://app.scentra-ai.online/?billing=success"
    billing_cancel_url: str = "https://app.scentra-ai.online/?billing=cancelled"
    stripe_secret_key: str = ""
    stripe_webhook_secret: str = ""
    mercadopago_access_token: str = ""
    mercadopago_webhook_secret: str = ""
    wompi_environment: str = "production"
    wompi_public_key: str = ""
    wompi_private_key: str = ""
    wompi_integrity_key: str = ""
    wompi_events_key: str = ""
    saas_ml_enabled: bool = False
    saas_ml_shadow_inference_enabled: bool = False
    saas_ml_auto_train_enabled: bool = False
    saas_ml_service_url: str = "http://ml-service:8090"
    saas_ml_inference_timeout_sec: int = 3
    saas_mlflow_tracking_uri: str = "http://mlflow:5000"
    saas_ml_model_dir: str = "/models"
    saas_qdrant_url: str = "http://qdrant:6333"

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
