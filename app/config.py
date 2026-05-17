from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    DATABASE_URL: str
    SECRET_KEY: str
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 15  # Сокращено для безопасности
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7  # Refresh token живет 7 дней

    # Rate limit на /auth/login и /auth/refresh (slowapi format: "N/period").
    # Prod: "5/minute" защищает от brute-force. Dev/CI/e2e-suite: подними до
    # "100/minute" через env-var — без этого playwright suite получает 429
    # к 6-му логину (5 в 01-login.spec + 1 setup + ещё несколько в обходных
    # тестах за минуту).
    AUTH_LOGIN_RATE_LIMIT: str = "5/minute"
    AUTH_REFRESH_RATE_LIMIT: str = "10/minute"
    
    # CORS Configuration
    CORS_ORIGINS: str  # Список origins через запятую, например: "https://example.com,https://app.example.com"
    
    # Logging Configuration
    DEBUG: bool = False  # В продакшене должно быть False
    LOG_LEVEL: str = "INFO"  # DEBUG, INFO, WARNING, ERROR, CRITICAL
    
    # MinIO / S3 Configuration
    S3_ENDPOINT_URL: str
    S3_PUBLIC_ENDPOINT_URL: str
    S3_ACCESS_KEY: str
    S3_SECRET_KEY: str
    S3_BUCKET_NAME: str = "pobo-documents"
    S3_REGION: str = "us-east-1"
    
    # Application Settings
    MAX_UPLOAD_MB: int = 50

    # ComplyAdvantage (AML Screening)
    COMPLY_ADVANTAGE_BASE_URL: str = "https://api.mesh.complyadvantage.com"
    COMPLY_ADVANTAGE_REALM: str = ""
    COMPLY_ADVANTAGE_USERNAME: str = ""
    COMPLY_ADVANTAGE_PASSWORD: str = ""
    COMPLY_ADVANTAGE_SCREENING_CONFIG_ID: str = ""
    
    # SMTP Configuration for fastapi-mail
    SMTP_HOST: str = "smtp.gmail.com"
    SMTP_PORT: int = 587
    SMTP_USER: str = ""
    SMTP_PASSWORD: str = ""
    MAIL_FROM: str = ""
    MAIL_FROM_NAME: str = "Garudar B2B"
    MAIL_TO_ADMIN: str = ""
    MAIL_STARTTLS: bool = True
    MAIL_SSL_TLS: bool = False
    USE_CREDENTIALS: bool = True
    VALIDATE_CERTS: bool = True

    class Config:
        env_file = ".env"
        extra = "ignore"


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
