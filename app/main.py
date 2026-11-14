"""FastAPI routes for the OptionMargin FAR 52.222-43 workspace."""

from __future__ import annotations

import hashlib
from contextlib import asynccontextmanager
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path

from fastapi import Depends, FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.agents.agent2_quant import Agent2Quant
from app.agents.agent3_executor import Agent3Executor
from app.config import RULE_PACK_VERSION, money_text, q2, q4, rate_text, settings
from app.database import SessionLocal, get_db, init_db
from app.models import (
    AdjustmentCase,
    BillingMatch,
    ChangeEvent,
    Contract,
    ContractVersion,
    EvidenceLink,
    PayrollRow,
    SourceSnapshot,
    WageRate,
    utcnow,
)
from app.seed import TENANT_ID, seed_if_empty
from app.services.pipeline import run_billing_reconciliation, run_pipeline, simulate_duplicate_webhook
from app.services.privacy_scrubber import PrivacyScrubber
from app.services.sample_generator import cold_email, demo_case_contract
from app.agents.agent1_hunter import Agent1Hunter

TEMPLATES = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))
TEMPLATES.env.filters["money"] = money_text
TEMPLATES.env.filters["rate"] = rate_text


@asynccontextmanager
async def lifespan(_app: FastAPI):
    init_db()
    db = SessionLocal()
    try:
        seed_if_empty(db)
    finally:
        db.close()
    yield


app = FastAPI(title=settings.app_name, version="1.0.0", lifespan=lifespan)


def _base(request: Request, **extra: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "request": request,
        "rule_pack_version": RULE_PACK_VERSION,
        "notice": request.query_params.get("notice", ""),
        "today": date.today(),
    }
    payload.update(extra)
    return payload


def _demo_adjustment():
    return Agent2Quant().compute_adjustment(
        workers=60,
        hours_per_worker=Decimal("160"),
        actual_prev_wage=Decimal("22.40"),
        new_required_wage=Decimal("23.40"),
        actual_new_wage=Decimal("23.60"),
        hw_delta=Decimal("0.00"),
    )


def _days_remaining(deadline: date | None, today: date) -> int | None:
    if deadline is None:
        return None
    return (deadline - today).days


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok", "rule_pack_version": RULE_PACK_VERSION}


@app.get("/", response_class=HTMLResponse)
def landing(request: Request) -> HTMLResponse:
    return TEMPLATES.TemplateResponse(
        request,
        "landing.html",
        _base(request, sample=None, adjustment=_demo_adjustment()),
    )


@app.get("/calculator", response_class=HTMLResponse)
def calculator(request: Request) -> HTMLResponse:
    return TEMPLATES.TemplateResponse(request, "calculator.html", _base(request, sample=None, adjustment=_demo_adjustment()))


@app.post("/api/calculate-preview", response_class=HTMLResponse)
def calculate_preview(
    request: Request,
    workers: str = Form("60"),
    hours_per_worker: str = Form("160"),
    actual_prev_wage: str = Form("22.40"),
    new_required_wage: str = Form("23.40"),
    actual_new_wage: str = Form("23.60"),
    hw_delta: str = Form("0.00"),
    fica_rate: str = Form("0.00"),
    futa_rate: str = Form("0.00"),
    suta_rate: str = Form("0.00"),
    wc_rate: str = Form("0.00"),
) -> HTMLResponse:
    try:
        worker_count = int(workers)
        adjustment = Agent2Quant().compute_adjustment(
            workers=worker_count,
            hours_per_worker=q2(hours_per_worker),
            actual_prev_wage=q4(actual_prev_wage),
            new_required_wage=q4(new_required_wage),
            actual_new_wage=q4(actual_new_wage),
            hw_delta=q4(hw_delta),
            fica_rate=q4(fica_rate),
            futa_rate=q4(futa_rate),
            suta_rate=q4(suta_rate),
            wc_rate=q4(wc_rate),
        )
    except (InvalidOperation, TypeError, ValueError, ArithmeticError) as exc:
        return HTMLResponse(
            "<p class='preview-error'>Enter workers as a whole number and every rate as a decimal. "
            + _html_escape(str(exc))
            + "</p>",
            status_code=400,
        )
    return TEMPLATES.TemplateResponse(
        request,
        "partials/preview_result.html",
        {"request": request, "adjustment": adjustment},
    )


@app.post("/api/lead", response_class=HTMLResponse)
def lead_sample(
    request: Request,
    company_name: str = Form(...),
    email: str = Form(...),
    contract_id: str = Form(""),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    company = company_name.strip()
    address = email.strip()
    if len(company) < 2 or "@" not in address:
        return HTMLResponse("<p class='preview-error'>Enter a company name and a real email address.</p>", status_code=400)
    sample = demo_case_contract()
    letter = cold_email(
        company=company,
        award_id=contract_id.strip() or "CONTRACT-DEMO",
        agency="Department of Veterans Affairs",
        county="Arlington",
        state="VA",
        hourly_delta=Decimal("1.00"),
    )
    digest = hashlib.sha256(address.lower().encode("utf-8")).hexdigest()[:16]
    Agent3Executor().run(
        db,
        {
            "tenant_id": TENANT_ID,
            "contract_id": "CONTRACT-DEMO",
            "wd_id": f"LEAD-{digest}",
            "revision": 1,
            "event_type": "WAGE_REVISION",
            "case_id": "CASE-DEMO-017",
            "channel": "INTERNAL_TASK",
            "recipient": address,
            "status": "POTENTIAL",
            "company_name": company,
            "sample_case": sample,
        },
    )
    return TEMPLATES.TemplateResponse(
        request,
        "partials/lead_result.html",
        {"request": request, "sample": sample, "letter": letter, "company_name": company},
    )


@app.get("/dashboard", response_class=HTMLResponse)
def dashboard(request: Request, db: Session = Depends(get_db)) -> HTMLResponse:
    cases = db.query(AdjustmentCase).order_by(AdjustmentCase.updated_at.desc()).all()
    contracts = {row.contract_id: row for row in db.query(Contract).all()}
    events = {row.id: row for row in db.query(ChangeEvent).all()}
    today = date.today()
    rows = []
    for case in cases:
        contract = contracts.get(case.contract_id)
        event = events.get(case.change_event_id) if case.change_event_id else None
        locality = "—"
        wd_label = "—"
        agency = "—"
        if contract is not None:
            agency = contract.agency_name or "—"
            locality = f"{contract.place_of_performance_county or ''}, {contract.place_of_performance_state or ''}".strip(", ")
            revision = event.current_revision if event is not None else None
            wd_label = contract.mapped_wd_id or "—"
            if revision is not None:
                wd_label = f"{wd_label} Rev {revision}"
        rows.append(
            {
                "case": case,
                "agency": agency,
                "locality_wd": f"{locality} · {wd_label}",
                "days_remaining": _days_remaining(case.filing_deadline_date, today),
            }
        )
    identified = q2(sum((q2(case.annualized_exposure_usd) for case in cases), Decimal("0.00")))
    supported_cases = [case for case in cases if case.status == "SUPPORTED"]
    supported_monthly = q2(sum((q2(case.estimated_monthly_exposure_usd) for case in supported_cases), Decimal("0.00")))
    agreed = q2(sum((q2(case.agreed_adjustment_usd) for case in cases), Decimal("0.00")))
    collected = q2(sum((q2(case.billed_collected_usd) for case in cases), Decimal("0.00")))
    leakage = q2(
        sum(
            (
                q2(match.variance_leakage_usd)
                for match in db.query(BillingMatch).all()
                if match.reconciliation_status == "UNDERBILLED_LEAKAGE"
            ),
            Decimal("0.00"),
        )
    )
    return TEMPLATES.TemplateResponse(
        request,
        "dashboard.html",
        _base(
            request,
            rows=rows,
            identified=identified,
            supported_count=len(supported_cases),
            supported_monthly=supported_monthly,
            agreed=agreed,
            collected=collected,
            leakage=leakage,
        ),
    )


@app.post("/api/pipeline/run")
def pipeline_run(db: Session = Depends(get_db)) -> RedirectResponse:
    result = run_pipeline(db)
    return RedirectResponse(
        f"/dashboard?notice=Pipeline finished. Gate {result['gate_decision']}. Prospects {result['prospects']}.",
        status_code=303,
    )


@app.post("/api/pipeline/duplicate-webhook")
def pipeline_duplicate(db: Session = Depends(get_db)) -> RedirectResponse:
    result = simulate_duplicate_webhook(db)
    return RedirectResponse(
        "/dashboard?notice="
        + f"Duplicate webhook: {result['attempts']} attempts, {result['cases']} adjustment case, {result['outbox_rows']} outbox row.",
        status_code=303,
    )


@app.post("/api/billing/reconcile")
def billing_reconcile(db: Session = Depends(get_db)) -> RedirectResponse:
    result = run_billing_reconciliation(db)
    return RedirectResponse(
        f"/dashboard?notice=Billing reconciliation checked {result['matches']} invoices. Leakage ${result['leakage']}.",
        status_code=303,
    )


@app.get("/cases/{case_id}", response_class=HTMLResponse)
def case_detail(case_id: str, request: Request, db: Session = Depends(get_db)) -> HTMLResponse:
    case = db.query(AdjustmentCase).filter(AdjustmentCase.case_id == case_id).one_or_none()
    if case is None:
        raise HTTPException(status_code=404, detail=f"Case {case_id} is not in this workspace.")
    contract = db.query(Contract).filter(Contract.contract_id == case.contract_id).one()
    event = db.query(ChangeEvent).filter(ChangeEvent.id == case.change_event_id).one_or_none() if case.change_event_id else None
    versions = sorted(case.calculations, key=lambda row: row.version_num)
    latest = versions[-1] if versions else None
    evidence = db.query(EvidenceLink).filter(EvidenceLink.case_id == case.case_id).all()
    billing = db.query(BillingMatch).filter(BillingMatch.case_id == case.case_id).all()
    mods = db.query(ContractVersion).filter(ContractVersion.contract_id == case.contract_id).all()
    previous_rate = None
    current_rate = None
    previous_hash = None
    current_hash = None
    if event is not None:
        previous_rate = (
            db.query(WageRate)
            .filter(
                WageRate.wd_id == event.wd_id,
                WageRate.revision == event.previous_revision,
                WageRate.occupation_code == "23470",
            )
            .one_or_none()
        )
        current_rate = (
            db.query(WageRate)
            .filter(
                WageRate.wd_id == event.wd_id,
                WageRate.revision == event.current_revision,
                WageRate.occupation_code == "23470",
            )
            .one_or_none()
        )
        previous_snap = (
            db.query(SourceSnapshot)
            .filter(SourceSnapshot.wd_id == event.wd_id, SourceSnapshot.revision == event.previous_revision)
            .one_or_none()
        )
        current_snap = (
            db.query(SourceSnapshot)
            .filter(SourceSnapshot.wd_id == event.wd_id, SourceSnapshot.revision == event.current_revision)
            .one_or_none()
        )
        previous_hash = previous_snap.document_hash if previous_snap else None
        current_hash = current_snap.document_hash if current_snap else event.document_hash
    return TEMPLATES.TemplateResponse(
        request,
        "case_detail.html",
        _base(
            request,
            case=case,
            contract=contract,
            event=event,
            versions=versions,
            latest=latest,
            evidence=evidence,
            billing=billing,
            mods=mods,
            previous_rate=previous_rate,
            current_rate=current_rate,
            previous_hash=previous_hash,
            current_hash=current_hash,
            days_remaining=_days_remaining(case.filing_deadline_date, date.today()),
        ),
    )


@app.get("/cases/{case_id}/claim.csv")
def claim_csv(case_id: str, db: Session = Depends(get_db)) -> Response:
    if db.query(AdjustmentCase).filter(AdjustmentCase.case_id == case_id).one_or_none() is None:
        raise HTTPException(status_code=404, detail=f"Case {case_id} is not in this workspace.")
    body = Agent3Executor().claim_csv(db, case_id)
    return Response(
        content=body,
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{case_id}-far-52-222-43-claim.csv"'},
    )


@app.get("/cases/{case_id}/evidence.json")
def evidence_json(case_id: str, db: Session = Depends(get_db)) -> Response:
    if db.query(AdjustmentCase).filter(AdjustmentCase.case_id == case_id).one_or_none() is None:
        raise HTTPException(status_code=404, detail=f"Case {case_id} is not in this workspace.")
    import json

    body = json.dumps(Agent3Executor().evidence_dossier(db, case_id), indent=2)
    return Response(
        content=body,
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="{case_id}-evidence.json"'},
    )


@app.get("/cases/{case_id}/evidence.html", response_class=HTMLResponse)
def evidence_html(case_id: str, db: Session = Depends(get_db)) -> HTMLResponse:
    if db.query(AdjustmentCase).filter(AdjustmentCase.case_id == case_id).one_or_none() is None:
        raise HTTPException(status_code=404, detail=f"Case {case_id} is not in this workspace.")
    return HTMLResponse(Agent3Executor().evidence_html(db, case_id))


@app.get("/prospects", response_class=HTMLResponse)
def prospects(request: Request) -> HTMLResponse:
    cards = Agent1Hunter().prospect_audit()
    letters = [
        cold_email(
            company=card.recipient_name,
            award_id=card.award_id,
            agency=card.agency_name,
            county=card.county,
            state=card.state,
            hourly_delta=card.hourly_delta,
        )
        for card in cards
    ]
    return TEMPLATES.TemplateResponse(
        request,
        "prospects.html",
        _base(request, cards=list(zip(cards, letters))),
    )


@app.get("/upload", response_class=HTMLResponse)
def upload_form(request: Request, db: Session = Depends(get_db)) -> HTMLResponse:
    contracts = db.query(Contract).order_by(Contract.contract_id).all()
    return TEMPLATES.TemplateResponse(
        request,
        "upload.html",
        _base(request, contracts=contracts, scrubbed=None, stripped=0, batch_hash="", error=""),
    )


@app.post("/upload", response_class=HTMLResponse)
def upload_payroll(
    request: Request,
    contract_id: str = Form(...),
    payroll_csv: str = Form(""),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    contracts = db.query(Contract).order_by(Contract.contract_id).all()
    contract = db.query(Contract).filter(Contract.contract_id == contract_id).one_or_none()
    if contract is None:
        return TEMPLATES.TemplateResponse(
            request,
            "upload.html",
            _base(request, contracts=contracts, scrubbed=None, stripped=0, batch_hash="", error="Choose a monitored contract."),
            status_code=400,
        )
    try:
        rows, stripped, batch_hash = PrivacyScrubber().scrub_csv(payroll_csv, contract.tenant_id)
    except ValueError as exc:
        return TEMPLATES.TemplateResponse(
            request,
            "upload.html",
            _base(request, contracts=contracts, scrubbed=None, stripped=0, batch_hash="", error=str(exc)),
            status_code=400,
        )
    today = date.today()
    for row in rows:
        db.add(
            PayrollRow(
                tenant_id=contract.tenant_id,
                contract_id=contract.contract_id,
                worker_hash=row.worker_hash,
                occupation_code=row.occupation_code,
                pay_period_start=row.pay_period_start or today.replace(day=1),
                pay_period_end=row.pay_period_end or today,
                eligible_hours=row.eligible_hours,
                actual_prev_wage=row.actual_prev_wage,
                actual_new_wage=row.actual_new_wage,
                actual_prev_hw=row.actual_prev_hw,
                actual_new_hw=row.actual_new_hw,
                ingested_at=utcnow(),
            )
        )
    db.commit()
    return TEMPLATES.TemplateResponse(
        request,
        "upload.html",
        _base(
            request,
            contracts=contracts,
            scrubbed=rows,
            stripped=stripped,
            batch_hash=batch_hash,
            error="",
            saved_contract=contract.contract_id,
        ),
    )


@app.get("/unsubscribe", response_class=HTMLResponse)
def unsubscribe(request: Request) -> HTMLResponse:
    return TEMPLATES.TemplateResponse(request, "unsubscribe.html", _base(request))


def create_prospect_audit() -> dict[str, object]:
    """Offline scheduled entry point. Prints a count; it does not send mail."""
    from app.seed import scheduled_hunter_summary

    return scheduled_hunter_summary()


def _html_escape(value: str) -> str:
    return value.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
