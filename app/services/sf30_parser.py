"""Deterministic SF-30 parser.

Instruction-like lines inside a contract document are removed before any field
is read. A model suggestion cannot replace a value the deterministic parser
already extracted, and it cannot introduce a value that is not a literal
substring of the sanitized text.
"""

from __future__ import annotations

import hashlib
import re
from datetime import date, datetime

from app.schemas import ParsedSF30
from app.services.llm_adapter import suggest_sf30_fields

INJECTION_LINE = re.compile(
    r"(?i)("
    r"ignore\s+(all\s+|any\s+)?(previous|prior|above)\s+instructions"
    r"|you\s+are\s+now"
    r"|system\s+prompt"
    r"|disregard\s+(the\s+)?(above|prior|previous)"
    r"|new\s+instructions"
    r"|<\s*\|\s*"
    r"|\bact\s+as\b"
    r"|do\s+not\s+follow\s+the\s+contract"
    r"|override\s+the\s+(wage|modification|receipt)"
    r"|^\s*assistant\s*:"
    r"|^\s*developer\s*:"
    r"|^\s*system\s*:"
    r")"
)
MOD_RE = re.compile(r"\b(P\d{5})\b")
WD_RE = re.compile(
    r"WD[-\s]*(?P<wd>\d{4}-\d{4}).{0,48}?Rev(?:ision)?\.?\s*(?P<rev>\d+)",
    re.IGNORECASE | re.DOTALL,
)
RECEIPT_RE = re.compile(
    r"verified[\s_-]*receipt[\s_-]*date\s*[:\-]?\s*(?P<day>\d{4}-\d{2}-\d{2})",
    re.IGNORECASE,
)
FAR_RE = re.compile(r"52\.222-43")


class SF30Parser:
    """Read modification number, incorporated WD, receipt date, and clause applicability."""

    def parse(self, sf30_text: str) -> ParsedSF30:
        document_hash = hashlib.sha256(sf30_text.encode("utf-8")).hexdigest()
        sanitized, removed = sanitize_contract_text(sf30_text)
        modification_number = _first(MOD_RE, sanitized)
        wd_match = WD_RE.search(sanitized)
        incorporated_wd_id = wd_match.group("wd") if wd_match else None
        incorporated_wd_revision = int(wd_match.group("rev")) if wd_match else None
        receipt_match = RECEIPT_RE.search(sanitized)
        verified_receipt_date = _parse_iso(receipt_match.group("day")) if receipt_match else None
        applicable = bool(FAR_RE.search(sanitized))
        span = _evidence_span(sanitized, modification_number, incorporated_wd_id)
        deterministic = ParsedSF30(
            modification_number=modification_number,
            incorporated_wd_id=incorporated_wd_id,
            incorporated_wd_revision=incorporated_wd_revision,
            verified_receipt_date=verified_receipt_date,
            far_52_222_43_applicable=applicable,
            document_hash=document_hash,
            sanitized=removed > 0,
            evidence_span=span,
            injection_lines_removed=removed,
        )
        suggestion = suggest_sf30_fields(sanitized)
        if suggestion is None:
            return deterministic
        return _merge_fail_closed(deterministic, suggestion, sanitized)


def sanitize_contract_text(text: str) -> tuple[str, int]:
    kept: list[str] = []
    removed = 0
    for line in text.splitlines():
        if INJECTION_LINE.search(line):
            removed += 1
            continue
        kept.append(line)
    return "\n".join(kept), removed


def _merge_fail_closed(deterministic: ParsedSF30, suggestion: dict, sanitized: str) -> ParsedSF30:
    modification_number = deterministic.modification_number or _literal(suggestion.get("modification_number"), sanitized)
    incorporated_wd_id = deterministic.incorporated_wd_id or _literal(suggestion.get("incorporated_wd_id"), sanitized)
    revision = deterministic.incorporated_wd_revision
    if revision is None:
        suggested_rev = suggestion.get("incorporated_wd_revision")
        if suggested_rev is not None and str(suggested_rev) in sanitized:
            try:
                revision = int(suggested_rev)
            except (TypeError, ValueError):
                revision = None
    receipt = deterministic.verified_receipt_date
    if receipt is None:
        suggested_day = suggestion.get("verified_receipt_date")
        if isinstance(suggested_day, str) and suggested_day in sanitized:
            receipt = _parse_iso(suggested_day)
    applicable = deterministic.far_52_222_43_applicable or ("52.222-43" in sanitized and bool(suggestion.get("far_52_222_43_applicable")))
    return deterministic.model_copy(
        update={
            "modification_number": modification_number,
            "incorporated_wd_id": incorporated_wd_id,
            "incorporated_wd_revision": revision,
            "verified_receipt_date": receipt,
            "far_52_222_43_applicable": applicable,
        }
    )


def _literal(value: object, sanitized: str) -> str | None:
    if not isinstance(value, str):
        return None
    cleaned = value.strip()
    if cleaned and cleaned in sanitized:
        return cleaned
    return None


def _first(pattern: re.Pattern[str], text: str) -> str | None:
    match = pattern.search(text)
    if not match:
        return None
    return match.group(1)


def _parse_iso(raw: str) -> date | None:
    try:
        return datetime.strptime(raw, "%Y-%m-%d").date()
    except ValueError:
        return None


def _evidence_span(text: str, modification_number: str | None, wd_id: str | None) -> str:
    needle = modification_number or wd_id or "52.222-43"
    index = text.find(needle) if needle else -1
    if index < 0:
        return text[:180].strip()
    start = max(0, index - 40)
    end = min(len(text), index + 120)
    return text[start:end].strip()
