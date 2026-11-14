"""Dashboard actions for the hunter, quant, and executor pipeline."""

from __future__ import annotations

from datetime import timedelta

from sqlalchemy.orm import Session

from app.agents.agent1_hunter import Agent1Hunter
from app.agents.agent3_executor import Agent3Executor
from app.config import ZERO_2, q2
from app.models import BillingMatch, ChangeEvent, DeliveryOutbox, JobRun, utcnow
from app.seed import TENANT_ID

WORKER_ID = "worker-local-1"


def run_pipeline(session: Session) -> dict[str, object]:
    started = utcnow()
    job = JobRun(
        job_type="agent_pipeline",
        status="CLAIMED",
        worker_id=WORKER_ID,
        lease_until=started + timedelta(minutes=15),
        started_at=started,
        metrics_json={},
    )
    session.add(job)
    session.flush()
    hunter = Agent1Hunter()
    old_html = (
        "<html><body><nav>SAM.gov | Sign In</nav><div>Last updated: 2026-01-04T08:00:00Z</div>"
        "<h1>Wage Determination 2015-4281 Revision 26</h1><p>Locality: Arlington County, VA</p>"
        "<p>23470 Janitor 22.40 H&amp;W 4.80</p></body></html>"
    )
    new_html = (
        "<html><body><nav>SAM.gov | Wage Determinations</nav><div>Last updated: 2026-09-01T14:00:00Z</div>"
        "<h1>Wage Determination 2015-4281 Revision 27</h1><p>Locality: Arlington County, VA</p>"
        "<p>23470 Janitor 23.40 H&amp;W 4.98</p></body></html>"
    )
    classification = hunter.classify(
        old_html,
        new_html,
        monitored=True,
        source_url="https://sam.gov/wage-determinations/2015-4281",
    )
    existing = (
        session.query(ChangeEvent)
        .filter(
            ChangeEvent.document_hash == classification.document_hash,
            ChangeEvent.gate_decision == classification.gate_decision,
        )
        .first()
    )
    if existing is None and classification.gate_decision == "ANALYZE":
        hunter.record_change_event(session, classification, observed_at=started, source_published_at=started - timedelta(days=2))
    prospects = hunter.prospect_audit()
    job.status = "COMPLETED"
    job.finished_at = utcnow()
    job.metrics_json = {
        "gate_decision": classification.gate_decision,
        "prospects": len(prospects),
        "rule_pack_version": "US-SCLS-1.0",
    }
    session.commit()
    return {
        "gate_decision": classification.gate_decision,
        "prospects": len(prospects),
        "job_id": job.id,
    }


def simulate_duplicate_webhook(session: Session) -> dict[str, int]:
    executor = Agent3Executor()
    payload = {
        "tenant_id": TENANT_ID,
        "contract_id": "CONTRACT-DEMO",
        "wd_id": "2015-4281",
        "revision": 27,
        "event_type": "WAGE_REVISION",
        "case_id": "CASE-WEBHOOK-001",
        "channel": "WEBHOOK",
        "status": "POTENTIAL",
        "estimated_monthly_exposure_usd": "9600.00",
        "recipient": "https://hooks.example.test/option-margin",
        "evidence_complete": False,
        "missing_fields": ["verified_receipt_date", "applicable_contract_modification"],
        "next_action": "Complete evidence package",
    }
    rows = [executor.run(session, payload) for _ in range(3)]
    key = rows[0].idempotency_key
    from app.models import AdjustmentCase

    return {
        "attempts": 3,
        "outbox_rows": session.query(DeliveryOutbox).filter(DeliveryOutbox.idempotency_key == key).count(),
        "cases": session.query(AdjustmentCase).filter(AdjustmentCase.case_id == "CASE-WEBHOOK-001").count(),
    }


def run_billing_reconciliation(session: Session) -> dict[str, object]:
    executor = Agent3Executor()
    leakage = ZERO_2
    checked = 0
    for match in session.query(BillingMatch).all():
        variance, status = executor.variance_only(
            expected_adjusted_rate=match.expected_adjusted_rate,
            actual_billed_rate=match.actual_billed_rate,
            hours_billed=match.hours_billed,
        )
        match.variance_leakage_usd = variance
        match.reconciliation_status = status
        match.checked_at = utcnow()
        if match.case is not None and status == "UNDERBILLED_LEAKAGE":
            match.case.unbilled_leakage_usd = variance
            match.case.updated_at = utcnow()
            leakage = q2(leakage + variance)
        elif match.case is not None and status == "MATCHED":
            match.case.unbilled_leakage_usd = ZERO_2
            match.case.updated_at = utcnow()
        checked += 1
    session.commit()
    return {"matches": checked, "leakage": f"{leakage:.2f}"}


def duplicate_attempts_skipped(result: dict[str, int]) -> int:
    return result["attempts"] - result["outbox_rows"]
