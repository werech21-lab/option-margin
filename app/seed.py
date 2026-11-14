"""Startup seed for US federal janitorial contracts, wage determinations, and cases.

observed_at is when OptionMargin captured the document. effective_at is when the
rate or modification binds. Those timestamps are never treated as the same fact.
"""

from __future__ import annotations

import hashlib
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy.orm import Session

from app.agents.agent1_hunter import Agent1Hunter
from app.agents.agent2_quant import Agent2Quant, breakdown_document
from app.agents.agent3_executor import Agent3Executor
from app.config import PARSER_VERSION, RULE_PACK_VERSION, q2
from app.models import (
    BillingMatch,
    ChangeEvent,
    Contract,
    ContractOccupationMapping,
    ContractVersion,
    DeliveryOutbox,
    EvidenceLink,
    JobRun,
    PayrollRow,
    Source,
    SourceSnapshot,
    WageRate,
    utcnow,
)
from app.services.privacy_scrubber import PrivacyScrubber
from app.services.sf30_parser import SF30Parser

TENANT_ID = "tenant-apex-janitorial"
RECIPIENT = "Apex Federal Janitorial Services LLC"


def seed_if_empty(session: Session) -> bool:
    from app.models import AdjustmentCase

    if session.query(AdjustmentCase).first() is not None:
        return False
    today = date.today()
    hunter = Agent1Hunter()
    quant = Agent2Quant()
    scrubber = PrivacyScrubber()
    now = utcnow()

    sam = Source(
        name="SAM.gov Wage Determinations",
        source_type="SAM_WD",
        base_url="https://sam.gov/wage-determinations",
        last_checked_at=now,
        health_status="OK",
        freshness_sla_hours=24,
    )
    usaspending = Source(
        name="USAspending Award Search",
        source_type="USASPENDING",
        base_url="https://api.usaspending.gov/api/v2/search/spending_by_award/",
        last_checked_at=now,
        health_status="OFFLINE_FALLBACK",
        freshness_sla_hours=24,
    )
    ecfr = Source(
        name="Electronic Code of Federal Regulations",
        source_type="ECFR",
        base_url="https://www.ecfr.gov/current/title-48/section-52.222-43",
        last_checked_at=now,
        health_status="OK",
        freshness_sla_hours=168,
    )
    session.add_all([sam, usaspending, ecfr])
    session.flush()

    arlington = _publish_wd_pair(
        session,
        hunter,
        source=sam,
        wd_id="2015-4281",
        locality="Arlington County, VA",
        old_revision=26,
        new_revision=27,
        old_rate="22.40",
        new_rate="23.40",
        old_hw="4.80",
        new_hw="4.98",
        published=datetime(2026, 9, 1, 14, 0, tzinfo=timezone.utc),
        observed=datetime(2026, 9, 3, 9, 30, tzinfo=timezone.utc),
        effective=datetime(2026, 10, 1, 0, 0, tzinfo=timezone.utc),
    )
    montgomery = _publish_wd_pair(
        session,
        hunter,
        source=sam,
        wd_id="2015-4289",
        locality="Montgomery County, MD",
        old_revision=12,
        new_revision=13,
        old_rate="22.40",
        new_rate="23.40",
        old_hw="4.70",
        new_hw="4.90",
        published=datetime(2026, 8, 15, 15, 0, tzinfo=timezone.utc),
        observed=datetime(2026, 8, 18, 11, 0, tzinfo=timezone.utc),
        effective=datetime(2026, 9, 15, 0, 0, tzinfo=timezone.utc),
    )
    fairfax = _publish_wd_pair(
        session,
        hunter,
        source=sam,
        wd_id="2015-4291",
        locality="Fairfax County, VA",
        old_revision=10,
        new_revision=11,
        old_rate="20.15",
        new_rate="21.00",
        old_hw="4.57",
        new_hw="4.57",
        published=datetime(2026, 6, 1, 13, 0, tzinfo=timezone.utc),
        observed=datetime(2026, 6, 4, 8, 15, tzinfo=timezone.utc),
        effective=datetime(2026, 7, 1, 0, 0, tzinfo=timezone.utc),
    )
    district = _publish_wd_pair(
        session,
        hunter,
        source=sam,
        wd_id="2015-4290",
        locality="District of Columbia, DC",
        old_revision=8,
        new_revision=9,
        old_rate="18.90",
        new_rate="19.90",
        old_hw="4.93",
        new_hw="5.13",
        published=datetime(2026, 9, 20, 16, 0, tzinfo=timezone.utc),
        observed=datetime(2026, 9, 22, 10, 45, tzinfo=timezone.utc),
        effective=datetime(2026, 10, 20, 0, 0, tzinfo=timezone.utc),
    )

    demo = _contract(
        tenant_id=TENANT_ID,
        contract_id="CONTRACT-DEMO",
        award_id="VA786-26-C-0170",
        title="Janitorial services, Arlington outpatient clinics",
        agency_name="Department of Veterans Affairs",
        recipient_name=RECIPIENT,
        county="Arlington",
        state="VA",
        wd_id="2015-4281",
        fica="0.0000",
        option_year=2,
        next_option=today + timedelta(days=120),
    )
    supported = _contract(
        tenant_id=TENANT_ID,
        contract_id="W912DY-24-C-0042",
        award_id="W912DY24C0042",
        title="Janitorial services, Fort Myer and Arlington National Cemetery support",
        agency_name="U.S. Army Corps of Engineers",
        recipient_name=RECIPIENT,
        county="Arlington",
        state="VA",
        wd_id="2015-4281",
        fica="0.0765",
        option_year=2,
        next_option=today + timedelta(days=200),
    )
    agreed = _contract(
        tenant_id=TENANT_ID,
        contract_id="47QSHA25C0188",
        award_id="47QSHA25C0188",
        title="Custodial services, GSA leased space, Montgomery County",
        agency_name="GSA Public Buildings Service",
        recipient_name=RECIPIENT,
        county="Montgomery",
        state="MD",
        wd_id="2015-4289",
        fica="0.0000",
        option_year=3,
        next_option=today + timedelta(days=240),
    )
    paid = _contract(
        tenant_id=TENANT_ID,
        contract_id="36C10G25C0044",
        award_id="36C10G25C0044",
        title="Evening janitorial, VA medical campus, Fairfax",
        agency_name="Department of Veterans Affairs",
        recipient_name=RECIPIENT,
        county="Fairfax",
        state="VA",
        wd_id="2015-4291",
        fica="0.0000",
        option_year=1,
        next_option=today + timedelta(days=300),
    )
    option = _contract(
        tenant_id=TENANT_ID,
        contract_id="HDEC08-25-C-0031",
        award_id="HDEC0825C0031",
        title="Facilities janitorial, Washington Aqueduct support",
        agency_name="U.S. Army Corps of Engineers",
        recipient_name=RECIPIENT,
        county="District of Columbia",
        state="DC",
        wd_id="2015-4290",
        fica="0.0000",
        option_year=1,
        next_option=today + timedelta(days=45),
    )
    session.add_all([demo, supported, agreed, paid, option])
    session.flush()

    supported_receipt = today - timedelta(days=12)
    supported_sf30 = _sf30_text(
        modification="P00004",
        contract_id=supported.contract_id,
        wd_id="2015-4281",
        revision=27,
        receipt=supported_receipt,
    )
    agreed_receipt = today - timedelta(days=50)
    agreed_sf30 = _sf30_text(
        modification="P00011",
        contract_id=agreed.contract_id,
        wd_id="2015-4289",
        revision=13,
        receipt=agreed_receipt,
    )
    paid_receipt = today - timedelta(days=70)
    paid_sf30 = _sf30_text(
        modification="P00002",
        contract_id=paid.contract_id,
        wd_id="2015-4291",
        revision=11,
        receipt=paid_receipt,
    )
    session.add_all(
        [
            _version_from_sf30(supported_sf30, supported, published=date(2026, 9, 1), effective=today - timedelta(days=10), agreed_amount=None, bilateral=False),
            _version_from_sf30(agreed_sf30, agreed, published=date(2026, 8, 15), effective=today - timedelta(days=40), agreed_amount=Decimal("115200.00"), bilateral=True),
            _version_from_sf30(paid_sf30, paid, published=date(2026, 6, 1), effective=today - timedelta(days=60), agreed_amount=Decimal("24480.00"), bilateral=True),
        ]
    )
    for contract in (demo, supported, agreed, paid, option):
        session.add(
            ContractOccupationMapping(
                tenant_id=TENANT_ID,
                contract_id=contract.contract_id,
                client_job_code="JAN-01",
                wd_occupation_code="23470",
                wd_occupation_title="Janitor",
                is_supported_scope=True,
            )
        )
    session.flush()

    period_start = today - timedelta(days=30)
    period_end = today - timedelta(days=16)
    _payroll(session, scrubber, supported.contract_id, 40, period_start, period_end, "22.40", "23.60", "4.80", "4.98")
    _payroll(session, scrubber, agreed.contract_id, 60, period_start, period_end, "22.40", "23.40", "0.00", "0.00")
    _payroll(session, scrubber, paid.contract_id, 15, period_start, period_end, "20.15", "21.00", "4.57", "4.57")

    demo_adjustment = quant.compute_adjustment(
        workers=60,
        hours_per_worker=Decimal("160"),
        actual_prev_wage=Decimal("22.40"),
        new_required_wage=Decimal("23.40"),
        actual_new_wage=Decimal("23.60"),
        hw_delta=Decimal("0.00"),
    )
    if demo_adjustment.total_monthly_entitlement_usd != Decimal("9600.00"):
        raise RuntimeError("Seed demo monthly entitlement drifted from 9600.00.")
    if demo_adjustment.annualized_exposure_usd != Decimal("115200.00"):
        raise RuntimeError("Seed demo annual exposure drifted from 115200.00.")
    demo_assessment = quant.assess_case(
        monitored=True,
        rates_changed=True,
        has_sf30=False,
        verified_receipt_date=None,
        payroll_rows_present=False,
        option_within_90_days=False,
        public_wd_increase=True,
    )
    quant.create_case_with_calculation(
        session,
        tenant_id=TENANT_ID,
        case_id="CASE-DEMO-017",
        contract_id=demo.contract_id,
        adjustment=demo_adjustment,
        breakdown=breakdown_document(
            adjustment=demo_adjustment,
            revision=27,
            actual_prev_wage="22.40",
            new_required_wage="23.40",
            actual_new_wage="23.60",
            hours_per_worker="160.00",
        ),
        status=demo_assessment.status,
        event_type=demo_assessment.event_type,
        evidence_complete=False,
        missing_fields=list(demo_assessment.missing_fields),
        next_action=demo_assessment.next_action,
        change_event_id=arlington.id,
    )
    session.add(
        EvidenceLink(
            tenant_id=TENANT_ID,
            case_id="CASE-DEMO-017",
            field_name="hourly_rate_23470",
            field_value="23.4000",
            source_type="SAM_WD",
            document_hash=arlington.document_hash,
            citation_span="23470 Janitor 23.40 H&W 4.98",
            verified_at=now,
        )
    )

    supported_adjustment = quant.compute_adjustment(
        workers=40,
        hours_per_worker=Decimal("160"),
        actual_prev_wage=Decimal("22.40"),
        new_required_wage=Decimal("23.40"),
        actual_new_wage=Decimal("23.60"),
        actual_prev_hw=Decimal("4.80"),
        new_required_hw=Decimal("4.98"),
        actual_new_hw=Decimal("4.98"),
        fica_rate=Decimal("0.0765"),
    )
    supported_deadline = supported_receipt + timedelta(days=30)
    quant.create_case_with_calculation(
        session,
        tenant_id=TENANT_ID,
        case_id="CASE-SUP-104",
        contract_id=supported.contract_id,
        adjustment=supported_adjustment,
        breakdown=breakdown_document(
            adjustment=supported_adjustment,
            revision=27,
            actual_prev_wage="22.40",
            new_required_wage="23.40",
            actual_new_wage="23.60",
            actual_prev_hw="4.80",
            new_required_hw="4.98",
            actual_new_hw="4.98",
            fica_rate="0.0765",
            hours_per_worker="160.00",
        ),
        status="SUPPORTED",
        event_type="WAGE_REVISION",
        evidence_complete=True,
        missing_fields=[],
        next_action="Prepare FAR 52.222-43 price adjustment claim package",
        verified_receipt_date=supported_receipt,
        filing_deadline_date=supported_deadline,
        change_event_id=arlington.id,
    )
    supported_parsed = SF30Parser().parse(supported_sf30)
    session.add_all(
        [
            EvidenceLink(
                tenant_id=TENANT_ID,
                case_id="CASE-SUP-104",
                field_name="hourly_rate_23470",
                field_value="23.4000",
                source_type="SAM_WD",
                document_hash=arlington.document_hash,
                citation_span="23470 Janitor 23.40 H&W 4.98",
                verified_at=now,
            ),
            EvidenceLink(
                tenant_id=TENANT_ID,
                case_id="CASE-SUP-104",
                field_name="modification_number",
                field_value=supported_parsed.modification_number or "P00004",
                source_type="SF30_MOD",
                document_hash=supported_parsed.document_hash,
                citation_span=supported_parsed.evidence_span,
                verified_at=now,
            ),
            EvidenceLink(
                tenant_id=TENANT_ID,
                case_id="CASE-SUP-104",
                field_name="eligible_hours",
                field_value="6400.00",
                source_type="PAYROLL_FEED",
                document_hash=_payroll_batch_hash(TENANT_ID, supported.contract_id),
                citation_span="40 Zero-PII worker hashes, 160.00 hours each, occupation 23470",
                verified_at=now,
            ),
        ]
    )

    agreed_adjustment = quant.compute_adjustment(
        workers=60,
        hours_per_worker=Decimal("160"),
        actual_prev_wage=Decimal("22.40"),
        new_required_wage=Decimal("23.40"),
        actual_new_wage=Decimal("23.40"),
    )
    quant.create_case_with_calculation(
        session,
        tenant_id=TENANT_ID,
        case_id="CASE-AGR-208",
        contract_id=agreed.contract_id,
        adjustment=agreed_adjustment,
        breakdown=breakdown_document(
            adjustment=agreed_adjustment,
            revision=13,
            actual_prev_wage="22.40",
            new_required_wage="23.40",
            actual_new_wage="23.40",
            hours_per_worker="160.00",
        ),
        status="AGREED",
        event_type="WAGE_REVISION",
        evidence_complete=True,
        missing_fields=[],
        next_action="Invoice the agreed rate and reconcile billed hours",
        verified_receipt_date=agreed_receipt,
        filing_deadline_date=agreed_receipt + timedelta(days=30),
        change_event_id=montgomery.id,
        agreed_adjustment_usd=Decimal("115200.00"),
    )
    session.add(
        BillingMatch(
            tenant_id=TENANT_ID,
            case_id="CASE-AGR-208",
            contract_id=agreed.contract_id,
            invoice_number="INV-2026-188",
            billing_period=f"{period_start.isoformat()}/{period_end.isoformat()}",
            expected_adjusted_rate=Decimal("23.40"),
            actual_billed_rate=Decimal("22.40"),
            hours_billed=Decimal("9600.00"),
            variance_leakage_usd=Decimal("9600.00"),
            reconciliation_status="UNDERBILLED_LEAKAGE",
            checked_at=now,
        )
    )
    agreed_case = session.query(AdjustmentCase).filter_by(case_id="CASE-AGR-208").one()
    agreed_case.unbilled_leakage_usd = Decimal("9600.00")

    paid_adjustment = quant.compute_adjustment(
        workers=15,
        hours_per_worker=Decimal("160"),
        actual_prev_wage=Decimal("20.15"),
        new_required_wage=Decimal("21.00"),
        actual_new_wage=Decimal("21.00"),
        actual_prev_hw=Decimal("4.57"),
        new_required_hw=Decimal("4.57"),
        actual_new_hw=Decimal("4.57"),
    )
    quant.create_case_with_calculation(
        session,
        tenant_id=TENANT_ID,
        case_id="CASE-PAID-014",
        contract_id=paid.contract_id,
        adjustment=paid_adjustment,
        breakdown=breakdown_document(
            adjustment=paid_adjustment,
            revision=11,
            actual_prev_wage="20.15",
            new_required_wage="21.00",
            actual_new_wage="21.00",
            actual_prev_hw="4.57",
            new_required_hw="4.57",
            actual_new_hw="4.57",
            hours_per_worker="160.00",
        ),
        status="PAID",
        event_type="WAGE_REVISION",
        evidence_complete=True,
        missing_fields=[],
        next_action="Archive the paid adjustment with the evidence dossier",
        verified_receipt_date=paid_receipt,
        filing_deadline_date=paid_receipt + timedelta(days=30),
        change_event_id=fairfax.id,
        agreed_adjustment_usd=paid_adjustment.annualized_exposure_usd,
        billed_collected_usd=paid_adjustment.annualized_exposure_usd,
    )
    session.add(
        BillingMatch(
            tenant_id=TENANT_ID,
            case_id="CASE-PAID-014",
            contract_id=paid.contract_id,
            invoice_number="INV-2026-044",
            billing_period=f"{period_start.isoformat()}/{period_end.isoformat()}",
            expected_adjusted_rate=Decimal("21.0000"),
            actual_billed_rate=Decimal("21.0000"),
            hours_billed=Decimal("2400.00"),
            variance_leakage_usd=Decimal("0.00"),
            reconciliation_status="MATCHED",
            checked_at=now,
        )
    )

    option_adjustment = quant.compute_adjustment(
        workers=25,
        hours_per_worker=Decimal("160"),
        actual_prev_wage=Decimal("18.90"),
        new_required_wage=Decimal("19.90"),
        actual_new_wage=Decimal("19.90"),
    )
    option_assessment = quant.assess_case(
        monitored=True,
        rates_changed=True,
        has_sf30=False,
        verified_receipt_date=None,
        option_within_90_days=True,
        public_wd_increase=True,
    )
    quant.create_case_with_calculation(
        session,
        tenant_id=TENANT_ID,
        case_id="CASE-OPT-090",
        contract_id=option.contract_id,
        adjustment=option_adjustment,
        breakdown=breakdown_document(
            adjustment=option_adjustment,
            revision=9,
            actual_prev_wage="18.90",
            new_required_wage="19.90",
            actual_new_wage="19.90",
            hours_per_worker="160.00",
        ),
        status=option_assessment.status,
        event_type=option_assessment.event_type,
        evidence_complete=False,
        missing_fields=list(option_assessment.missing_fields),
        next_action=option_assessment.next_action,
        change_event_id=district.id,
    )

    executor = Agent3Executor()
    notice_key = executor.idempotency_key(
        tenant_id=TENANT_ID,
        contract_id=supported.contract_id,
        wd_id="2015-4281",
        revision=27,
        event_type="WAGE_REVISION",
    )
    session.add(
        DeliveryOutbox(
            tenant_id=TENANT_ID,
            case_id="CASE-SUP-104",
            idempotency_key=notice_key,
            channel="INTERNAL_TASK",
            recipient="contracts-desk",
            payload_json={
                "tenant_id": TENANT_ID,
                "contract_id": supported.contract_id,
                "wd_id": "2015-4281",
                "revision": 27,
                "event_type": "WAGE_REVISION",
                "case_id": "CASE-SUP-104",
            },
            status="SENT",
            retry_count=0,
            created_at=now,
        )
    )
    session.add(
        JobRun(
            job_type="seed_hunter_quant_executor",
            status="COMPLETED",
            worker_id="worker-local-1",
            lease_until=now + timedelta(minutes=15),
            started_at=now,
            finished_at=now,
            metrics_json={
                "cases": 5,
                "rule_pack_version": RULE_PACK_VERSION,
                "demo_monthly": "9600.00",
                "demo_annual": "115200.00",
                "ignore_events": 4,
            },
        )
    )
    session.commit()
    return True


def _publish_wd_pair(
    session: Session,
    hunter: Agent1Hunter,
    *,
    source: Source,
    wd_id: str,
    locality: str,
    old_revision: int,
    new_revision: int,
    old_rate: str,
    new_rate: str,
    old_hw: str,
    new_hw: str,
    published: datetime,
    observed: datetime,
    effective: datetime,
) -> ChangeEvent:
    old_html = _wd_html(wd_id, old_revision, locality, old_rate, old_hw, "2026-01-04T08:00:00Z", "SAM.gov | Sign In")
    cosmetic_html = _wd_html(wd_id, old_revision, locality, old_rate, old_hw, "2026-05-01T12:00:00Z", "Home | Menu | Search | Logout")
    new_html = _wd_html(wd_id, new_revision, locality, new_rate, new_hw, "2026-09-01T14:00:00Z", "SAM.gov | Wage Determinations")
    source_url = f"https://sam.gov/wage-determinations/{wd_id}"
    cosmetic = hunter.classify(old_html, cosmetic_html, monitored=True, source_url=source_url)
    if cosmetic.gate_decision != "IGNORE":
        raise RuntimeError(f"Cosmetic WD diff for {wd_id} was {cosmetic.gate_decision}, expected IGNORE.")
    hunter.record_change_event(
        session,
        cosmetic,
        source_published_at=published - timedelta(days=30),
        observed_at=observed - timedelta(days=20),
    )
    analyzed = hunter.classify(old_html, new_html, monitored=True, source_url=source_url)
    if analyzed.gate_decision != "ANALYZE":
        raise RuntimeError(f"Rate change for {wd_id} was {analyzed.gate_decision}, expected ANALYZE.")
    event = hunter.record_change_event(
        session,
        analyzed,
        source_published_at=published,
        observed_at=observed,
    )
    for revision, raw, html_rate, html_hw, published_at, effective_at in (
        (old_revision, old_html, old_rate, old_hw, published - timedelta(days=200), effective - timedelta(days=180)),
        (new_revision, new_html, new_rate, new_hw, published, effective),
    ):
        parsed = hunter.parse_document(raw)
        session.add(
            SourceSnapshot(
                source_id=source.id,
                wd_id=wd_id,
                revision=revision,
                source_url=source_url,
                source_published_at=published_at,
                observed_at=observed if revision == new_revision else observed - timedelta(days=200),
                document_hash=parsed.document_hash,
                normalized_content_json={
                    "locality": parsed.locality,
                    "rows": [
                        {
                            "occupation_code": row.occupation_code,
                            "occupation_title": row.occupation_title,
                            "hourly_rate": f"{row.hourly_rate:.4f}",
                            "hw_rate": f"{row.hw_rate:.4f}",
                        }
                        for row in parsed.rows
                    ],
                },
                parser_version=PARSER_VERSION,
            )
        )
        session.add(
            WageRate(
                wd_id=wd_id,
                revision=revision,
                occupation_code="23470",
                occupation_title="Janitor",
                locality=locality,
                hourly_rate=Decimal(html_rate),
                hw_rate=Decimal(html_hw),
                source_published_at=published_at,
                effective_at=effective_at,
                evidence_span=f"23470 Janitor {html_rate} H&W {html_hw}",
            )
        )
    if observed == published or effective == published:
        raise RuntimeError("observed_at, source_published_at, and effective_at must stay distinct.")
    return event


def _wd_html(wd_id: str, revision: int, locality: str, rate: str, hw: str, stamp: str, nav: str) -> str:
    return (
        "<html><body>"
        f"<nav>{nav}</nav>"
        f"<div>Last updated: {stamp}</div>"
        f"<h1>Wage Determination {wd_id} Revision {revision}</h1>"
        f"<p>Locality: {locality}</p>"
        f"<p>23470 Janitor {rate} H&amp;W {hw}</p>"
        "</body></html>"
    )


def _contract(
    *,
    tenant_id: str,
    contract_id: str,
    award_id: str,
    title: str,
    agency_name: str,
    recipient_name: str,
    county: str,
    state: str,
    wd_id: str,
    fica: str,
    option_year: int,
    next_option: date,
) -> Contract:
    return Contract(
        tenant_id=tenant_id,
        contract_id=contract_id,
        award_id=award_id,
        title=title,
        agency_name=agency_name,
        naics_code="561720",
        recipient_name=recipient_name,
        place_of_performance_county=county,
        place_of_performance_state=state,
        mapped_wd_id=wd_id,
        far_clause_version="FAR 52.222-43",
        is_cba=False,
        fica_rate=Decimal(fica),
        futa_rate=Decimal("0.0000"),
        suta_rate=Decimal("0.0000"),
        wc_rate=Decimal("0.0000"),
        current_option_year=option_year,
        next_option_date=next_option,
        created_at=utcnow(),
    )


def _sf30_text(*, modification: str, contract_id: str, wd_id: str, revision: int, receipt: date) -> str:
    return (
        "STANDARD FORM 30\n"
        f"Modification Number: {modification}\n"
        f"Contract {contract_id}\n"
        f"This modification incorporates WD {wd_id} Revision {revision} pursuant to FAR 52.222-43.\n"
        f"Verified receipt date: {receipt.isoformat()}\n"
    )


def _version_from_sf30(
    text: str,
    contract: Contract,
    *,
    published: date,
    effective: date,
    agreed_amount: Decimal | None,
    bilateral: bool,
) -> ContractVersion:
    parsed = SF30Parser().parse(text)
    if not parsed.modification_number or not parsed.far_52_222_43_applicable:
        raise RuntimeError("SF-30 seed document did not parse.")
    if parsed.verified_receipt_date is None:
        raise RuntimeError("SF-30 seed document is missing a verified receipt date.")
    return ContractVersion(
        tenant_id=contract.tenant_id,
        contract_id=contract.contract_id,
        modification_number=parsed.modification_number,
        sf30_document_hash=parsed.document_hash,
        incorporated_wd_id=parsed.incorporated_wd_id,
        incorporated_wd_revision=parsed.incorporated_wd_revision,
        published_date=published,
        verified_receipt_date=parsed.verified_receipt_date,
        effective_at=effective,
        is_bilateral_agreed=bilateral,
        agreed_adjustment_amount=agreed_amount,
        evidence_span=parsed.evidence_span,
    )


def _payroll(
    session: Session,
    scrubber: PrivacyScrubber,
    contract_id: str,
    workers: int,
    period_start: date,
    period_end: date,
    prev_wage: str,
    new_wage: str,
    prev_hw: str,
    new_hw: str,
) -> None:
    for index in range(workers):
        session.add(
            PayrollRow(
                tenant_id=TENANT_ID,
                contract_id=contract_id,
                worker_hash=scrubber.worker_hash(TENANT_ID, f"{contract_id}-worker-{index:03d}"),
                occupation_code="23470",
                pay_period_start=period_start,
                pay_period_end=period_end,
                eligible_hours=Decimal("160.00"),
                actual_prev_wage=Decimal(prev_wage),
                actual_new_wage=Decimal(new_wage),
                actual_prev_hw=Decimal(prev_hw),
                actual_new_hw=Decimal(new_hw),
                ingested_at=utcnow(),
            )
        )


def _payroll_batch_hash(tenant_id: str, contract_id: str) -> str:
    return hashlib.sha256(f"{tenant_id}:{contract_id}:payroll-feed".encode("utf-8")).hexdigest()


def scheduled_hunter_summary() -> dict[str, object]:
    """Offline prospect pass used by the scheduled workflow. No mail is sent."""
    cards = Agent1Hunter().prospect_audit()
    return {
        "prospects": len(cards),
        "illustrative_sensitivity_per_10000_hours": f"{q2(cards[0].illustrative_080_sensitivity_usd):.2f}" if cards else "0.00",
        "legal_entitlement_claimed": False,
        "rule_pack_version": RULE_PACK_VERSION,
    }
