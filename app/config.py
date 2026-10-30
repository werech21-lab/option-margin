"""Application configuration and deterministic financial constants."""

import os
from decimal import Decimal, ROUND_HALF_UP
from dataclasses import dataclass


FOUR_PLACES = Decimal("0.0001")
TWO_PLACES = Decimal("0.01")
ZERO_2D = Decimal("0.00")
ZERO_4D = Decimal("0.0000")


def q4(val: Decimal | str | int) -> Decimal:
    """Quantize to 4 decimal places (hourly rates & hours) using ROUND_HALF_UP."""
    if isinstance(val, float):
        raise TypeError("Float values are strictly prohibited in OptionMargin financial math. Use Decimal or str.")
    return Decimal(str(val)).quantize(FOUR_PLACES, rounding=ROUND_HALF_UP)


def q2(val: Decimal | str | int) -> Decimal:
    """Quantize to 2 decimal places (currency totals) using ROUND_HALF_UP."""
    if isinstance(val, float):
        raise TypeError("Float values are strictly prohibited in OptionMargin financial math. Use Decimal or str.")
    return Decimal(str(val)).quantize(TWO_PLACES, rounding=ROUND_HALF_UP)


@dataclass(frozen=True)
class Settings:
    app_name: str = "OptionMargin — Autonomous Contract Margin Recovery Engine"
    app_env: str = os.getenv("APP_ENV", "development")
    database_url: str = os.getenv("DATABASE_URL", "sqlite:///./option_margin.db")
    pii_hmac_secret: str = os.getenv("PII_HMAC_SECRET", "option-margin-zero-pii-institutional-salt-2026")
    llm_provider: str = os.getenv("LLM_PROVIDER", "mock")
    anthropic_api_key: str = os.getenv("ANTHROPIC_API_KEY", "")
    gemini_api_key: str = os.getenv("GEMINI_API_KEY", "")
    default_fica_rate: Decimal = q4(os.getenv("DEFAULT_FICA_RATE", "0.0765"))
    default_futa_rate: Decimal = q4(os.getenv("DEFAULT_FUTA_RATE", "0.0060"))
    default_suta_rate: Decimal = q4(os.getenv("DEFAULT_SUTA_RATE", "0.0210"))
    default_workers_comp_rate: Decimal = q4(os.getenv("DEFAULT_WORKERS_COMP_RATE", "0.0315"))
    target_naics: str = "561720"
    primary_occupation_code: str = "23470"
    primary_occupation_title: str = "Janitor"


settings = Settings()
