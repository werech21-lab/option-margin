"""Specialized Parser for Standard Form 30 (SF-30) Contract Modifications.

Extracts Modification Number, Modification Type (Option Exercise vs. Admin Change),
FAR 52.217-9 / FAR 52.222-43 applicability, Incorporated WD Number & Revision,
Effective Date, Verified Receipt Date, and computes the 30-Calendar-Day Notification Deadline.
"""

import hashlib
import re
from dataclasses import dataclass
from datetime import date, timedelta
from app.schemas import EvidenceSpanSchema


@dataclass(frozen=True)
class ParsedSF30Modification:
    mod_number: str
    mod_type: str
    incorporated_wd_number: str | None
    incorporated_wd_revision: int | None
    effective_date: date
    verified_receipt_date: date
    notification_deadline_date: date
    written_extension_date: date | None
    exercises_option: bool
    cites_far_52_222_43: bool
    document_hash: str
    evidence_spans: list[EvidenceSpanSchema]


MOD_NUMBER_RE = re.compile(r"\b(P\d{5}|A\d{5})\b")
WD_REF_RE = re.compile(r"WD\s*(?:No\.?|Number)?\s*(\d{4}-\d{4})\s*(?:Rev(?:ision)?\.?\s*(\d+))?", re.IGNORECASE)
OPTION_RE = re.compile(r"(exercise\s+option|option\s+period|52\.217-9)", re.IGNORECASE)
FAR_43_RE = re.compile(r"52\.222-43", re.IGNORECASE)


class SF30Parser:
    """Deterministic parser for Standard Form 30 (Amendment of Solicitation / Modification of Contract)."""

    def parse(
        self,
        sf30_text: str,
        effective_date: date,
        verified_receipt_date: date,
        written_extension_date: date | None = None,
        explicit_mod_number: str | None = None,
    ) -> ParsedSF30Modification:
        doc_hash = hashlib.sha256(sf30_text.encode("utf-8")).hexdigest()
        spans: list[EvidenceSpanSchema] = []

        mod_match = MOD_NUMBER_RE.search(sf30_text)
        mod_number = explicit_mod_number or (mod_match.group(1) if mod_match else "P00001")

        wd_match = WD_REF_RE.search(sf30_text)
        inc_wd_number: str | None = None
        inc_wd_rev: int | None = None
        if wd_match:
            inc_wd_number = wd_match.group(1)
            inc_wd_rev = int(wd_match.group(2)) if wd_match.group(2) else None
            spans.append(
                EvidenceSpanSchema(
                    source_doc_type="SF30_MOD",
                    source_doc_identifier=f"SF30-{mod_number}",
                    extracted_field_name="incorporated_wage_determination",
                    extracted_value=f"{inc_wd_number} Rev {inc_wd_rev}" if inc_wd_rev is not None else inc_wd_number,
                    page_number=1,
                    char_start=wd_match.start(),
                    char_end=wd_match.end(),
                    verbatim_quote=sf30_text[max(0, wd_match.start() - 25) : min(len(sf30_text), wd_match.end() + 35)].strip(),
                )
            )

        exercises_option = bool(OPTION_RE.search(sf30_text))
        cites_far_43 = bool(FAR_43_RE.search(sf30_text))

        if exercises_option:
            opt_match = OPTION_RE.search(sf30_text)
            if opt_match:
                spans.append(
                    EvidenceSpanSchema(
                        source_doc_type="SF30_MOD",
                        source_doc_identifier=f"SF30-{mod_number}",
                        extracted_field_name="option_exercise_authority",
                        extracted_value="OPTION_EXERCISE",
                        page_number=1,
                        char_start=opt_match.start(),
                        char_end=opt_match.end(),
                        verbatim_quote=sf30_text[max(0, opt_match.start() - 20) : min(len(sf30_text), opt_match.end() + 40)].strip(),
                    )
                )

        if exercises_option:
            mod_type = "OPTION_EXERCISE"
        elif inc_wd_number:
            mod_type = "WD_INCORPORATION"
        else:
            mod_type = "ADMIN_CHANGE"

        # FAR 52.222-43(f): Contractor shall notify the Contracting Officer within 30 days
        # after receipt of the wage determination modification, unless extended in writing.
        deadline = verified_receipt_date + timedelta(days=30)

        return ParsedSF30Modification(
            mod_number=mod_number,
            mod_type=mod_type,
            incorporated_wd_number=inc_wd_number,
            incorporated_wd_revision=inc_wd_rev,
            effective_date=effective_date,
            verified_receipt_date=verified_receipt_date,
            notification_deadline_date=deadline,
            written_extension_date=written_extension_date,
            exercises_option=exercises_option,
            cites_far_52_222_43=cites_far_43,
            document_hash=doc_hash,
            evidence_spans=spans,
        )
