from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    odds_api_key: str = ""
    odds_region: str = "us"
    odds_format: str = "american"
    database_url: str = "sqlite:///./data/edgeiq.db"
    watch_ev_threshold: float = 0.0
    bet_ev_threshold: float = 0.05
    paper_bankroll: float = 1000.0
    default_unit: float = 5.0
    max_single_recommendation: float = 10.0
    max_weekly_exposure: float = 50.0
    max_player_exposure: float = 15.0
    max_event_exposure: float = 20.0
    min_watch_confidence: float = 0.50
    min_bet_confidence: float = 0.70
    fresh_data_seconds: int = 900
    stale_data_seconds: int = 3600
    confidence_data_quality_weight: float = 0.25
    confidence_sample_size_weight: float = 0.20
    confidence_role_stability_weight: float = 0.15
    confidence_injury_certainty_weight: float = 0.15
    confidence_matchup_certainty_weight: float = 0.10
    confidence_market_stability_weight: float = 0.15
    ingestion_enabled: bool = False
    ingestion_poll_interval_minutes: int = 15
    provider_timeout_seconds: float = 30.0
    provider_retry_count: int = 2
    ingestion_stale_event_hours: int = 6
    enabled_providers: str = "mock"

    @property
    def enabled_provider_keys(self) -> list[str]:
        return [key.strip() for key in self.enabled_providers.split(",") if key.strip()]

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()
