"""Application configuration and deterministic financial quantization.

Money, wage rates, fringe rates, tax rates, and hours never use float.
Rates quantize to 0.0001 and currency/hours quantize to 0.01, both ROUND_HALF_UP.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP


FOUR_PLACES = Decimal("0.0001")
TWO_PLACES = Decimal("0.01")
ZERO = Decimal("0")
ZERO_2 = Decimal("0.00")
ZERO_4 = Decimal("0.0000")
RULE_PACK_VERSION = "US-SCLS-1.0"
PARSER_VERSION = "scls-parser-1.0.0"


def _to_decimal(val: Decimal | str | int, quant: Decimal) -> Decimal:
    if isinstance(val, bool) or isinstance(val, float):
        raise TypeError(
            "Float and boolean values are prohibited in OptionMargin financial math. Use Decimal or str."
        )
    if isinstance(val, str) and not val.strip():
        raise InvalidOperation("Missing decimal value")
    return Decimal(val).quantize(quant, rounding=ROUND_HALF_UP)


def q4(val: Decimal | str | int) -> Decimal:
    """Quantize an hourly rate, fringe rate, or tax rate to 4 decimal places."""
    return _to_decimal(val, FOUR_PLACES)


def q2(val: Decimal | str | int) -> Decimal:
    """Quantize currency or hours to 2 decimal places."""
    return _to_decimal(val, TWO_PLACES)


def money_text(val: Decimal | str | int) -> str:
    amount = q2(val)
    sign = "-" if amount < 0 else ""
    return f"{sign}${abs(amount):,.2f}"


def rate_text(val: Decimal | str | int) -> str:
    return f"${q2(val):,.2f}/hr"


@dataclass(frozen=True)
class Settings:
    app_name: str = "OptionMargin — Autonomous Contract Margin Recovery Engine"
    app_env: str = os.getenv("APP_ENV", "development")
    database_url: str = os.getenv("DATABASE_URL", "sqlite:///./option_margin.db")
    pii_hmac_secret: str = os.getenv("PII_HMAC_SECRET", "dev-only-not-a-secret")
    llm_provider: str = os.getenv("LLM_PROVIDER", "offline")
    anthropic_api_key: str = os.getenv("ANTHROPIC_API_KEY", "")
    gemini_api_key: str = os.getenv("GEMINI_API_KEY", "")
    anthropic_model: str = os.getenv("ANTHROPIC_MODEL", "claude-3-5-haiku-latest")
    gemini_model: str = os.getenv("GEMINI_MODEL", "gemini-2.0-flash")
    usaspending_live: bool = os.getenv("USASPENDING_LIVE", "false").strip().lower() in {"1", "true", "yes"}
    smtp_host: str = os.getenv("SMTP_HOST", "")
    smtp_port: str = os.getenv("SMTP_PORT", "")
    smtp_user: str = os.getenv("SMTP_USER", "")
    smtp_pass: str = os.getenv("SMTP_PASS", "")
    target_naics: str = "561720"
    primary_occupation_code: str = "23470"
    primary_occupation_title: str = "Janitor"
    default_fica_rate: Decimal = q4(os.getenv("DEFAULT_FICA_RATE", "0.0765"))
    default_futa_rate: Decimal = q4(os.getenv("DEFAULT_FUTA_RATE", "0.0000"))
    default_suta_rate: Decimal = q4(os.getenv("DEFAULT_SUTA_RATE", "0.0000"))
    default_wc_rate: Decimal = q4(os.getenv("DEFAULT_WC_RATE", "0.0000"))


settings = Settings()
