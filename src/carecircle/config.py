"""Environment-only deployment configuration."""
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    bedrock_model_id: str = Field(min_length=1, pattern=r"\S")
    aws_region: str = Field(min_length=1, pattern=r"\S")
    supervisor_timeout_seconds: float = Field(default=60, gt=0, le=300)
    log_level: str = "INFO"
    care_profiles_table: str | None = None
    care_events_table: str | None = None
    action_ledger_table: str | None = None
    caregiver_alert_topic_arn: str | None = None
    follow_up_lambda_arn: str | None = None
    follow_up_scheduler_role_arn: str | None = None
    demo_mode: bool = True
