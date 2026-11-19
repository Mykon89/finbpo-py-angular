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
    dados_chave: str = ""  # chave dos CPFs cifrados (base64, 64 bytes); vazio = derivada do SECRET_KEY
    mcp_mascarar_pf: bool = True  # o conector do Claude recebe CPF e nome de pessoa física mascarados
    retencao_arquivos_dias: int = 90  # arquivos já importados da pasta monitorada são apagados depois disso
    auditoria_dias: int = 1825  # eventos de auditoria guardados por 5 anos
    # Conta de serviço do Google (JSON) com acesso de leitura à planilha FECHAMENTO; vazio = link público
    google_service_account_file: str = ""
    # Pasta monitorada: extratos salvos nela são importados sozinhos (subpasta com o id ou CNPJ escolhe a entidade)
    extratos_pasta: str = ""
    extratos_entidade_id: int | None = None  # entidade dos arquivos soltos na raiz da pasta
    extratos_intervalo_segundos: int = 60
    tarefas_automaticas: bool = True  # pasta monitorada + tarefas diárias (retenção, auditoria, bancos)
    aliquota_imposto_comissao: float = 0.087  # alíquota usada na coluna IMP (planilha: =C.BRUTA*0,087)


settings = Settings()
