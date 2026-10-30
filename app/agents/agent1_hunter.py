"""Agent 1: Hunter — Public WD Scraper, Dual SHA-256 Hashing, Semantic WD Diff, and USAspending Sniper."""

import hashlib
import re
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from app.config import q4


@dataclass(frozen=True)
class ParsedWageDetermination:
    wd_number: str
    revision_number: int
    locality_state: str
    locality_county: str
    source_published_at: date
    raw_content_hash: str
    semantic_rate_hash: str
    hw_rate_standard: Decimal
    hw_rate_eo13706: Decimal
    occupation_rates: dict[str, Decimal]
    occupation_titles: dict[str, str]
    raw_text: str


@dataclass(frozen=True)
class WDDiffResult:
    wd_number: str
    old_revision: int
    new_revision: int
    raw_hash_changed: bool
    semantic_hash_changed: bool
    is_formatting_only: bool
    occupation_deltas: dict[str, Decimal]
    hw_standard_delta: Decimal
    hw_eo13706_delta: Decimal


@dataclass(frozen=True)
class USAspendingTarget:
    piid: str
    recipient_name: str
    recipient_uei: str
    agency_name: str
    naics_code: str
    pop_state: str
    pop_county: str
    wd_number: str
    next_option_start_date: date
    days_until_option: int
    in_pre_option_window: bool


OCC_LINE_RE = re.compile(r"^\s*(\d{5})\s*-\s*([A-Za-z0-9 ,/()&-]+?)\s+(\d+\.\d{2,4})\s*$", re.MULTILINE)
HW_STD_RE = re.compile(r"HEALTH\s*&\s*WELFARE\s*:\s*\$?(\d+\.\d{2,4})", re.IGNORECASE)
HW_EO_RE = re.compile(r"EO\s*13706\s*:\s*\$?(\d+\.\d{2,4})", re.IGNORECASE)


class Agent1Hunter:
    """Monitors public SAM.gov Wage Determinations and USAspending NAICS 561720 awards."""

    def parse_wd_document(
        self,
        raw_text: str,
        wd_number: str,
        revision_number: int,
        locality_state: str,
        locality_county: str,
        source_published_at: date,
    ) -> ParsedWageDetermination:
        raw_hash = hashlib.sha256(raw_text.encode("utf-8")).hexdigest()

        occ_rates: dict[str, Decimal] = {}
        occ_titles: dict[str, str] = {}
        for match in OCC_LINE_RE.finditer(raw_text):
            code = match.group(1).strip()
            title = " ".join(match.group(2).split())
            rate = q4(match.group(3))
            occ_rates[code] = rate
            occ_titles[code] = title

        hw_std_match = HW_STD_RE.search(raw_text)
        hw_eo_match = HW_EO_RE.search(raw_text)
        hw_std = q4(hw_std_match.group(1)) if hw_std_match else q4("4.9800")
        hw_eo = q4(hw_eo_match.group(1)) if hw_eo_match else q4("4.5700")

        # Build canonical semantic string strictly from rates (immune to HTML/whitespace formatting noise)
        sorted_rates_str = "|".join(f"{k}:{occ_rates[k]}" for k in sorted(occ_rates.keys()))
        semantic_payload = f"WD:{wd_number}|HW_STD:{hw_std}|HW_EO:{hw_eo}|OCC:{sorted_rates_str}"
        semantic_hash = hashlib.sha256(semantic_payload.encode("utf-8")).hexdigest()

        return ParsedWageDetermination(
            wd_number=wd_number,
            revision_number=revision_number,
            locality_state=locality_state,
            locality_county=locality_county,
            source_published_at=source_published_at,
            raw_content_hash=raw_hash,
            semantic_rate_hash=semantic_hash,
            hw_rate_standard=hw_std,
            hw_rate_eo13706=hw_eo,
            occupation_rates=occ_rates,
            occupation_titles=occ_titles,
            raw_text=raw_text,
        )

    def diff_wage_determinations(
        self,
        old_wd: ParsedWageDetermination,
        new_wd: ParsedWageDetermination,
        monitored_occupations: set[str] | None = None,
    ) -> WDDiffResult:
        raw_changed = old_wd.raw_content_hash != new_wd.raw_content_hash
        sem_changed = old_wd.semantic_rate_hash != new_wd.semantic_rate_hash

        codes = monitored_occupations or (set(old_wd.occupation_rates.keys()) | set(new_wd.occupation_rates.keys()))
        deltas: dict[str, Decimal] = {}
        for code in sorted(codes):
            if code in old_wd.occupation_rates and code in new_wd.occupation_rates:
                deltas[code] = q4(new_wd.occupation_rates[code] - old_wd.occupation_rates[code])

        hw_std_delta = q4(new_wd.hw_rate_standard - old_wd.hw_rate_standard)
        hw_eo_delta = q4(new_wd.hw_rate_eo13706 - old_wd.hw_rate_eo13706)

        all_zero = all(d == Decimal("0.0000") for d in deltas.values()) and hw_std_delta == Decimal("0.0000") and hw_eo_delta == Decimal("0.0000")
        is_formatting_only = raw_changed and (not sem_changed or all_zero)

        return WDDiffResult(
            wd_number=new_wd.wd_number,
            old_revision=old_wd.revision_number,
            new_revision=new_wd.revision_number,
            raw_hash_changed=raw_changed,
            semantic_hash_changed=sem_changed,
            is_formatting_only=is_formatting_only,
            occupation_deltas=deltas,
            hw_standard_delta=hw_std_delta,
            hw_eo13706_delta=hw_eo_delta,
        )

    def scan_usaspending_pre_option_targets(
        self,
        awards: list[dict],
        as_of_date: date,
    ) -> list[USAspendingTarget]:
        """Filter NAICS 561720 contracts and flag those within 60-90 days of Option Exercise."""
        results: list[USAspendingTarget] = []
        for award in awards:
            if str(award.get("naics_code")) != "561720":
                continue
            opt_date: date = award["next_option_start_date"]
            days_until = (opt_date - as_of_date).days
            in_window = 60 <= days_until <= 90
            results.append(
                USAspendingTarget(
                    piid=award["piid"],
                    recipient_name=award["recipient_name"],
                    recipient_uei=award["recipient_uei"],
                    agency_name=award["agency_name"],
                    naics_code="561720",
                    pop_state=award["pop_state"],
                    pop_county=award["pop_county"],
                    wd_number=award["wd_number"],
                    next_option_start_date=opt_date,
                    days_until_option=days_until,
                    in_pre_option_window=in_window,
                )
            )
        return results
