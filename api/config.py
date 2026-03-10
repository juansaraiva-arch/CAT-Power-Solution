"""
CAT Power Solution — Application Configuration
================================================
Reads all configuration from environment variables.
In production: variables are injected from Azure Key Vault
               via App Service configuration.
In development: loaded from .env file.
"""

from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # ── App ──────────────────────────────────────────────────────────
    environment: str = "development"      # development | staging | production
    app_version: str = "3.2.0"
    log_level: str = "INFO"

    # ── Entra ID (Azure AD) ──────────────────────────────────────────
    entra_tenant_id: str = "caterpillar.com"
    entra_app_client_id: str = ""         # requerido en producción

    # ── Security Groups (nombres exactos en Entra ID) ────────────────
    sg_demo: str = "SG-CPS-Demo"
    sg_full: str = "SG-CPS-Full"
    sg_admin: str = "SG-CPS-Admin"

    # ── Database ─────────────────────────────────────────────────────
    database_url: str = ""               # postgresql://user:pass@host/db
    db_pool_size: int = 5
    db_max_overflow: int = 10

    # ── Azure Blob Storage ───────────────────────────────────────────
    azure_storage_account_name: str = ""
    azure_storage_container_pdfs: str = "cat-power-solution-pdfs"
    azure_storage_key: str = ""          # vacío en producción (usa Managed Identity)
    pdf_sas_expiry_hours: int = 24

    # ── Anthropic ────────────────────────────────────────────────────
    anthropic_api_key: str = ""

    # ── Rate Limiting ────────────────────────────────────────────────
    max_requests_per_hour: int = 100
    max_requests_demo_per_hour: int = 20

    # ── CORS ─────────────────────────────────────────────────────────
    allowed_origins: str = "http://localhost:3000,http://localhost:8000"
    # En producción: "https://cat-power-solution.cat.com,https://caterpillar.com"

    # ── Audit ────────────────────────────────────────────────────────
    pdf_retention_days: int = 90
    audit_retention_days: int = 90

    # ── Feature flags ────────────────────────────────────────────────
    enable_pdf_generation: bool = True
    enable_db_persistence: bool = False  # False hasta que IT configure PostgreSQL
    require_auth: bool = True            # False solo para desarrollo local

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )


@lru_cache()
def get_settings() -> Settings:
    return Settings()
