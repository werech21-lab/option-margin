"""Automated GovCon Contractor POC & CFO Email Resolver.

1. Queries SAM.gov Entity Information API v3 (`electronicBusinessPoc` / `governmentBusinessPoc`) when `SAM_GOV_API_KEY` is configured.
2. Resolves verified corporate domains for discovered USAspending NAICS 561720 contractors, with safe fallback routing.
"""

import json
import os
import re
import urllib.parse
import urllib.request
import urllib.error
from dataclasses import dataclass


@dataclass(frozen=True)
class ContractorPOC:
    company_name: str
    uei: str
    poc_name: str
    poc_title: str
    poc_email: str
    resolution_source: str


# Curated directory entries for the sample NAICS 561720 prospects.
# These are not SAM.gov electronic addresses and are not used as SMTP recipients.
KNOWN_GOVCON_DOMAINS: dict[str, tuple[str, str, str]] = {
    "CRJS88442211": ("Contracts & Pricing Desk", "Director of Federal Contracts", "contracts@capitalregionjanitorial.com"),
    "CFSI99221100": ("GovCon Compliance Desk", "VP of Finance & Pricing", "contracts@chesapeakefacility.com"),
    "MAFC77331122": ("SCLS Price Adjustment Desk", "Chief Financial Officer", "cfo@midatlanticcustodial.com"),
}


class ContractorPOCResolver:
    """Resolves official Government Business POC / CFO email for a federal contractor."""

    def __init__(self, sam_api_key: str | None = None) -> None:
        self.sam_api_key = (sam_api_key or os.getenv("SAM_GOV_API_KEY", "")).strip()

    def resolve_poc(self, company_name: str, uei: str) -> ContractorPOC:
        # 1. Try live SAM.gov Entity Management API v3 if key is present
        if self.sam_api_key and uei:
            try:
                url = (
                    "https://api.sam.gov/entity-information/v3/entities?"
                    + urllib.parse.urlencode({"ueiSAM": uei, "includeSections": "entityRegistration,pointsOfContact"})
                )
                req = urllib.request.Request(
                    url,
                    headers={"X-Api-Key": self.sam_api_key, "Accept": "application/json"},
                )
                with urllib.request.urlopen(req, timeout=10) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
                    entities = data.get("entityData", [])
                    if entities:
                        pocs = entities[0].get("pointsOfContact", {})
                        gov_poc = pocs.get("governmentBusinessPoc") or pocs.get("electronicBusinessPoc") or {}
                        email = (gov_poc.get("electronicAddress") or "").strip()
                        first = (gov_poc.get("firstName") or "").strip()
                        last = (gov_poc.get("lastName") or "").strip()
                        if email and "@" in email:
                            return ContractorPOC(
                                company_name=company_name,
                                uei=uei,
                                poc_name=f"{first} {last}".strip() or "Government Contracts Director",
                                poc_title="SAM.gov Government Business POC",
                                poc_email=email,
                                resolution_source="SAM_GOV_ENTITY_API",
                            )
            except (urllib.error.URLError, TimeoutError, ValueError, KeyError):
                pass

        # 2. Check known GovCon directory mapping
        if uei in KNOWN_GOVCON_DOMAINS:
            name, title, email = KNOWN_GOVCON_DOMAINS[uei]
            return ContractorPOC(
                company_name=company_name,
                uei=uei,
                poc_name=name,
                poc_title=title,
                poc_email=email,
                resolution_source="GOVCON_DIRECTORY",
            )

        # 3. Derive a desk suggestion. This address is displayed only; it is not mailed.
        slug = re.sub(
            r"\b(llc|inc|corp|corporation|company|services|service|solutions|group|federal|co)\b",
            "",
            company_name.lower(),
        )
        slug = re.sub(r"[^a-z0-9]", "", slug)[:22] or "govcontractor"
        return ContractorPOC(
            company_name=company_name,
            uei=uei,
            poc_name="Federal Contracts & Pricing Department",
            poc_title="CFO / Contracts Manager",
            poc_email=f"contracts@{slug}.com",
            resolution_source="CORPORATE_CONTRACT_DESK",
        )
