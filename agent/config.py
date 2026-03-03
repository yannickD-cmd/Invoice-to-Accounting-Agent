"""Application settings loaded from environment variables."""

from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Central configuration — all values come from env vars / .env file."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── App ───────────────────────────────────────────────────────────
    app_env: str = "development"
    log_level: str = "INFO"

    # ── Anthropic ─────────────────────────────────────────────────────
    anthropic_api_key: str = ""

    # ── Google ────────────────────────────────────────────────────────
    google_service_account_json: str = ""
    gmail_ap_inbox: str = ""
    gmail_marie_email: str = ""
    gmail_thomas_email: str = ""
    gmail_gm_email: str = ""
    google_drive_root_folder_id: str = ""
    google_budget_sheet_id: str = ""

    # ── Pennylane ─────────────────────────────────────────────────────
    pennylane_base_url: str = "https://app.pennylane.com/api/v1"
    pennylane_token_cc01: str = ""
    pennylane_token_cc02: str = ""
    pennylane_token_cc03: str = ""
    pennylane_token_cc04: str = ""
    pennylane_token_cc05: str = ""
    pennylane_token_cc06: str = ""
    pennylane_token_cc07: str = ""
    pennylane_token_cc08: str = ""

    # ── Slack ─────────────────────────────────────────────────────────
    slack_bot_token: str = ""
    slack_app_token: str = ""
    slack_channel_invoices: str = ""
    slack_channel_exceptions: str = ""
    slack_channel_alerts: str = ""
    slack_channel_finance_ops: str = ""

    # Slack user IDs
    slack_user_marie: str = ""
    slack_user_thomas: str = ""
    slack_user_direction: str = ""
    slack_user_pm_cc01: str = ""
    slack_user_pm_cc02: str = ""
    slack_user_pm_cc03: str = ""
    slack_user_pm_cc04: str = ""
    slack_user_pm_cc05: str = ""
    slack_user_pm_cc06: str = ""

    # ── Notion ────────────────────────────────────────────────────────
    notion_token: str = ""
    notion_db_vendors: str = ""
    notion_db_pending: str = ""
    notion_db_audit: str = ""

    # ── Database ──────────────────────────────────────────────────────
    database_url: str = "postgresql+asyncpg://user:password@localhost:5432/invoice_agent"

    # ── Helpers ───────────────────────────────────────────────────────
    @property
    def is_production(self) -> bool:
        return self.app_env == "production"

    def pennylane_token_for(self, cost_center: str) -> str:
        """Return the Pennylane API token for a given cost center code."""
        mapping = {
            "CC-01": self.pennylane_token_cc01,
            "CC-02": self.pennylane_token_cc02,
            "CC-03": self.pennylane_token_cc03,
            "CC-04": self.pennylane_token_cc04,
            "CC-05": self.pennylane_token_cc05,
            "CC-06": self.pennylane_token_cc06,
            "CC-07": self.pennylane_token_cc07,
            "CC-08": self.pennylane_token_cc08,
        }
        token = mapping.get(cost_center, "")
        if not token:
            raise ValueError(f"No Pennylane token configured for {cost_center}")
        return token

    def property_manager_slack_id(self, cost_center: str) -> str | None:
        """Return the Slack user ID for a property manager, if any."""
        mapping = {
            "CC-01": self.slack_user_pm_cc01,
            "CC-02": self.slack_user_pm_cc02,
            "CC-03": self.slack_user_pm_cc03,
            "CC-04": self.slack_user_pm_cc04,
            "CC-05": self.slack_user_pm_cc05,
            "CC-06": self.slack_user_pm_cc06,
        }
        return mapping.get(cost_center) or None


# Singleton — import this everywhere
settings = Settings()
