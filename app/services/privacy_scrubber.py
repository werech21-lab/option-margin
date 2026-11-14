"""Zero-PII payroll scrubber.

Names, SSNs, emails, phone numbers, and street addresses are hashed in memory
and never returned. The stored identifier is a SHA-256 worker_hash.
"""

from __future__ import annotations

import csv
import hashlib
import io
import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from app.config import q2, q4, settings
from app.schemas import ScrubbedPayrollRow

PII_COLUMNS = {
    "employee_name",
    "employee",
    "name",
    "full_name",
    "first_name",
    "last_name",
    "worker_name",
    "ssn",
    "social_security",
    "social_security_number",
    "ssn_last4",
    "tax_id",
    "email",
    "phone",
    "phone_number",
    "home_address",
    "street_address",
    "address",
    "dob",
    "date_of_birth",
    "bank_account",
    "routing_number",
}

SSN_REGEX = re.compile(r"\b\d{3}-?\d{2}-?\d{4}\b")
EMAIL_REGEX = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
PHONE_REGEX = re.compile(r"\b(?:\+1[\s.-]?)?\(?\d{3}\)?[\s.-]\d{3}[\s.-]\d{4}\b")


class PrivacyScrubber:
    """Convert a raw payroll CSV into rows that contain no direct identifiers."""

    def __init__(self, secret_salt: str | None = None) -> None:
        self.secret_salt = secret_salt if secret_salt is not None else settings.pii_hmac_secret

    def worker_hash(self, tenant_id: str, raw_identity: str) -> str:
        normalized = re.sub(r"[^A-Za-z0-9]", "", raw_identity.strip().upper())
        material = f"{tenant_id}:{normalized}:{self.secret_salt}".encode("utf-8")
        return hashlib.sha256(material).hexdigest()

    def scrub_csv(self, csv_text: str, tenant_id: str) -> tuple[list[ScrubbedPayrollRow], int, str]:
        if not csv_text.strip():
            raise ValueError("Payroll CSV is empty.")
        reader = csv.DictReader(io.StringIO(csv_text))
        if not reader.fieldnames:
            raise ValueError("Payroll CSV needs a header row.")
        stripped = 0
        rows: list[ScrubbedPayrollRow] = []
        canonical_lines: list[str] = []
        for index, raw in enumerate(reader, start=1):
            lowered = {(key or "").strip().lower(): (value or "").strip() for key, value in raw.items()}
            identity_parts: list[str] = []
            for column in list(lowered):
                if column in PII_COLUMNS:
                    identity_parts.append(lowered[column])
                    stripped += 1
                    del lowered[column]
            if not identity_parts:
                identity_parts.append(f"ROW-{index}")
            worker_hash = self.worker_hash(tenant_id, "|".join(identity_parts))
            job_code = lowered.get("job_code") or lowered.get("client_job_code") or lowered.get("internal_job_code") or "JAN-01"
            occupation = lowered.get("occupation_code") or lowered.get("wd_occupation_code") or "23470"
            hours = _decimal_field(lowered, ("hours", "eligible_hours", "regular_hours"), "0.00", q2)
            prev_wage = _decimal_field(lowered, ("prev_wage", "actual_prev_wage", "previous_rate"), "0.0000", q4)
            new_wage = _decimal_field(lowered, ("new_wage", "actual_new_wage", "actual_rate"), "0.0000", q4)
            prev_hw = _decimal_field(lowered, ("prev_hw", "actual_prev_hw"), "0.0000", q4)
            new_hw = _decimal_field(lowered, ("new_hw", "actual_new_hw"), "0.0000", q4)
            start = _date_field(lowered.get("pay_period_start") or lowered.get("period_start"))
            end = _date_field(lowered.get("pay_period_end") or lowered.get("period_end"))
            row = ScrubbedPayrollRow(
                worker_hash=worker_hash,
                occupation_code=_scrub_free_text(occupation),
                client_job_code=_scrub_free_text(job_code),
                eligible_hours=hours,
                actual_prev_wage=prev_wage,
                actual_new_wage=new_wage,
                actual_prev_hw=prev_hw,
                actual_new_hw=new_hw,
                pay_period_start=start,
                pay_period_end=end,
            )
            serialized = row.model_dump_json()
            if SSN_REGEX.search(serialized) or EMAIL_REGEX.search(serialized):
                raise RuntimeError("Scrubber failed closed: an identifier survived serialization.")
            rows.append(row)
            canonical_lines.append(serialized)
        batch_hash = hashlib.sha256("\n".join(canonical_lines).encode("utf-8")).hexdigest()
        return rows, stripped, batch_hash


def _decimal_field(row: dict[str, str], keys: tuple[str, ...], default: str, quantizer) -> Decimal:
    raw = default
    for key in keys:
        if row.get(key):
            raw = row[key].replace("$", "").replace(",", "")
            break
    try:
        return quantizer(raw)
    except (InvalidOperation, TypeError) as exc:
        raise ValueError(f"Payroll column {keys[0]} is not a decimal: {raw}") from exc


def _date_field(raw: str | None) -> date | None:
    if not raw:
        return None
    cleaned = raw.strip()
    for fmt in ("%Y-%m-%d", "%m/%d/%Y"):
        try:
            return datetime.strptime(cleaned, fmt).date()
        except ValueError:
            continue
    raise ValueError(f"Payroll date {cleaned} is not YYYY-MM-DD.")


def _scrub_free_text(value: str) -> str:
    cleaned = SSN_REGEX.sub("", value)
    cleaned = EMAIL_REGEX.sub("", cleaned)
    cleaned = PHONE_REGEX.sub("", cleaned)
    return re.sub(r"\s+", " ", cleaned).strip() or "23470"
