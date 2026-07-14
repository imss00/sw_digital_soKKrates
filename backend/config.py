import os

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Database
    database_url: str = "postgresql://paperback:paperback@localhost:5432/paperback"

    # Redis
    redis_url: str = "redis://localhost:6379/0"

    # JWT
    jwt_secret_key: str = "change-me"
    fernet_key: str = ""

    # Spotify
    spotify_client_id: str = ""
    spotify_client_secret: str = ""
    spotify_redirect_uri: str = "http://localhost:8000/auth/spotify/callback"

    # Google
    google_client_id: str = ""
    google_client_secret: str = ""
    google_redirect_uri: str = "http://localhost:8000/auth/google/callback"

    # Notion OAuth
    notion_client_id: str = ""
    notion_client_secret: str = ""
    notion_redirect_uri: str = "http://localhost:8000/auth/notion/callback"

    # Google API Key (YouTube Data API v3 — OAuth 불필요, 공개 영상 메타데이터용)
    google_api_key: str = ""

    # AI
    anthropic_api_key: str = ""
    openai_api_key: str = ""
    gemini_api_key: str = ""

    # Webhook secret (설정 시 X-Webhook-Secret 헤더 검증, 미설정 시 로컬 개발용 무인증)
    webhook_secret: str = ""
    allow_unprotected_webhooks: bool = False

    # 자동 인쇄 (매일 아침 신문을 PDF로 렌더해 프린터 이메일로 발송)
    print_enabled: bool = False
    frontend_base_url: str = "https://paperback-agent.fly.dev"
    resend_api_key: str = ""
    print_from_email: str = "PaperBack Agent <onboarding@resend.dev>"
    printer_email: str = ""
    print_user_id: int = 0

    # App
    app_host: str = "0.0.0.0"
    app_port: int = 8000

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


settings = Settings()

if settings.gemini_api_key and not os.environ.get("GOOGLE_API_KEY"):
    os.environ["GOOGLE_API_KEY"] = settings.gemini_api_key
