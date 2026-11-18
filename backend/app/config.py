from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg://finbpo:finbpo@localhost:5432/finbpo"
    secret_key: str = "dev-inseguro-troque-em-producao-0123456789"
    access_token_minutes: int = 480
    cors_origins: list[str] = ["http://localhost:4200"]
    # Tolerância (dias) entre vencimento e data do extrato na conciliação automática
    conciliacao_tolerancia_dias: int = 5
    # Token do conector MCP (Claude Desktop / Claude Code). Vazio = conector desligado.
    mcp_token: str = ""


settings = Settings()
