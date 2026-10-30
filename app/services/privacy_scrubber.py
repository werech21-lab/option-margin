"""Zero-PII Payroll Ingestion Service.

Strips all direct employee identifiers (names, SSNs, emails, phone numbers, home addresses)
in memory before database persistence and replaces them with a deterministic HMAC-SHA256
`worker_hash` (`WRK-...`).
"""

import hashlib
import hmac
import re
from decimal import Decimal
from typing import Any
from app.config import settings, q4
from app.schemas import ScrubbedPayrollLine

PII_FIELD_NAMES = {
    "employee_name",
    "full_name",
    "first_name",
    "last_name",
    "ssn",
    "social_security_number",
    "tax_id",
    "email",
    "phone",
    "phone_number",
    "home_address",
    "street_address",
    "dob",
    "date_of_birth",
    "bank_account",
    "routing_number",
}

SSN_REGEX = re.compile(r"\b\d{3}-?\d{2}-?\d{4}\b")
EMAIL_REGEX = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")


class PrivacyScrubber:
    """Deterministic Zero-PII scrubber for contractor payroll registers."""

    def __init__(self, secret_salt: str | None = None) -> None:
        self.secret_salt = (secret_salt or settings.pii_hmac_secret).encode("utf-8")

    def generate_worker_hash(self, raw_identifier: str, org_id: str) -> str:
        """Create a deterministic, collision-resistant anonymous worker token."""
        normalized = re.sub(r"[^A-Za-z0-9]", "", raw_identifier.strip().upper())
        msg = f"{org_id}:{normalized}".encode("utf-8")
        digest = hmac.new(self.secret_salt, msg, hashlib.sha256).hexdigest()[:16].upper()
        return f"WRK-{digest}"

    def scrub_payroll_rows(
        self,
        raw_rows: list[dict[str, Any]],
        org_id: str,
        occupation_map: dict[str, str] | None = None,
    ) -> tuple[list[ScrubbedPayrollLine], int, str]:
        """Scrub raw payroll dictionaries into Zero-PII ScrubbedPayrollLine objects.

        Returns:
            (scrubbed_lines, total_pii_fields_stripped, batch_sha256_hash)
        """
        occupation_map = occupation_map or {}
        scrubbed_lines: list[ScrubbedPayrollLine] = []
        pii_stripped_count = 0

        for row in raw_rows:
            raw_id_parts: list[str] = []
            for key in list(row.keys()):
                lower_k = key.lower()
                if lower_k in PII_FIELD_NAMES:
                    val_str = str(row[key] or "")
                    if lower_k in ("ssn", "social_security_number", "employee_id", "employee_name", "full_name"):
                        raw_id_parts.append(val_str)
                    pii_stripped_count += 1

            raw_identity_seed = "|".join(raw_id_parts) if raw_id_parts else str(row.get("worker_id", "ANON"))
            worker_hash = self.generate_worker_hash(raw_identity_seed, org_id)

            internal_code = str(row.get("internal_job_code", "JAN-01")).strip()
            # Ensure no accidental SSN or email leaked into job code
            internal_code = SSN_REGEX.sub("[REDACTED]", internal_code)
            internal_code = EMAIL_REGEX.sub("[REDACTED]", internal_code)

            mapped_scls = row.get("scls_occupation_code") or occupation_map.get(internal_code)

            line = ScrubbedPayrollLine(
                worker_hash=worker_hash,
                internal_job_code=internal_code,
                scls_occupation_code=mapped_scls,
                regular_hours=q4(str(row.get("regular_hours", "0.0000"))),
                overtime_hours=q4(str(row.get("overtime_hours", "0.0000"))),
                vacation_holiday_hours=q4(str(row.get("vacation_holiday_hours", "0.0000"))),
                actual_prev_wage_rate=q4(str(row.get("actual_prev_wage_rate", "0.0000"))),
                actual_new_wage_rate=q4(str(row.get("actual_new_wage_rate", "0.0000"))),
                actual_prev_hw_rate=q4(str(row.get("actual_prev_hw_rate", "0.0000"))),
                actual_new_hw_rate=q4(str(row.get("actual_new_hw_rate", "0.0000"))),
            )
            scrubbed_lines.append(line)

        canonical_payload = "|".join(
            f"{item.worker_hash}:{item.scls_occupation_code}:{item.regular_hours}:{item.actual_prev_wage_rate}:{item.actual_new_wage_rate}"
            for item in sorted(scrubbed_lines, key=lambda x: x.worker_hash)
        )
        batch_hash = hashlib.sha256(canonical_payload.encode("utf-8")).hexdigest()
        return scrubbed_lines, pii_stripped_count, batch_hash
