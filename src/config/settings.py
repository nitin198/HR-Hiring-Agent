"""Application settings and configuration."""

from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # Ollama Configuration
    ollama_base_url: str = Field(default="http://localhost:11434", description="Ollama API base URL")
    ollama_model: str = Field(default="kimi-k2.5:cloud", description="Ollama model to use")
    ollama_timeout: int = Field(default=300, description="Ollama request timeout in seconds")
    ollama_use_chat: bool = Field(default=False, description="Use ChatOllama client when available")

    # API Configuration
    api_host: str = Field(default="0.0.0.0", description="API host")
    api_port: int = Field(default=8000, description="API port")
    api_reload: bool = Field(default=True, description="Enable API auto-reload")
    api_base_url: str = Field(default="", description="Base URL for UI API calls")

    # Database
    database_url: str = Field(default="sqlite+aiosqlite:///./hiring_agent.db", description="Database connection URL")

    # Outlook / Microsoft Graph
    outlook_enabled: bool = Field(default=False, description="Enable Outlook ingestion")
    outlook_auth_mode: Literal["client_credentials", "device_code"] = Field(
        default="client_credentials",
        description="Outlook auth mode: client_credentials or device_code",
    )
    outlook_tenant_id: str | None = Field(default=None, description="Azure AD tenant ID")
    outlook_client_id: str | None = Field(default=None, description="Azure AD client ID")
    outlook_client_secret: str | None = Field(default=None, description="Azure AD client secret")
    outlook_user_id: str = Field(default="me", description="Mailbox user ID or email")
    outlook_sender_filter: str = Field(
        default="saki.nitin1985@gmail.com",
        description="Sender email filter for Outlook ingestion",
    )
    outlook_max_messages: int = Field(default=25, description="Max Outlook messages to scan per sync")
    outlook_attachment_dir: str = Field(default="data/outlook_resumes", description="Where to store Outlook resumes")
    outlook_allowed_extensions_csv: str = Field(
        default=".pdf,.doc,.docx",
        description="Allowed attachment extensions (comma-separated)",
    )
    outlook_device_scopes_csv: str = Field(
        default="https://graph.microsoft.com/Mail.ReadWrite",
        description="Delegated scopes for device code (comma-separated)",
    )

    # Outlook IMAP
    outlook_imap_enabled: bool = Field(default=False, description="Enable Outlook IMAP ingestion")
    outlook_imap_host: str | None = Field(default=None, description="IMAP host for Outlook")
    outlook_imap_port: int = Field(default=993, description="IMAP port")
    outlook_imap_user: str | None = Field(default=None, description="IMAP username")
    outlook_imap_password: str | None = Field(default=None, description="IMAP password or app password")
    outlook_imap_folder: str = Field(default="INBOX", description="IMAP folder to scan")
    outlook_imap_use_ssl: bool = Field(default=True, description="Use SSL for IMAP")

    # Gmail IMAP
    gmail_enabled: bool = Field(default=False, description="Enable Gmail IMAP ingestion")
    gmail_imap_host: str = Field(default="imap.gmail.com", description="IMAP host for Gmail")
    gmail_imap_port: int = Field(default=993, description="IMAP port for Gmail")
    gmail_imap_user: str | None = Field(default=None, description="Gmail username")
    gmail_imap_password: str | None = Field(default=None, description="Gmail app password")
    gmail_imap_folder: str = Field(default="INBOX", description="IMAP folder to scan")
    gmail_imap_use_ssl: bool = Field(default=True, description="Use SSL for Gmail IMAP")
    gmail_sender_filter: str = Field(
        default="tanvir.k@idsil.com",
        description="Sender email filter for Gmail ingestion",
    )
    gmail_max_messages: int = Field(default=50, description="Max unread Gmail messages to scan per sync")
    gmail_sync_interval_minutes: int = Field(
        default=60,
        description="Automatic Gmail sync interval in minutes",
    )
    gmail_allowed_extensions_csv: str = Field(
        default=".pdf,.doc,.docx,.txt",
        description="Allowed Gmail attachment extensions (comma-separated)",
    )

    @property
    def outlook_allowed_extensions(self) -> set[str]:
        """Return allowed Outlook attachment extensions."""
        return {ext.strip().lower() for ext in self.outlook_allowed_extensions_csv.split(",") if ext.strip()}

    @property
    def outlook_device_scopes(self) -> list[str]:
        """Return delegated scopes for device code auth."""
        return [scope.strip() for scope in self.outlook_device_scopes_csv.split(",") if scope.strip()]

    @property
    def gmail_allowed_extensions(self) -> set[str]:
        """Return allowed Gmail attachment extensions."""
        return {
            ext.strip().lower()
            for ext in self.gmail_allowed_extensions_csv.split(",")
            if ext.strip()
        }

    # Scoring Weights (must sum to 100)
    weight_skill_match: int = Field(default=40, description="Weight for skill matching")
    weight_experience: int = Field(default=25, description="Weight for experience matching")
    weight_domain_knowledge: int = Field(default=15, description="Weight for domain knowledge")
    weight_project_complexity: int = Field(default=10, description="Weight for project complexity")
    weight_soft_skills: int = Field(default=10, description="Weight for soft skills")

    # Decision Thresholds
    threshold_strong_hire: int = Field(default=80, description="Score threshold for strong hire")
    threshold_borderline: int = Field(default=60, description="Score threshold for borderline")
    threshold_reject: int = Field(default=60, description="Score threshold for reject")

    # Audio Interview (TTS/STT)
    tts_engine: str = Field(default="piper", description="TTS engine (piper)")
    tts_piper_bin: str = Field(default="piper", description="Path to Piper TTS binary")
    tts_piper_voice: str = Field(default="data/models/tts/en_US-lessac-medium.onnx", description="Piper voice model path")
    tts_sample_rate: int = Field(default=22050, description="TTS output sample rate")

    stt_engine: str = Field(default="faster-whisper", description="STT engine (faster-whisper)")
    stt_model_size: str = Field(default="small", description="Whisper model size")
    stt_device: str = Field(default="cpu", description="STT device (cpu)")
    stt_compute_type: str = Field(default="int8", description="STT compute type (int8/float32)")

    @property
    def scoring_weights(self) -> dict[str, int]:
        """Return scoring weights as a dictionary."""
        return {
            "skill_match": self.weight_skill_match,
            "experience": self.weight_experience,
            "domain_knowledge": self.weight_domain_knowledge,
            "project_complexity": self.weight_project_complexity,
            "soft_skills": self.weight_soft_skills,
        }

    @property
    def decision_thresholds(self) -> dict[str, int]:
        """Return decision thresholds as a dictionary."""
        return {
            "strong_hire": self.threshold_strong_hire,
            "borderline": self.threshold_borderline,
            "reject": self.threshold_reject,
        }

    def validate_weights(self) -> None:
        """Validate that scoring weights sum to 100."""
        total = (
            self.weight_skill_match
            + self.weight_experience
            + self.weight_domain_knowledge
            + self.weight_project_complexity
            + self.weight_soft_skills
        )
        if total != 100:
            raise ValueError(f"Scoring weights must sum to 100, got {total}")


@lru_cache
def get_settings() -> Settings:
    """Get cached settings instance."""
    settings = Settings()
    settings.validate_weights()
    return settings


# Re-export for convenience
settings = get_settings()
