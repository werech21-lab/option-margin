"""FastAPI Entrypoint, HTMX Views, and REST API Endpoints for OptionMargin."""

import html
import json
import os
import pathlib
from datetime import date
from decimal import Decimal
from fastapi import FastAPI, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
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
    TransactionalOutbox,
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
from app.services.email_dispatcher import OutboundEmailDispatcher
from app.services.stripe_billing import StripeBillingService
from app.services.usaspending_live import USAspendingLiveService

app = FastAPI(
    title=settings.app_name,
    version="1.0.0",
    description="Autonomous SCLS / FAR 52.222-43 Contract Margin Recovery Engine",
)

TEMPLATES_DIR = pathlib.Path(__file__).parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


EVAL_DATE = date(2026, 10, 30)


def _persist_wd(db: Any, parsed: Any) -> WageDetermination:
    row = WageDetermination(
        wd_number=parsed.wd_number,
        revision_number=parsed.revision_number,
        locality_state=parsed.locality_state,
        locality_county=parsed.locality_county,
        source_published_at=parsed.source_published_at,
        raw_content_hash=parsed.raw_content_hash,
        semantic_rate_hash=parsed.semantic_rate_hash,
        hw_rate_standard=parsed.hw_rate_standard,
        hw_rate_eo13706=parsed.hw_rate_eo13706,
        source_url=f"https://sam.gov/wage-determinations/{parsed.wd_number}/{parsed.revision_number}",
    )
    db.add(row)
    db.flush()
    for code, rate in parsed.occupation_rates.items():
        db.add(
            WDOccupationRate(
                wd_id=row.id,
                occupation_code=code,
                occupation_title=parsed.occupation_titles.get(code, "Janitor"),
                hourly_rate=rate,
            )
        )
    return row


def _payroll_row(
    label: str,
    regular_hours: str,
    overtime_hours: str,
    w_act: str,
    job_code: str = "JAN-1",
    scls: str | None = "23470",
) -> dict[str, Any]:
    row: dict[str, Any] = {
        "employee_name": label,
        "internal_job_code": job_code,
        "regular_hours": regular_hours,
        "overtime_hours": overtime_hours,
        "vacation_holiday_hours": "0.0000",
        "actual_prev_wage_rate": "16.5000",
        "actual_new_wage_rate": w_act,
        "actual_prev_hw_rate": "4.5700",
        "actual_new_hw_rate": "4.9800",
    }
    if scls is not None:
        row["scls_occupation_code"] = scls
    return row


def seed_demo_data(db: Any) -> None:
    """Seed the six canonical NAICS 561720 contracts when the database is empty."""
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
        raw_text="WD 2015-4281 Rev 26\n23470 - Janitor 16.50\nHEALTH & WELFARE: $4.57\nEO 13706: $4.57\n",
        wd_number="2015-4281",
        revision_number=26,
        locality_state="VA",
        locality_county="Arlington",
        source_published_at=date(2025, 6, 15),
    )
    new_wd_parsed = hunter.parse_wd_document(
        raw_text="WD 2015-4281 Rev 27\n23470 - Janitor 18.20\nHEALTH & WELFARE: $4.98\nEO 13706: $4.98\n",
        wd_number="2015-4281",
        revision_number=27,
        locality_state="VA",
        locality_county="Arlington",
        source_published_at=date(2026, 9, 15),
    )
    fmt_old_parsed = hunter.parse_wd_document(
        raw_text="WD 2015-4281 Rev 26\n23470 - Janitor 16.50\nHEALTH & WELFARE: $4.57\nEO 13706: $4.57\n",
        wd_number="2015-4281",
        revision_number=26,
        locality_state="MD",
        locality_county="Prince George's",
        source_published_at=date(2026, 8, 1),
    )
    fmt_new_parsed = hunter.parse_wd_document(
        raw_text="   WD 2015-4281 Rev 26 (HTML REFORMAT)  \n  23470 - Janitor   16.50 \nHEALTH & WELFARE: $4.57\nEO 13706: $4.57\n",
        wd_number="2015-4281",
        revision_number=26,
        locality_state="MD",
        locality_county="Prince George's",
        source_published_at=date(2026, 9, 1),
    )

    old_wd = _persist_wd(db, old_wd_parsed)
    new_wd = _persist_wd(db, new_wd_parsed)
    fmt_old = _persist_wd(db, fmt_old_parsed)
    fmt_new = _persist_wd(db, fmt_new_parsed)
    rate_diff = hunter.diff_wage_determinations(old_wd_parsed, new_wd_parsed)
    format_diff = hunter.diff_wage_determinations(fmt_old_parsed, fmt_new_parsed)
    quant = Agent2Quant()
    scrubber = PrivacyScrubber()
    sf30_parser = SF30Parser()

    def open_case(
        *,
        piid: str,
        agency_name: str,
        pop_state: str,
        pop_county: str,
        next_option: date,
        old_parsed: Any,
        new_parsed: Any,
        old_row: WageDetermination,
        new_row: WageDetermination,
        wd_diff: Any,
        payroll_rows: list[dict[str, Any]] | None,
        sf30_text: str | None,
        mod_number: str | None,
        receipt: date | None,
        lifecycle_override: str | None = None,
    ) -> None:
        contract = Contract(
            org_id=org.id,
            piid=piid,
            agency_name=agency_name,
            naics_code="561720",
            psc_code="S201",
            pop_state=pop_state,
            pop_county=pop_county,
            wd_number="2015-4281",
            active_wd_id=new_row.id,
            current_option_year=2,
            next_option_start_date=next_option,
        )
        db.add(contract)
        db.flush()

        sf30_parsed = None
        mod = None
        if sf30_text and mod_number and receipt is not None:
            sf30_parsed = sf30_parser.parse(
                sf30_text=sf30_text,
                effective_date=receipt,
                verified_receipt_date=receipt,
                explicit_mod_number=mod_number,
            )
            mod = ContractModification(
                org_id=org.id,
                contract_id=contract.id,
                mod_number=sf30_parsed.mod_number,
                mod_type=sf30_parsed.mod_type,
                incorporated_wd_id=new_row.id,
                effective_date=sf30_parsed.effective_date,
                verified_receipt_date=sf30_parsed.verified_receipt_date,
                notification_deadline_date=sf30_parsed.notification_deadline_date,
                sf30_block14_text=sf30_text[:500],
                document_hash=sf30_parsed.document_hash,
            )
            db.add(mod)
            db.flush()

        payroll_lines = None
        if payroll_rows is not None:
            payroll_lines, _, _ = scrubber.scrub_payroll_rows(raw_rows=payroll_rows, org_id=org.id)

        eval_res = quant.evaluate_case(
            contract_wd_number="2015-4281",
            contract_next_option_date=contract.next_option_start_date,
            is_eo13706_applicable=True,
            has_complex_cba=False,
            old_wd=old_parsed,
            new_wd=new_parsed,
            wd_diff=wd_diff,
            sf30_mod=sf30_parsed,
            payroll_lines=payroll_lines,
            tax_config=StatutoryTaxConfig(),
            evaluation_date=EVAL_DATE,
        )
        adj_case = AdjustmentCase(
            org_id=org.id,
            contract_id=contract.id,
            modification_id=mod.id if mod else None,
            old_wd_id=old_row.id,
            new_wd_id=new_row.id,
            state_gate=eval_res.state_gate.value,
            lifecycle_status=lifecycle_override or eval_res.lifecycle_status.value,
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

    option_sf30 = (
        "MODIFICATION {mod}: Pursuant to FAR 52.217-9 and FAR 52.222-43, "
        "the Government hereby exercises Option Period 2 and incorporates WD 2015-4281 Rev 27."
    )
    open_case(
        piid="47PM0924C0012",
        agency_name="GSA Public Buildings Service (Region 11 - Arlington, VA)",
        pop_state="VA",
        pop_county="Arlington",
        next_option=date(2027, 10, 1),
        old_parsed=old_wd_parsed,
        new_parsed=new_wd_parsed,
        old_row=old_wd,
        new_row=new_wd,
        wd_diff=rate_diff,
        payroll_rows=[
            _payroll_row("COHORT-1", "20800.0000", "0.0000", "19.0000", "JAN-1"),
            _payroll_row("COHORT-2", "20800.0000", "0.0000", "19.0000", "JAN-2"),
        ],
        sf30_text=option_sf30.format(mod="P00004"),
        mod_number="P00004",
        receipt=date(2026, 10, 10),
        lifecycle_override="SUPPORTED",
    )
    open_case(
        piid="W912DR24C0045",
        agency_name="U.S. Army Corps of Engineers (Baltimore District, MD)",
        pop_state="MD",
        pop_county="Baltimore",
        next_option=date(2027, 10, 1),
        old_parsed=old_wd_parsed,
        new_parsed=new_wd_parsed,
        old_row=old_wd,
        new_row=new_wd,
        wd_diff=rate_diff,
        payroll_rows=[_payroll_row("COHORT-OT", "20800.0000", "200.0000", "18.4400", "JAN-OT")],
        sf30_text=option_sf30.format(mod="P00003"),
        mod_number="P00003",
        receipt=date(2026, 10, 16),
        lifecycle_override="SUBMITTED",
    )
    open_case(
        piid="GS03P24CD0019",
        agency_name="GSA Public Buildings Service (Montgomery County, MD)",
        pop_state="MD",
        pop_county="Montgomery",
        next_option=date(2027, 1, 13),
        old_parsed=old_wd_parsed,
        new_parsed=new_wd_parsed,
        old_row=old_wd,
        new_row=new_wd,
        wd_diff=rate_diff,
        payroll_rows=None,
        sf30_text=None,
        mod_number=None,
        receipt=None,
    )
    open_case(
        piid="36C24524C0118",
        agency_name="Department of Veterans Affairs (VISN 5 Medical Center)",
        pop_state="MD",
        pop_county="Baltimore",
        next_option=date(2027, 1, 2),
        old_parsed=old_wd_parsed,
        new_parsed=new_wd_parsed,
        old_row=old_wd,
        new_row=new_wd,
        wd_diff=rate_diff,
        payroll_rows=None,
        sf30_text=None,
        mod_number=None,
        receipt=None,
    )
    open_case(
        piid="FA890324C0008",
        agency_name="Department of the Air Force (772 ESS Facility Services)",
        pop_state="MD",
        pop_county="Anne Arundel",
        next_option=date(2027, 10, 1),
        old_parsed=old_wd_parsed,
        new_parsed=new_wd_parsed,
        old_row=old_wd,
        new_row=new_wd,
        wd_diff=rate_diff,
        payroll_rows=[_payroll_row("UNMAPPED-JOB", "2080.0000", "0.0000", "18.2000", "CUST-LD-99", None)],
        sf30_text="MODIFICATION P00002 incorporates WD 2015-4281 Rev 27.",
        mod_number="P00002",
        receipt=date(2026, 10, 18),
    )
    open_case(
        piid="70B06C24C00000042",
        agency_name="Department of Homeland Security (CBP Training Facility)",
        pop_state="MD",
        pop_county="Prince George's",
        next_option=date(2027, 6, 1),
        old_parsed=fmt_old_parsed,
        new_parsed=fmt_new_parsed,
        old_row=fmt_old,
        new_row=fmt_new,
        wd_diff=format_diff,
        payroll_rows=None,
        sf30_text=None,
        mod_number=None,
        receipt=None,
    )
    db.commit()


@app.on_event("startup")
def on_startup() -> None:
    init_db()
    with SessionLocal() as db:
        seed_demo_data(db)


@app.get("/command-center", response_class=HTMLResponse)
def command_center() -> HTMLResponse:
    index_path = pathlib.Path(__file__).resolve().parents[1] / "index.html"
    return HTMLResponse(index_path.read_text(encoding="utf-8"))


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


def run_live_sniper_pipeline(
    limit: int = 5,
    recipient_email: str = "werech21@gmail.com",
    db: Any = None,
) -> dict:
    """Pull live NAICS 561720 awards, price each teaser, and queue idempotent outbox emails."""
    owns_session = db is None
    if db is None:
        db = SessionLocal()
    try:
        from app.services.poc_resolver import ContractorPOCResolver

        teasers = USAspendingLiveService().generate_live_prospect_audits(limit=limit)
        dispatcher = OutboundEmailDispatcher()
        resolver = ContractorPOCResolver()
        executor = Agent3Executor()
        records: list[dict[str, Any]] = []
        for teaser in teasers:
            poc = resolver.resolve_poc(teaser.prospect_company_name, teaser.prospect_uei)
            email = dispatcher.build_audit_email(teaser, recipient_email=recipient_email, poc=poc)
            payload = {
                "idempotency_key": email.idempotency_key,
                "recipient_email": email.recipient_email,
                "subject": email.subject,
                "contract_piid": email.contract_piid,
                "prospect_company_name": teaser.prospect_company_name,
                "estimated_recovery_usd": email.estimated_recovery_usd,
                "stripe_checkout_url": email.stripe_checkout_url,
                "charge_amount_usd": "1499.00",
                "delivery_channel": email.delivery_channel,
                "delivery_status": email.delivery_status,
                "days_until_option": teaser.days_until_option,
                "poc_name": poc.poc_name,
                "poc_title": poc.poc_title,
                "poc_email": poc.poc_email,
                "resolution_source": poc.resolution_source,
            }
            record, created = executor.enqueue_outbox_task(
                db,
                org_id=None,
                idempotency_key=email.idempotency_key,
                task_type="prospect_audit",
                payload=payload,
            )
            if not created:
                record.payload_json = json.dumps(payload, default=str)
                db.commit()
            records.append({**payload, "outbox_id": record.id, "created": created, "status": record.status})
        return {"count": len(records), "recipient_email": recipient_email, "records": records}
    finally:
        if owns_session:
            db.close()


@app.post("/api/sniper/run-live")
def run_live_sniper_endpoint(
    limit: int = 5,
    recipient_email: str = "werech21@gmail.com",
    db: Any = Depends(get_db),
) -> dict:
    return run_live_sniper_pipeline(limit=limit, recipient_email=recipient_email, db=db)


@app.get("/api/outbox")
def list_outbox(db: Any = Depends(get_db)) -> dict:
    rows = db.query(TransactionalOutbox).filter(TransactionalOutbox.task_type == "prospect_audit").all()
    items = []
    for row in rows:
        try:
            payload = json.loads(row.payload_json)
        except (TypeError, ValueError):
            payload = {"raw": row.payload_json}
        items.append(
            {
                "id": row.id,
                "idempotency_key": row.idempotency_key,
                "task_type": row.task_type,
                "status": row.status,
                "payload": payload,
            }
        )
    return {"count": len(items), "records": items}


PUBLIC_BASE_URL = os.getenv("PUBLIC_BASE_URL", "https://optionmargin-engine.onrender.com").rstrip("/")

WAGE_DETERMINATIONS: dict[str, dict[str, str]] = {
    "2015-4281": {
        "locality": "Arlington, VA and Washington, DC",
        "old_revision": "26",
        "new_revision": "27",
        "old_wage": "16.50",
        "new_wage": "18.20",
        "alt_wage": "DC floor moves from $17.10 to $18.95",
        "old_hw": "4.57",
        "new_hw": "4.98",
    },
    "2015-4265": {
        "locality": "Baltimore, MD",
        "old_revision": "24",
        "new_revision": "25",
        "old_wage": "16.50",
        "new_wage": "18.20",
        "alt_wage": "Maryland janitorial schedule",
        "old_hw": "4.57",
        "new_hw": "4.98",
    },
    "2015-5253": {
        "locality": "Texas statewide janitorial locality",
        "old_revision": "22",
        "new_revision": "23",
        "old_wage": "14.80",
        "new_wage": "16.40",
        "alt_wage": "Texas wage floor",
        "old_hw": "4.57",
        "new_hw": "4.98",
    },
    "2015-5637": {
        "locality": "California statewide janitorial locality",
        "old_revision": "25",
        "new_revision": "26",
        "old_wage": "18.10",
        "new_wage": "19.90",
        "alt_wage": "California wage floor",
        "old_hw": "4.57",
        "new_hw": "4.98",
    },
}


def _money(value: Decimal | str) -> str:
    return f"{Decimal(str(value)):,.2f}"


def _commercial_page(title: str, body: str) -> HTMLResponse:
    safe_title = html.escape(title)
    document = f"""<!DOCTYPE html>
<html lang="en" class="h-full bg-slate-950 text-slate-100">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{safe_title}</title>
    <meta name="description" content="OptionMargin prices the mandatory FAR 52.222-43 Service Contract Act adjustment for NAICS 561720 janitorial contracts. Overhead, G&amp;A, and profit stay at $0.00.">
    <script src="https://cdn.tailwindcss.com"></script>
    <script src="https://unpkg.com/htmx.org@1.9.12"></script>
</head>
<body class="min-h-full font-sans antialiased">
    <nav class="border-b border-slate-800 bg-slate-900/90 sticky top-0 z-30">
        <div class="max-w-5xl mx-auto px-4 h-16 flex items-center justify-between">
            <a href="/" class="text-lg font-bold text-white">OptionMargin</a>
            <div class="flex gap-4 text-sm">
                <a href="/calculator" class="text-slate-300 hover:text-white">Calculator</a>
                <a href="/wd/2015-4281" class="text-slate-300 hover:text-white">Wage Determinations</a>
                <a href="/command-center" class="text-emerald-400">Command Center</a>
            </div>
        </div>
    </nav>
    <main class="max-w-5xl mx-auto px-4 py-10">{body}</main>
</body>
</html>"""
    return HTMLResponse(document)


def _teaser_for_claim(contract_piid: str, uei: str, db: Any):
    stored = None
    rows = db.query(TransactionalOutbox).filter(TransactionalOutbox.task_type == "prospect_audit").all()
    for row in rows:
        try:
            payload = json.loads(row.payload_json)
        except (TypeError, ValueError):
            continue
        if payload.get("contract_piid") == contract_piid:
            stored = payload
            break
    fte = 30 if contract_piid == "47PM0924C0088" else 20
    state = "MD" if contract_piid.startswith("W912") else "VA"
    wd = WAGE_DETERMINATIONS["2015-4265" if state == "MD" else "2015-4281"]
    teaser = SampleGenerator().build_prospect_audit(
        prospect_company_name=(stored or {}).get("prospect_company_name") or "Federal Janitorial Contractor",
        prospect_uei=uei or "PENDING-UEI",
        contract_piid=contract_piid,
        agency_name="General Services Administration" if state == "VA" else "U.S. Army Corps of Engineers",
        locality=wd["locality"],
        wd_number="2015-4265" if state == "MD" else "2015-4281",
        old_revision=int(wd["old_revision"]),
        new_revision=int(wd["new_revision"]),
        next_option_date=date(2027, 1, 3),
        old_wd_rate=Decimal(wd["old_wage"]),
        new_wd_rate=Decimal(wd["new_wage"]),
        old_hw_rate=Decimal(wd["old_hw"]),
        new_hw_rate=Decimal(wd["new_hw"]),
        estimated_janitor_fte=fte,
        as_of_date=date(2026, 10, 30),
    )
    if stored and stored.get("estimated_recovery_usd"):
        return teaser, Decimal(stored["estimated_recovery_usd"])
    return teaser, teaser.estimated_annual_recovery_usd


@app.get("/claim-audit/{contract_piid}", response_class=HTMLResponse)
def claim_audit_page(contract_piid: str, uei: str = "PENDING-UEI", db: Any = Depends(get_db)) -> HTMLResponse:
    teaser, recovery = _teaser_for_claim(contract_piid, uei, db)
    checkout = StripeBillingService().create_checkout_session(
        contract_piid=contract_piid,
        prospect_uei=uei,
        estimated_recovery_usd=recovery,
        plan_code="SINGLE_CLAIM_UNLOCK",
    )
    preview = html.escape(teaser.redacted_evidence_preview)
    body = f"""
    <p class="text-xs uppercase tracking-wider text-amber-300">Watermarked prospect audit · SF-30 still redacted</p>
    <h1 class="mt-3 text-3xl font-bold text-white">FAR 52.222-43 margin recovery audit for {html.escape(contract_piid)}</h1>
    <p class="mt-3 text-slate-300">UEI {html.escape(uei)} · {html.escape(teaser.agency_name)} · {html.escape(teaser.locality)}</p>
    <div class="mt-8 grid md:grid-cols-3 gap-4">
        <div class="p-5 rounded-xl bg-slate-900 border border-slate-800">
            <div class="text-xs text-slate-400">Estimated annual recovery</div>
            <div class="mt-2 text-3xl font-bold text-emerald-400">${_money(recovery)}</div>
            <div class="mt-2 text-sm text-slate-400">Published wedge for this occupation: $97,323.20 – $145,984.80</div>
        </div>
        <div class="p-5 rounded-xl bg-slate-900 border border-rose-900/60">
            <div class="text-xs text-rose-300">FAR 52.222-43(f) clock</div>
            <div class="mt-2 text-xl font-bold text-white">30 calendar days from verified SF-30 receipt</div>
            <div class="mt-2 text-sm text-slate-400">{teaser.days_until_option} days remain before the next option date ({teaser.next_option_date.isoformat()}). A late notice can forfeit the adjustment.</div>
        </div>
        <div class="p-5 rounded-xl bg-slate-900 border border-slate-800">
            <div class="text-xs text-slate-400">Price of the unredacted package</div>
            <div class="mt-2 text-3xl font-bold text-white">$1,499.00</div>
            <div class="mt-2 text-sm text-slate-400">6,400% ROI against a $97,323.20 claim. OH / G&amp;A / Profit stay $0.00.</div>
        </div>
    </div>
    <section class="mt-8 p-6 rounded-xl bg-slate-900 border border-slate-800">
        <h2 class="text-lg font-semibold text-white">Redacted SF-30 and evidence span</h2>
        <p class="mt-3 text-sm leading-6 text-slate-300">{preview}</p>
        <p class="mt-4 text-sm text-slate-500">Worker names, SSNs, and the contracting officer's block are removed until the package is unlocked.</p>
    </section>
    <a href="{html.escape(checkout.checkout_url)}" class="mt-8 inline-flex px-6 py-4 rounded-lg bg-emerald-500 text-slate-950 font-bold text-lg">Unlock Unredacted Evidence Package &amp; CO Claim Letter ($1,499 — 6,400% ROI)</a>
    """
    return _commercial_page(f"Claim audit {contract_piid}", body)


@app.get("/checkout/{session_id}", response_class=HTMLResponse)
def checkout_portal(
    session_id: str,
    piid: str = "47PM0924C0012",
    uei: str = "PENDING-UEI",
    plan: str = "SINGLE_CLAIM_UNLOCK",
    amount: str = "1499.00",
    recovery: str = "97323.20",
) -> HTMLResponse:
    fee = _money(amount)
    body = f"""
    <p class="text-xs uppercase tracking-wider text-emerald-300">Corporate checkout and invoice reservation</p>
    <h1 class="mt-3 text-3xl font-bold text-white">Authorize the ${fee} claim package</h1>
    <p class="mt-3 text-slate-300">Contract {html.escape(piid)} · UEI {html.escape(uei)} · Plan {html.escape(plan)} · Estimated recovery ${_money(recovery)}</p>
    <form method="post" action="/api/billing/capture-order" class="mt-8 grid md:grid-cols-2 gap-4 p-6 rounded-xl bg-slate-900 border border-slate-800">
        <input type="hidden" name="session_id" value="{html.escape(session_id)}">
        <input type="hidden" name="contract_piid" value="{html.escape(piid)}">
        <input type="hidden" name="prospect_uei" value="{html.escape(uei)}">
        <input type="hidden" name="plan_code" value="{html.escape(plan)}">
        <input type="hidden" name="amount" value="{html.escape(amount)}">
        <input type="hidden" name="recovery" value="{html.escape(recovery)}">
        <label class="text-sm text-slate-300">Company name<input required name="company_name" class="mt-1 w-full px-3 py-2 rounded bg-slate-950 border border-slate-700 text-white"></label>
        <label class="text-sm text-slate-300">CFO / contracts manager<input required name="contact_name" class="mt-1 w-full px-3 py-2 rounded bg-slate-950 border border-slate-700 text-white"></label>
        <label class="text-sm text-slate-300">Official email<input required type="email" name="email" class="mt-1 w-full px-3 py-2 rounded bg-slate-950 border border-slate-700 text-white"></label>
        <label class="text-sm text-slate-300">Phone<input required name="phone" class="mt-1 w-full px-3 py-2 rounded bg-slate-950 border border-slate-700 text-white"></label>
        <label class="md:col-span-2 text-sm text-slate-300">SF-30 modification status
            <select name="sf30_status" class="mt-1 w-full px-3 py-2 rounded bg-slate-950 border border-slate-700 text-white">
                <option>Not yet received</option>
                <option>Received — 30-day clock running</option>
                <option>Incorporated in the contract</option>
            </select>
        </label>
        <button class="md:col-span-2 py-3 rounded-lg bg-emerald-500 text-slate-950 font-bold" type="submit">Authorize ${fee} Claim Package Unlock</button>
    </form>
    <p class="mt-4 text-xs text-slate-500">Card checkout runs through Stripe when a secret key is configured. Otherwise this reservation is captured for ACH or corporate invoice. Session {html.escape(session_id)}.</p>
    """
    return _commercial_page(f"Checkout {session_id}", body)


@app.post("/api/billing/capture-order")
def capture_order(
    session_id: str = Form(...),
    contract_piid: str = Form(...),
    prospect_uei: str = Form(...),
    plan_code: str = Form("SINGLE_CLAIM_UNLOCK"),
    amount: str = Form("1499.00"),
    recovery: str = Form("0.00"),
    company_name: str = Form(...),
    contact_name: str = Form(...),
    email: str = Form(...),
    phone: str = Form(...),
    sf30_status: str = Form("Not yet received"),
    db: Any = Depends(get_db),
) -> RedirectResponse:
    payload = {
        "order_status": "ORDER_CAPTURED",
        "session_id": session_id,
        "contract_piid": contract_piid,
        "prospect_uei": prospect_uei,
        "plan_code": plan_code,
        "amount": amount,
        "recovery": recovery,
        "company_name": company_name,
        "contact_name": contact_name,
        "email": email,
        "phone": phone,
        "sf30_status": sf30_status,
    }
    subject = f"[OptionMargin Order] {company_name} authorized ${amount} for {contract_piid}"
    html_body = (
        f"<p>{html.escape(company_name)} ({html.escape(contact_name)}) reserved a "
        f"${html.escape(amount)} unlock for {html.escape(contract_piid)}.</p>"
        f"<p>Email {html.escape(email)} · Phone {html.escape(phone)} · SF-30: {html.escape(sf30_status)}</p>"
    )
    channel, status = OutboundEmailDispatcher._send_if_configured(
        "werech21@gmail.com",
        subject,
        html_body,
        f"{company_name} authorized ${amount} for {contract_piid}. Contact {contact_name} {email} {phone}.",
    )
    payload["delivery_channel"] = channel
    payload["delivery_status"] = status
    record, _created = Agent3Executor().enqueue_outbox_task(
        db,
        org_id=None,
        idempotency_key=f"ORDER-{session_id}",
        task_type="billing_sync",
        payload=payload,
    )
    record.status = "ORDER_CAPTURED"
    record.result_summary = "ORDER_CAPTURED"
    db.commit()
    return RedirectResponse(url=f"/command-center?unlocked={contract_piid}", status_code=303)


@app.get("/wd/{wd_number}", response_class=HTMLResponse)
def wage_determination_page(wd_number: str) -> HTMLResponse:
    page = WAGE_DETERMINATIONS.get(wd_number)
    if page is None:
        listed = ", ".join(WAGE_DETERMINATIONS)
        return _commercial_page("Wage determination not found", f"<h1 class='text-2xl font-bold'>WD {html.escape(wd_number)} is not in the public index.</h1><p class='mt-3 text-slate-300'>Indexed determinations: {html.escape(listed)}</p>")
    body = f"""
    <p class="text-xs uppercase tracking-wider text-sky-300">Programmatic wage determination · NAICS 561720</p>
    <h1 class="mt-3 text-3xl font-bold text-white">WD {html.escape(wd_number)} · 23470 Janitor</h1>
    <p class="mt-3 text-slate-300">{html.escape(page['locality'])}. {html.escape(page['alt_wage'])}.</p>
    <div class="mt-8 overflow-hidden rounded-xl border border-slate-800">
        <table class="w-full text-sm">
            <thead class="bg-slate-900 text-slate-400"><tr><th class="text-left p-3">Revision</th><th class="text-left p-3">Wage</th><th class="text-left p-3">Health &amp; Welfare</th></tr></thead>
            <tbody>
                <tr class="border-t border-slate-800"><td class="p-3">Rev {html.escape(page['old_revision'])}</td><td class="p-3">${html.escape(page['old_wage'])}</td><td class="p-3">${html.escape(page['old_hw'])}</td></tr>
                <tr class="border-t border-slate-800"><td class="p-3">Rev {html.escape(page['new_revision'])}</td><td class="p-3 text-emerald-400">${html.escape(page['new_wage'])}</td><td class="p-3 text-emerald-400">${html.escape(page['new_hw'])}</td></tr>
            </tbody>
        </table>
    </div>
    <section class="mt-8 p-6 rounded-xl bg-slate-900 border border-slate-800">
        <h2 class="text-lg font-semibold">SCLS margin bleed calculator</h2>
        <form hx-post="/api/calculator" hx-target="#wd-calc" hx-swap="innerHTML" class="mt-4 grid md:grid-cols-3 gap-3">
            <input type="hidden" name="contract_piid" value="WD-{html.escape(wd_number)}">
            <label class="text-xs text-slate-400">Janitor FTE<input name="worker_count" value="20" class="mt-1 w-full px-3 py-2 rounded bg-slate-950 border border-slate-700 text-white"></label>
            <label class="text-xs text-slate-400">Hours / FTE<input name="annual_hours_per_worker" value="2080" class="mt-1 w-full px-3 py-2 rounded bg-slate-950 border border-slate-700 text-white"></label>
            <label class="text-xs text-slate-400">W prev<input name="w_prev" value="{html.escape(page['old_wage'])}" class="mt-1 w-full px-3 py-2 rounded bg-slate-950 border border-slate-700 text-white"></label>
            <label class="text-xs text-slate-400">W required<input name="w_req_new" value="{html.escape(page['new_wage'])}" class="mt-1 w-full px-3 py-2 rounded bg-slate-950 border border-slate-700 text-white"></label>
            <label class="text-xs text-slate-400">W paid<input name="w_act_new" value="{html.escape(page['new_wage'])}" class="mt-1 w-full px-3 py-2 rounded bg-slate-950 border border-slate-700 text-white"></label>
            <label class="text-xs text-slate-400">H&amp;W prev<input name="hw_prev" value="{html.escape(page['old_hw'])}" class="mt-1 w-full px-3 py-2 rounded bg-slate-950 border border-slate-700 text-white"></label>
            <label class="text-xs text-slate-400">H&amp;W required<input name="hw_req_new" value="{html.escape(page['new_hw'])}" class="mt-1 w-full px-3 py-2 rounded bg-slate-950 border border-slate-700 text-white"></label>
            <label class="text-xs text-slate-400">H&amp;W paid<input name="hw_act_new" value="{html.escape(page['new_hw'])}" class="mt-1 w-full px-3 py-2 rounded bg-slate-950 border border-slate-700 text-white"></label>
            <button class="md:col-span-3 py-3 rounded-lg bg-emerald-600 text-white font-semibold" type="submit">Calculate this wage determination</button>
        </form>
        <div id="wd-calc" class="mt-4 text-sm text-slate-300"></div>
    </section>
    """
    return _commercial_page(f"WD {wd_number} Janitor rates", body)


@app.get("/sitemap.xml")
def sitemap() -> Response:
    paths = ["/", "/calculator", "/command-center", "/claim-audit/47PM0924C0088", "/claim-audit/47PM0924C0012"]
    paths.extend(f"/wd/{number}" for number in WAGE_DETERMINATIONS)
    urls = "\n".join(f"  <url><loc>{PUBLIC_BASE_URL}{path}</loc></url>" for path in paths)
    xml = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        f"{urls}\n</urlset>\n"
    )
    return Response(content=xml, media_type="application/xml")


@app.get("/robots.txt")
def robots() -> Response:
    body = f"User-agent: *\nAllow: /\nSitemap: {PUBLIC_BASE_URL}/sitemap.xml\n"
    return Response(content=body, media_type="text/plain")
