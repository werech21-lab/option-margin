"""Agent 1 — Deep Hunter.

Strips volatile navigation, timestamps, and whitespace before comparing wage
rows. The SHA-256 is always of the original document. Identical parsed rates
are IGNORE even when the raw hash changed. A real rate change on a WD that is
not tied to a monitored contract is ARCHIVE. A real rate change on a monitored
WD is ANALYZE and becomes a change event.
"""

from __future__ import annotations

import hashlib
import html
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal

import httpx

from app.config import PARSER_VERSION, ZERO_4, q4, settings
from app.models import ChangeEvent
from app.schemas import ProspectCard
from app.services.sample_generator import illustrative_eighty_cent_sensitivity, sensitivity_per_10000_hours

NAV_BLOCK = re.compile(r"(?is)<(script|style|nav|header|footer)\b[^>]*>.*?</\1>")
TAG = re.compile(r"(?is)<[^>]+>")
COMMENT = re.compile(r"(?is)<!--.*?-->")
TIMESTAMP = re.compile(r"\b\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:\.\d+)?Z?\b")
STAMP_LABEL = re.compile(r"(?i)\b(?:last\s+updated|generated|retrieved|printed|timestamp|observed\s+at)\b\s*:?")
WD_RE = re.compile(r"\b(\d{4}-\d{4})\b")
REV_RE = re.compile(r"\bRev(?:ision)?\.?\s+(\d+)\b", re.IGNORECASE)
LOC_RE = re.compile(r"Locality:\s*([A-Za-z][A-Za-z .'\-]+?,\s*[A-Z]{2})\b")
OCC_RE = re.compile(
    r"\b(?P<code>\d{5})\b\s+(?P<title>[A-Za-z][A-Za-z /&-]{1,60}?)\s+\$?(?P<rate>\d+\.\d{2,4})\b"
)
HW_RE = re.compile(r"H\s*&\s*W(?:\s+rate)?\s*:?\s*\$?(?P<rate>\d+\.\d{2,4})", re.IGNORECASE)

USASPENDING_URL = "https://api.usaspending.gov/api/v2/search/spending_by_award/"

AREA_WAGE_DIRECTORY: dict[tuple[str, str], dict[str, object]] = {
    ("VA", "ARLINGTON"): {
        "wd_id": "2015-4281",
        "revision": 27,
        "hourly_delta": Decimal("1.00"),
    },
    ("MD", "MONTGOMERY"): {
        "wd_id": "2015-4289",
        "revision": 13,
        "hourly_delta": Decimal("1.00"),
    },
    ("DC", "DISTRICT OF COLUMBIA"): {
        "wd_id": "2015-4290",
        "revision": 9,
        "hourly_delta": Decimal("1.00"),
    },
    ("VA", "FAIRFAX"): {
        "wd_id": "2015-4291",
        "revision": 11,
        "hourly_delta": Decimal("0.85"),
    },
}

OFFLINE_AWARDS: list[dict[str, str]] = [
    {
        "recipient_name": "Potomac Facilities Services LLC",
        "award_id": "W912DY24C0108",
        "agency_name": "U.S. Army Corps of Engineers",
        "county": "Arlington",
        "state": "VA",
    },
    {
        "recipient_name": "Chesapeake Building Care Inc",
        "award_id": "47QSHA25C0188",
        "agency_name": "GSA Public Buildings Service",
        "county": "Montgomery",
        "state": "MD",
    },
    {
        "recipient_name": "Capitol Court Janitorial Cooperative",
        "award_id": "HDEC0825C0031",
        "agency_name": "U.S. Army Corps of Engineers",
        "county": "District of Columbia",
        "state": "DC",
    },
    {
        "recipient_name": "Fairfax Night Shift Services LLC",
        "award_id": "36C10G25C0044",
        "agency_name": "Department of Veterans Affairs",
        "county": "Fairfax",
        "state": "VA",
    },
]


@dataclass
class OccupationRow:
    occupation_code: str
    occupation_title: str
    hourly_rate: Decimal
    hw_rate: Decimal
    locality: str
    evidence_span: str


@dataclass
class ParsedDocument:
    raw_text: str
    normalized_text: str
    document_hash: str
    wd_id: str | None
    revision: int | None
    locality: str
    rows: list[OccupationRow] = field(default_factory=list)


@dataclass
class ChangeClassification:
    gate_decision: str
    document_hash: str
    previous_hash: str
    raw_hash_changed: bool
    rates_identical: bool
    wd_id: str | None
    previous_revision: int | None
    current_revision: int | None
    locality: str
    changed_fields: list[dict[str, str]]
    evidence_locations: list[dict[str, str]]
    current_rows: list[OccupationRow]
    source_url: str


class Agent1Hunter:
    """Compare wage determinations and build the prospect list."""

    def strip_volatile(self, raw: str) -> str:
        text = COMMENT.sub(" ", raw)
        text = NAV_BLOCK.sub(" ", text)
        text = TAG.sub(" ", text)
        text = html.unescape(text)
        text = STAMP_LABEL.sub(" ", text)
        text = TIMESTAMP.sub(" ", text)
        return re.sub(r"\s+", " ", text).strip()

    def document_hash(self, raw: str) -> str:
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def parse_document(self, raw: str) -> ParsedDocument:
        normalized = self.strip_volatile(raw)
        wd_match = WD_RE.search(normalized)
        rev_match = REV_RE.search(normalized)
        loc_match = LOC_RE.search(normalized)
        locality = loc_match.group(1).strip() if loc_match else "UNSPECIFIED"
        hw_match = HW_RE.search(normalized)
        hw_rate = q4(hw_match.group("rate")) if hw_match else ZERO_4
        rows: list[OccupationRow] = []
        for match in OCC_RE.finditer(normalized):
            start = max(0, match.start() - 12)
            end = min(len(normalized), match.end() + 24)
            rows.append(
                OccupationRow(
                    occupation_code=match.group("code"),
                    occupation_title=re.sub(r"\s+", " ", match.group("title")).strip(),
                    hourly_rate=q4(match.group("rate")),
                    hw_rate=hw_rate,
                    locality=locality,
                    evidence_span=normalized[start:end].strip(),
                )
            )
        return ParsedDocument(
            raw_text=raw,
            normalized_text=normalized,
            document_hash=self.document_hash(raw),
            wd_id=wd_match.group(1) if wd_match else None,
            revision=int(rev_match.group(1)) if rev_match else None,
            locality=locality,
            rows=rows,
        )

    def classify(self, previous_raw: str, current_raw: str, *, monitored: bool, source_url: str) -> ChangeClassification:
        previous = self.parse_document(previous_raw)
        current = self.parse_document(current_raw)
        raw_hash_changed = previous.document_hash != current.document_hash
        rates_identical = _rate_map(previous) == _rate_map(current)
        if rates_identical:
            gate = "IGNORE"
        elif not monitored:
            gate = "ARCHIVE"
        else:
            gate = "ANALYZE"
        changed = _changed_fields(previous, current)
        locations = [
            {
                "occupation_code": row.occupation_code,
                "citation_span": row.evidence_span,
                "document_hash": current.document_hash,
            }
            for row in current.rows
        ]
        return ChangeClassification(
            gate_decision=gate,
            document_hash=current.document_hash,
            previous_hash=previous.document_hash,
            raw_hash_changed=raw_hash_changed,
            rates_identical=rates_identical,
            wd_id=current.wd_id or previous.wd_id,
            previous_revision=previous.revision,
            current_revision=current.revision,
            locality=current.locality,
            changed_fields=changed,
            evidence_locations=locations,
            current_rows=current.rows,
            source_url=source_url,
        )

    def record_change_event(
        self,
        session,
        classification: ChangeClassification,
        *,
        source_published_at: datetime | None = None,
        observed_at: datetime | None = None,
    ) -> ChangeEvent:
        """Persist the gate. IGNORE and ARCHIVE do not open an adjustment case."""
        event = ChangeEvent(
            wd_id=classification.wd_id or "UNPARSED",
            previous_revision=classification.previous_revision,
            current_revision=classification.current_revision,
            source_url=classification.source_url,
            source_published_at=source_published_at,
            observed_at=observed_at or datetime.now(timezone.utc),
            document_hash=classification.document_hash,
            changed_fields_json=classification.changed_fields,
            evidence_locations_json=classification.evidence_locations,
            parser_version=PARSER_VERSION,
            gate_decision=classification.gate_decision,
        )
        session.add(event)
        session.flush()
        return event

    def prospect_audit(self, *, naics_code: str = "561720") -> list[ProspectCard]:
        live_rows = _fetch_usaspending(naics_code) if settings.usaspending_live else []
        awards = live_rows or [dict(row) for row in OFFLINE_AWARDS]
        source = "usaspending" if live_rows else "offline-deterministic"
        cards: list[ProspectCard] = []
        for award in awards:
            state = (award.get("state") or "").upper()
            county = (award.get("county") or "").upper()
            directory = AREA_WAGE_DIRECTORY.get((state, county))
            hourly_delta = q4(directory["hourly_delta"]) if directory else q4("0.80")
            cards.append(
                ProspectCard(
                    recipient_name=award.get("recipient_name") or "Unknown recipient",
                    award_id=award.get("award_id") or "UNKNOWN",
                    agency_name=award.get("agency_name") or "Unknown agency",
                    naics_code=naics_code,
                    county=award.get("county") or "",
                    state=award.get("state") or "",
                    wd_id=str(directory["wd_id"]) if directory else None,
                    wd_revision=int(directory["revision"]) if directory else None,
                    hourly_delta=hourly_delta,
                    sensitivity_per_10000_hours_usd=sensitivity_per_10000_hours(hourly_delta),
                    illustrative_080_sensitivity_usd=illustrative_eighty_cent_sensitivity(),
                    legal_entitlement_claimed=False,
                    source=source,
                )
            )
        return cards


def _rate_map(document: ParsedDocument) -> dict[tuple[str, str, str], tuple[Decimal, Decimal]]:
    wd_id = document.wd_id or ""
    return {
        (wd_id, row.occupation_code, row.locality): (row.hourly_rate, row.hw_rate)
        for row in document.rows
    }


def _changed_fields(previous: ParsedDocument, current: ParsedDocument) -> list[dict[str, str]]:
    before = _rate_map(previous)
    after = _rate_map(current)
    changes: list[dict[str, str]] = []
    for key in sorted(set(before) | set(after)):
        old_wage, old_hw = before.get(key, (None, None))
        new_wage, new_hw = after.get(key, (None, None))
        wd_id, code, locality = key
        if old_wage != new_wage:
            changes.append(
                {
                    "wd_id": wd_id,
                    "occupation_code": code,
                    "locality": locality,
                    "field": "hourly_rate",
                    "previous": "" if old_wage is None else f"{old_wage:.4f}",
                    "current": "" if new_wage is None else f"{new_wage:.4f}",
                }
            )
        if old_hw != new_hw:
            changes.append(
                {
                    "wd_id": wd_id,
                    "occupation_code": code,
                    "locality": locality,
                    "field": "hw_rate",
                    "previous": "" if old_hw is None else f"{old_hw:.4f}",
                    "current": "" if new_hw is None else f"{new_hw:.4f}",
                }
            )
    return changes


def _fetch_usaspending(naics_code: str) -> list[dict[str, str]]:
    try:
        response = httpx.post(
            USASPENDING_URL,
            json={
                "filters": {
                    "naics_codes": {"require": [naics_code]},
                    "time_period": [{"start_date": "2024-10-01", "end_date": "2026-09-30"}],
                    "award_type_codes": ["A", "B", "C", "D"],
                },
                "fields": [
                    "Award ID",
                    "Recipient Name",
                    "Awarding Agency",
                    "Place of Performance State Code",
                    "Place of Performance County",
                ],
                "limit": 10,
                "page": 1,
                "sort": "Award Amount",
                "order": "desc",
            },
            timeout=5.0,
        )
        response.raise_for_status()
        payload = response.json()
    except (httpx.HTTPError, ValueError, TypeError):
        return []
    results = payload.get("results") if isinstance(payload, dict) else None
    if not isinstance(results, list):
        return []
    normalized: list[dict[str, str]] = []
    for row in results:
        if not isinstance(row, dict):
            continue
        county = str(row.get("Place of Performance County") or row.get("pop_county_name") or "")
        state = str(row.get("Place of Performance State Code") or row.get("pop_state_code") or "")
        normalized.append(
            {
                "recipient_name": str(row.get("Recipient Name") or row.get("recipient_name") or ""),
                "award_id": str(row.get("Award ID") or row.get("Award ID") or ""),
                "agency_name": str(row.get("Awarding Agency") or row.get("awarding_agency") or ""),
                "county": county,
                "state": state,
            }
        )
    return [row for row in normalized if row["award_id"]]
