"""FastAPI Entrypoint, HTMX Views, and REST API Endpoints for OptionMargin."""

import pathlib
from datetime import date
from decimal import Decimal
from fastapi import FastAPI, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from typing import Any
from app.config import q2, q4, settings
from app.database import get_db, init_db, SessionLocal
from app.models import (
    AdjustmentCase,
    CalculationLedgerEntry,
    Contract,
    ContractModification,
    EvidenceSpan,
    Organization,
    WageDetermination,
    WDOccupationRate,
)
from app.schemas import CalculatorRequest, ScrubbedPayrollLine, StatutoryTaxConfig
from app.agents.agent1_hunter import Agent1Hunter
from app.agents.agent2_quant import Agent2Quant
from app.agents.agent3_executor import Agent3Executor
from app.services.privacy_scrubber import PrivacyScrubber
from app.services.sf30_parser import SF30Parser
from app.services.sample_generator import SampleGenerator
from app.services.stripe_billing import StripeBillingService

app = FastAPI(
    title=settings.app_name,
    version="1.0.0",
    description="Autonomous SCLS / FAR 52.222-43 Contract Margin Recovery Engine",
)

TEMPLATES_DIR = pathlib.Path(__file__).parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


def seed_demo_data(db: Any) -> None:
    """Seed a deterministic NAICS 561720 demo organization and case if database is empty."""
    if db.query(Organization).first() is not None:
        return

    org = Organization(
        name="Apex Federal Janitorial Services LLC",
        uei="J8K2L9M4N5P6",
        cage_code="9A7B2",
        primary_naics="561720",
    )
    db.add(org)
    db.flush()

    hunter = Agent1Hunter()
    old_wd_parsed = hunter.parse_wd_document(
        raw_text="WD 2015-4281 Rev 26\n23470 - Janitor 16.50\nHEALTH & WELFARE: $4.98\nEO 13706: $4.57\n",
        wd_number="2015-4281",
        revision_number=26,
        locality_state="VA",
        locality_county="Arlington",
        source_published_at=date(2025, 6, 15),
    )
    new_wd_parsed = hunter.parse_wd_document(
        raw_text="WD 2015-4281 Rev 27\n23470 - Janitor 18.20\nHEALTH & WELFARE: $5.36\nEO 13706: $4.98\n",
        wd_number="2015-4281",
        revision_number=27,
        locality_state="VA",
        locality_county="Arlington",
        source_published_at=date(2026, 9, 15),
    )

    old_wd = WageDetermination(
        wd_number=old_wd_parsed.wd_number,
        revision_number=old_wd_parsed.revision_number,
        locality_state=old_wd_parsed.locality_state,
        locality_county=old_wd_parsed.locality_county,
        source_published_at=old_wd_parsed.source_published_at,
        raw_content_hash=old_wd_parsed.raw_content_hash,
        semantic_rate_hash=old_wd_parsed.semantic_rate_hash,
        hw_rate_standard=old_wd_parsed.hw_rate_standard,
        hw_rate_eo13706=old_wd_parsed.hw_rate_eo13706,
        source_url="https://sam.gov/wage-determinations/2015-4281/26",
    )
    new_wd = WageDetermination(
        wd_number=new_wd_parsed.wd_number,
        revision_number=new_wd_parsed.revision_number,
        locality_state=new_wd_parsed.locality_state,
        locality_county=new_wd_parsed.locality_county,
        source_published_at=new_wd_parsed.source_published_at,
        raw_content_hash=new_wd_parsed.raw_content_hash,
        semantic_rate_hash=new_wd_parsed.semantic_rate_hash,
        hw_rate_standard=new_wd_parsed.hw_rate_standard,
        hw_rate_eo13706=new_wd_parsed.hw_rate_eo13706,
        source_url="https://sam.gov/wage-determinations/2015-4281/27",
    )
    db.add_all([old_wd, new_wd])
    db.flush()

    db.add_all([
        WDOccupationRate(wd_id=old_wd.id, occupation_code="23470", occupation_title="Janitor", hourly_rate=Decimal("16.5000")),
        WDOccupationRate(wd_id=new_wd.id, occupation_code="23470", occupation_title="Janitor", hourly_rate=Decimal("18.2000")),
    ])

    contract = Contract(
        org_id=org.id,
        piid="47PM0924C0012",
        agency_name="General Services Administration (GSA PBS Region 11)",
        naics_code="561720",
        psc_code="S201",
        pop_state="VA",
        pop_county="Arlington",
        wd_number="2015-4281",
        active_wd_id=new_wd.id,
        current_option_year=2,
        next_option_start_date=date(2027, 10, 1),
    )
    db.add(contract)
    db.flush()

    sf30_parser = SF30Parser()
    sf30_parsed = sf30_parser.parse(
        sf30_text="MODIFICATION P00004: Pursuant to FAR 52.217-9 and FAR 52.222-43, the Government hereby exercises Option Period 2 and incorporates WD 2015-4281 Rev 27.",
        effective_date=date(2026, 10, 1),
        verified_receipt_date=date(2026, 10, 10),
        explicit_mod_number="P00004",
    )

    mod = ContractModification(
        org_id=org.id,
        contract_id=contract.id,
        mod_number=sf30_parsed.mod_number,
        mod_type=sf30_parsed.mod_type,
        incorporated_wd_id=new_wd.id,
        effective_date=sf30_parsed.effective_date,
        verified_receipt_date=sf30_parsed.verified_receipt_date,
        notification_deadline_date=sf30_parsed.notification_deadline_date,
        sf30_block14_text="Exercise Option Period 2 and incorporate WD 2015-4281 Rev 27.",
        document_hash=sf30_parsed.document_hash,
    )
    db.add(mod)
    db.flush()

    scrubber = PrivacyScrubber()
    scrubbed_lines, _, _ = scrubber.scrub_payroll_rows(
        raw_rows=[
            {
                "employee_name": "Marcus Vance",
                "ssn": "123-45-6789",
                "internal_job_code": "JAN-1",
                "scls_occupation_code": "23470",
                "regular_hours": "2080.0000",
                "overtime_hours": "0.0000",
                "vacation_holiday_hours": "0.0000",
                "actual_prev_wage_rate": "16.5000",
                "actual_new_wage_rate": "19.0000",
                "actual_prev_hw_rate": "4.5700",
                "actual_new_hw_rate": "4.9800",
            }
        ],
        org_id=org.id,
    )

    diff = hunter.diff_wage_determinations(old_wd_parsed, new_wd_parsed)
    quant = Agent2Quant()
    eval_res = quant.evaluate_case(
        contract_wd_number="2015-4281",
        contract_next_option_date=contract.next_option_start_date,
        is_eo13706_applicable=True,
        has_complex_cba=False,
        old_wd=old_wd_parsed,
        new_wd=new_wd_parsed,
        wd_diff=diff,
        sf30_mod=sf30_parsed,
        payroll_lines=scrubbed_lines,
        tax_config=StatutoryTaxConfig(),
        evaluation_date=date(2026, 10, 30),
    )

    adj_case = AdjustmentCase(
        org_id=org.id,
        contract_id=contract.id,
        modification_id=mod.id,
        old_wd_id=old_wd.id,
        new_wd_id=new_wd.id,
        state_gate=eval_res.state_gate.value,
        lifecycle_status=eval_res.lifecycle_status.value,
        is_pre_option_alert=eval_res.is_pre_option_alert,
        days_until_option=eval_res.days_until_option,
        days_remaining_30d_clock=eval_res.days_remaining_30d_clock,
        is_late_notice_flagged=eval_res.is_late_notice_flagged,
        total_eligible_hours=eval_res.total_eligible_hours,
        total_eligible_wage_delta=eval_res.total_eligible_wage_delta,
        total_eligible_hw_delta=eval_res.total_eligible_hw_delta,
        total_accompanying_taxes_wc=eval_res.total_accompanying_taxes_wc,
        voluntary_raise_excluded_amount=eval_res.voluntary_raise_excluded_amount,
        total_claim_amount=eval_res.total_claim_amount,
        gate_reason=eval_res.gate_reason,
    )
    db.add(adj_case)
    db.flush()

    for l_row in eval_res.ledger_lines:
        db.add(
            CalculationLedgerEntry(
                org_id=org.id,
                case_id=adj_case.id,
                scls_occupation_code=l_row.scls_occupation_code,
                worker_hash=l_row.worker_hash,
                eligible_wage_hours=l_row.eligible_wage_hours,
                eligible_hw_hours=l_row.eligible_hw_hours,
                overtime_hours_excluded_from_hw=l_row.overtime_hours_excluded_from_hw,
                w_prev=l_row.w_prev,
                w_req_new=l_row.w_req_new,
                w_act_new=l_row.w_act_new,
                eligible_hourly_wage_delta=l_row.eligible_hourly_wage_delta,
                voluntary_hourly_exclusion=l_row.voluntary_hourly_exclusion,
                hw_prev=l_row.hw_prev,
                hw_req_new=l_row.hw_req_new,
                hw_act_new=l_row.hw_act_new,
                eligible_hourly_hw_delta=l_row.eligible_hourly_hw_delta,
                combined_tax_wc_rate=l_row.combined_tax_wc_rate,
                tax_wc_hourly_delta=l_row.tax_wc_hourly_delta,
                line_wage_entitlement=l_row.line_wage_entitlement,
                line_hw_entitlement=l_row.line_hw_entitlement,
                line_tax_wc_entitlement=l_row.line_tax_wc_entitlement,
                line_total_claim=l_row.line_total_claim,
            )
        )

    for sp in eval_res.evidence_spans:
        db.add(
            EvidenceSpan(
                org_id=org.id,
                case_id=adj_case.id,
                source_doc_type=sp.source_doc_type,
                source_doc_identifier=sp.source_doc_identifier,
                extracted_field_name=sp.extracted_field_name,
                extracted_value=sp.extracted_value,
                page_number=sp.page_number,
                char_start=sp.char_start,
                char_end=sp.char_end,
                verbatim_quote=sp.verbatim_quote,
                confidence_score=sp.confidence_score,
            )
        )

    db.commit()


@app.on_event("startup")
def on_startup() -> None:
    init_db()
    with SessionLocal() as db:
        seed_demo_data(db)


@app.get("/api/health")
def health_check() -> dict:
    return {
        "status": "ok",
        "service": settings.app_name,
        "naics_focus": settings.target_naics,
        "occupation_focus": f"{settings.primary_occupation_code} - {settings.primary_occupation_title}",
        "math_engine": "decimal.Decimal (ROUND_HALF_UP)",
    }


@app.get("/", response_class=HTMLResponse)
def dashboard_view(request: Request, db: Any = Depends(get_db)) -> HTMLResponse:
    cases = db.query(AdjustmentCase).all()
    contracts_by_id = {c.id: c for c in db.query(Contract).all()}
    case_views = []
    total_supported = Decimal("0.00")
    total_vol_excl = Decimal("0.00")
    pre_opt = 0
    active_clock = 0

    for c in cases:
        contract = contracts_by_id.get(c.contract_id)
        piid = contract.piid if contract else "UNKNOWN"
        if c.state_gate == "SUPPORTED":
            total_supported = q2(total_supported + c.total_claim_amount)
        total_vol_excl = q2(total_vol_excl + c.voluntary_raise_excluded_amount)
        if c.is_pre_option_alert:
            pre_opt += 1
        if c.days_remaining_30d_clock is not None and c.days_remaining_30d_clock >= 0:
            active_clock += 1
        case_views.append(
            {
                "id": c.id,
                "piid": piid,
                "state_gate": c.state_gate,
                "lifecycle_status": c.lifecycle_status,
                "days_remaining_30d_clock": c.days_remaining_30d_clock,
                "is_late_notice_flagged": c.is_late_notice_flagged,
                "total_eligible_wage_delta": f"{q2(c.total_eligible_wage_delta):,.2f}",
                "total_eligible_hw_delta": f"{q2(c.total_eligible_hw_delta):,.2f}",
                "total_accompanying_taxes_wc": f"{q2(c.total_accompanying_taxes_wc):,.2f}",
                "total_claim_amount": f"{q2(c.total_claim_amount):,.2f}",
            }
        )

    summary = {
        "total_supported_claim": f"{total_supported:,.2f}",
        "total_voluntary_excluded": f"{total_vol_excl:,.2f}",
        "pre_option_count": pre_opt,
        "active_clock_count": active_clock,
    }
    return templates.TemplateResponse(request, "dashboard.html", {"cases": case_views, "summary": summary})


@app.get("/cases/{case_id}", response_class=HTMLResponse)
def case_detail_view(case_id: str, request: Request, db: Any = Depends(get_db)) -> HTMLResponse:
    case = db.query(AdjustmentCase).filter(AdjustmentCase.id == case_id).first()
    if not case:
        raise HTTPException(status_code=404, detail="Case not found")
    contract = db.query(Contract).filter(Contract.id == case.contract_id).first()
    ledger = db.query(CalculationLedgerEntry).filter(CalculationLedgerEntry.case_id == case.id).all()
    spans = db.query(EvidenceSpan).filter(EvidenceSpan.case_id == case.id).all()

    case_data = {
        "id": case.id,
        "piid": contract.piid if contract else "UNKNOWN",
        "state_gate": case.state_gate,
        "lifecycle_status": case.lifecycle_status,
        "total_claim_amount": f"{q2(case.total_claim_amount):,.2f}",
        "gate_reason": case.gate_reason,
    }
    return templates.TemplateResponse(
        request,
        "case_detail.html",
        {"case": case_data, "ledger": ledger, "spans": spans},
    )


@app.get("/calculator", response_class=HTMLResponse)
def calculator_view(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(request, "calculator.html", {})


@app.post("/api/calculator", response_class=HTMLResponse)
def run_calculator(
    contract_piid: str = Form("47PM0924C0012"),
    worker_count: int = Form(25),
    annual_hours_per_worker: str = Form("2080"),
    w_prev: str = Form("16.50"),
    w_req_new: str = Form("18.20"),
    w_act_new: str = Form("19.00"),
    hw_prev: str = Form("4.57"),
    hw_req_new: str = Form("4.98"),
    hw_act_new: str = Form("4.98"),
) -> HTMLResponse:
    req = CalculatorRequest(
        contract_piid=contract_piid,
        worker_count=worker_count,
        annual_hours_per_worker=Decimal(annual_hours_per_worker),
        w_prev=Decimal(w_prev),
        w_req_new=Decimal(w_req_new),
        w_act_new=Decimal(w_act_new),
        hw_prev=Decimal(hw_prev),
        hw_req_new=Decimal(hw_req_new),
        hw_act_new=Decimal(hw_act_new),
    )
    quant = Agent2Quant()
    w_elig, w_vol = quant.compute_hourly_entitlement_delta(req.w_prev, req.w_req_new, req.w_act_new)
    hw_elig, _ = quant.compute_hourly_entitlement_delta(req.hw_prev, req.hw_req_new, req.hw_act_new)
    tax_rate = q4(req.fica_rate + req.futa_rate + req.suta_rate + req.workers_comp_rate)
    tax_hourly = q4(w_elig * tax_rate)

    total_hours = q4(Decimal(str(req.worker_count)) * req.annual_hours_per_worker)
    wage_total = q2(w_elig * total_hours)
    hw_total = q2(hw_elig * total_hours)
    tax_total = q2(tax_hourly * total_hours)
    vol_excluded_total = q2(w_vol * total_hours)
    grand_total = q2(wage_total + hw_total + tax_total)

    html = f"""
    <div class="space-y-3">
        <div class="flex items-center justify-between border-b border-slate-800 pb-3">
            <span class="font-semibold text-white">Contract {req.contract_piid} ({req.worker_count} Janitor FTEs • {total_hours:,.0f} hrs)</span>
            <span class="text-xl font-bold font-mono text-emerald-400">${grand_total:,.2f} Recoverable</span>
        </div>
        <div class="grid grid-cols-2 md:grid-cols-4 gap-3 text-xs font-mono">
            <div class="p-3 rounded bg-slate-950 border border-slate-800">
                <div class="text-slate-400">Eligible Wage Delta</div>
                <div class="text-white font-bold mt-1">${w_elig}/hr (${wage_total:,.2f})</div>
            </div>
            <div class="p-3 rounded bg-slate-950 border border-slate-800">
                <div class="text-slate-400">Eligible H&W Delta</div>
                <div class="text-white font-bold mt-1">${hw_elig}/hr (${hw_total:,.2f})</div>
            </div>
            <div class="p-3 rounded bg-slate-950 border border-slate-800">
                <div class="text-slate-400">Statutory Taxes & WC</div>
                <div class="text-white font-bold mt-1">${tax_hourly}/hr (${tax_total:,.2f})</div>
            </div>
            <div class="p-3 rounded bg-slate-950 border border-slate-800">
                <div class="text-amber-400">Voluntary Raise Excluded</div>
                <div class="text-amber-300 font-bold mt-1">${w_vol}/hr (${vol_excluded_total:,.2f})</div>
            </div>
        </div>
        <div class="text-xs text-slate-400">
            Strict FAR 52.222-43(d) Compliance: Overhead = $0.00 | G&A = $0.00 | Profit = $0.00.
        </div>
    </div>
    """
    return HTMLResponse(content=html)


@app.post("/api/prospect-audit")
def create_prospect_audit(
    prospect_company_name: str = "CleanStar Federal Services Inc.",
    prospect_uei: str = "U9M4N2P8Q1R5",
    contract_piid: str = "W912DR24C0045",
) -> dict:
    gen = SampleGenerator()
    teaser = gen.build_prospect_audit(
        prospect_company_name=prospect_company_name,
        prospect_uei=prospect_uei,
        contract_piid=contract_piid,
        agency_name="U.S. Army Corps of Engineers",
        locality="Fairfax County, VA",
        wd_number="2015-4281",
        old_revision=26,
        new_revision=27,
        next_option_date=date(2027, 1, 15),
        old_wd_rate=Decimal("16.50"),
        new_wd_rate=Decimal("18.20"),
        old_hw_rate=Decimal("4.57"),
        new_hw_rate=Decimal("4.98"),
    )
    return {
        "task_type": teaser.task_type,
        "contract_piid": teaser.contract_piid,
        "estimated_annual_recovery_usd": str(teaser.estimated_annual_recovery_usd),
        "days_until_option": teaser.days_until_option,
        "redacted_evidence_preview": teaser.redacted_evidence_preview,
        "claim_unlock_cta_url": teaser.claim_unlock_cta_url,
    }


@app.post("/api/billing/create-checkout-session")
def create_stripe_checkout(
    contract_piid: str = "47PM0924C0012",
    prospect_uei: str = "J8K2L9M4N5P6",
    estimated_recovery_usd: str = "97323.20",
    plan_code: str = "SINGLE_CLAIM_UNLOCK",
) -> dict:
    billing = StripeBillingService()
    session = billing.create_checkout_session(
        contract_piid=contract_piid,
        prospect_uei=prospect_uei,
        estimated_recovery_usd=Decimal(estimated_recovery_usd),
        plan_code=plan_code,
    )
    return {
        "session_id": session.session_id,
        "plan_code": session.plan_code,
        "contract_piid": session.contract_piid,
        "estimated_recovery_usd": str(session.estimated_recovery_usd),
        "charge_amount_usd": str(session.charge_amount_usd),
        "currency": session.currency,
        "checkout_url": session.checkout_url,
        "mode": session.mode,
    }
