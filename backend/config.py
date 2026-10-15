"""
Application configuration loaded from environment variables / .env file.
"""

from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    APP_ENV: str = "development"
    APP_DEBUG: bool = True
    SECRET_KEY: str = "change-me"

    DATABASE_URL: str = "sqlite:///./data/violations.db"
    CAPTURES_DIR: str = "./data/captures"

    HOST: str = "0.0.0.0"
    PORT: int = 8000

    # Optional OCR backend identifier (local | google_vision | azure)
    OCR_PROVIDER: str = "local"
    OCR_API_KEY: str = ""

    # Email notification settings (SMTP)
    # When SMTP_HOST is empty, NotificationService operates in safe DRY-RUN logging mode
    SMTP_HOST: str = ""
    SMTP_PORT: int = 587
    SMTP_USER: str = ""
    SMTP_PASSWORD: str = ""
    EMAIL_FROM: str = "traffic-alerts@campus.edu"
    AUTHORITY_EMAIL: str = "campus-security@campus.edu"

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()

# Ensure data and captures directories exist
Path(settings.CAPTURES_DIR).mkdir(parents=True, exist_ok=True)
Path("./data").mkdir(parents=True, exist_ok=True)
