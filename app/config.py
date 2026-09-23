from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    poll_interval_minutes: int = 15
    db_path: str = "/data/damgala.db"
    dashboard_port: int = 8000
    history_lookback_days: int = 3650
    log_level: str = "INFO"


settings = Settings()
