"""Automated Test Suite covering all 8 Golden Edge Cases for OptionMargin (FAR 52.222-43).

Compatible with both `pytest` and standard `python3 -m unittest` runners.
"""

import unittest
from datetime import date
from decimal import Decimal

from app.config import q2
from app.database import HAS_SQLALCHEMY, Base
from app.models import AdjustmentCase, Contract, Organization
from app.schemas import (
    LifecycleStatus,
    ScrubbedPayrollLine,
    StateGate,
    StatutoryTaxConfig,
)
from app.agents.agent1_hunter import Agent1Hunter
from app.agents.agent2_quant import Agent2Quant
from app.agents.agent3_executor import Agent3Executor
from app.services.privacy_scrubber import PrivacyScrubber
from app.services.sf30_parser import SF30Parser
from app.services.sample_generator import SampleGenerator


def _make_test_session():
    if HAS_SQLALCHEMY:
        from sqlalchemy import create_engine  # type: ignore
        from sqlalchemy.orm import sessionmaker  # type: ignore
        eng = create_engine("sqlite:///:memory:", future=True)
        Base.metadata.create_all(bind=eng)
        return sessionmaker(bind=eng, autoflush=False, autocommit=False)()
    else:
        from app.database import create_isolated_session
        return create_isolated_session()


def _sample_wds():
    hunter = Agent1Hunter()
    old_wd = hunter.parse_wd_document(
        raw_text="WD 2015-4281 Rev 26\n23470 - Janitor 16.50\nHEALTH & WELFARE: $4.98\nEO 13706: $4.57\n",
        wd_number="2015-4281",
        revision_number=26,
        locality_state="VA",
        locality_county="Arlington",
        source_published_at=date(2025, 6, 15),
    )
    new_wd = hunter.parse_wd_document(
        raw_text="WD 2015-4281 Rev 27\n23470 - Janitor 18.20\nHEALTH & WELFARE: $5.36\nEO 13706: $4.98\n",
        wd_number="2015-4281",
        revision_number=27,
        locality_state="VA",
        locality_county="Arlington",
        source_published_at=date(2026, 9, 15),
    )
    diff = hunter.diff_wage_determinations(old_wd, new_wd)
    return hunter, old_wd, new_wd, diff


def test_golden_case_1_eligible_entitlement_and_voluntary_raise_exclusion():
    """Golden Case 1: Standard Eligible Entitlement + Voluntary Raise Exclusion + Strict 0.00 OH/G&A/Profit.
    W_prev = 16.50, W_req_new = 18.20, W_act_new = 19.00.
    Eligible delta must be min(19.00, 18.20) - 16.50 = 1.70/hr; voluntary 0.80/hr strictly excluded.
    """
    _, old_wd, new_wd, diff = _sample_wds()
    sf30 = SF30Parser().parse(
        sf30_text="MOD P00004: Exercise Option Period 2 under FAR 52.217-9 and incorporate WD 2015-4281 Rev 27 per FAR 52.222-43.",
        effective_date=date(2026, 10, 1),
        verified_receipt_date=date(2026, 10, 10),
    )
    payroll = [
        ScrubbedPayrollLine(
            worker_hash="WRK-AA11BB22CC33DD44",
            internal_job_code="JAN-1",
            scls_occupation_code="23470",
            regular_hours=Decimal("1000.0000"),
            overtime_hours=Decimal("0.0000"),
            vacation_holiday_hours=Decimal("0.0000"),
            actual_prev_wage_rate=Decimal("16.5000"),
            actual_new_wage_rate=Decimal("19.0000"),
            actual_prev_hw_rate=Decimal("4.5700"),
            actual_new_hw_rate=Decimal("4.9800"),
        )
    ]

    quant = Agent2Quant()
    res = quant.evaluate_case(
        contract_wd_number="2015-4281",
        contract_next_option_date=date(2027, 10, 1),
        is_eo13706_applicable=True,
        has_complex_cba=False,
        old_wd=old_wd,
        new_wd=new_wd,
        wd_diff=diff,
        sf30_mod=sf30,
        payroll_lines=payroll,
        tax_config=StatutoryTaxConfig(),
        evaluation_date=date(2026, 10, 25),
    )

    assert res.state_gate == StateGate.SUPPORTED
    assert res.total_eligible_wage_delta == Decimal("1700.00")
    assert res.voluntary_raise_excluded_amount == Decimal("800.00")
    assert res.total_eligible_hw_delta == Decimal("410.00")
    assert res.total_accompanying_taxes_wc == Decimal("229.50")
    assert res.overhead_excluded_amount == Decimal("0.00")
    assert res.ga_excluded_amount == Decimal("0.00")
    assert res.profit_excluded_amount == Decimal("0.00")
    assert res.total_claim_amount == Decimal("2339.50")
    assert len(res.evidence_spans) >= 4


def test_golden_case_2_already_paying_above_new_wd_minimum():
    """Golden Case 2: Contractor already paid W_prev >= W_req_new ($19.50 >= $18.20).
    Mandatory Wage Delta must be strictly Decimal('0.0000').
    """
    _, old_wd, new_wd, diff = _sample_wds()
    sf30 = SF30Parser().parse(
        sf30_text="MOD P00005: Incorporate WD 2015-4281 Rev 27 under FAR 52.222-43.",
        effective_date=date(2026, 10, 1),
        verified_receipt_date=date(2026, 10, 10),
    )
    payroll = [
        ScrubbedPayrollLine(
            worker_hash="WRK-HIGHWAGE0001",
            internal_job_code="JAN-SR",
            scls_occupation_code="23470",
            regular_hours=Decimal("1000.0000"),
            actual_prev_wage_rate=Decimal("19.5000"),
            actual_new_wage_rate=Decimal("20.0000"),
            actual_prev_hw_rate=Decimal("5.0000"),
            actual_new_hw_rate=Decimal("5.0000"),
        )
    ]
    res = Agent2Quant().evaluate_case(
        contract_wd_number="2015-4281",
        contract_next_option_date=date(2027, 10, 1),
        is_eo13706_applicable=True,
        has_complex_cba=False,
        old_wd=old_wd,
        new_wd=new_wd,
        wd_diff=diff,
        sf30_mod=sf30,
        payroll_lines=payroll,
        tax_config=StatutoryTaxConfig(),
        evaluation_date=date(2026, 10, 20),
    )
    assert res.state_gate == StateGate.SUPPORTED
    assert res.total_eligible_wage_delta == Decimal("0.00")
    assert res.total_eligible_hw_delta == Decimal("0.00")
    assert res.total_accompanying_taxes_wc == Decimal("0.00")
    assert res.total_claim_amount == Decimal("0.00")
    assert res.voluntary_raise_excluded_amount == Decimal("500.00")


def test_golden_case_3_formatting_only_html_change_triggers_ignore_gate():
    """Golden Case 3: Public WD HTML/whitespace change with zero semantic rate diff -> StateGate.IGNORE."""
    hunter = Agent1Hunter()
    wd_v1 = hunter.parse_wd_document(
        raw_text="WD 2015-4281 Rev 26\n23470 - Janitor 16.50\nHEALTH & WELFARE: $4.98\nEO 13706: $4.57\n",
        wd_number="2015-4281",
        revision_number=26,
        locality_state="VA",
        locality_county="Arlington",
        source_published_at=date(2025, 6, 15),
    )
    wd_v2_noise = hunter.parse_wd_document(
        raw_text="   WD 2015-4281 Rev 26 (SAM.GOV REFORMAT)   \n\n  23470 - Janitor    16.50  \nHEALTH & WELFARE: $4.98\nEO 13706: $4.57\n",
        wd_number="2015-4281",
        revision_number=26,
        locality_state="VA",
        locality_county="Arlington",
        source_published_at=date(2026, 9, 15),
    )
    diff = hunter.diff_wage_determinations(wd_v1, wd_v2_noise)
    assert diff.raw_hash_changed is True
    assert diff.semantic_hash_changed is False
    assert diff.is_formatting_only is True

    res = Agent2Quant().evaluate_case(
        contract_wd_number="2015-4281",
        contract_next_option_date=date(2027, 1, 1),
        is_eo13706_applicable=True,
        has_complex_cba=False,
        old_wd=wd_v1,
        new_wd=wd_v2_noise,
        wd_diff=diff,
        sf30_mod=None,
        payroll_lines=None,
        tax_config=StatutoryTaxConfig(),
        evaluation_date=date(2026, 10, 30),
    )
    assert res.state_gate == StateGate.IGNORE
    assert res.total_claim_amount == Decimal("0.00")


def test_golden_case_4_mid_year_wd_without_sf30_and_pre_option_alert():
    """Golden Case 4: Higher public WD published 75 days before Option Period, but no SF-30 mod yet.
    Must route to StateGate.POTENTIAL and set is_pre_option_alert = True.
    """
    _, old_wd, new_wd, diff = _sample_wds()
    res = Agent2Quant().evaluate_case(
        contract_wd_number="2015-4281",
        contract_next_option_date=date(2027, 1, 13),
        is_eo13706_applicable=True,
        has_complex_cba=False,
        old_wd=old_wd,
        new_wd=new_wd,
        wd_diff=diff,
        sf30_mod=None,
        payroll_lines=None,
        tax_config=StatutoryTaxConfig(),
        evaluation_date=date(2026, 10, 30),
    )
    assert res.state_gate == StateGate.POTENTIAL
    assert res.is_pre_option_alert is True
    assert res.days_until_option == 75
    assert res.total_claim_amount == Decimal("0.00")


def test_golden_case_5_30_day_notification_clock_and_written_extension():
    """Golden Case 5: FAR 52.222-43(f) 30-day clock tracked from verified_receipt_date (not source_published_at),
    plus CO written extension override.
    """
    _, old_wd, new_wd, diff = _sample_wds()
    payroll = [
        ScrubbedPayrollLine(
            worker_hash="WRK-CLOCK001",
            internal_job_code="JAN-1",
            scls_occupation_code="23470",
            regular_hours=Decimal("100.0000"),
            actual_prev_wage_rate=Decimal("16.5000"),
            actual_new_wage_rate=Decimal("18.2000"),
            actual_prev_hw_rate=Decimal("4.5700"),
            actual_new_hw_rate=Decimal("4.9800"),
        )
    ]
    sf30_no_ext = SF30Parser().parse(
        sf30_text="MOD P00006: Incorporate WD 2015-4281 Rev 27.",
        effective_date=date(2026, 10, 1),
        verified_receipt_date=date(2026, 10, 1),
    )
    res_late = Agent2Quant().evaluate_case(
        contract_wd_number="2015-4281",
        contract_next_option_date=date(2027, 10, 1),
        is_eo13706_applicable=True,
        has_complex_cba=False,
        old_wd=old_wd,
        new_wd=new_wd,
        wd_diff=diff,
        sf30_mod=sf30_no_ext,
        payroll_lines=payroll,
        tax_config=StatutoryTaxConfig(),
        evaluation_date=date(2026, 11, 5),
    )
    assert res_late.is_late_notice_flagged is True
    assert res_late.days_remaining_30d_clock == -5

    sf30_with_ext = SF30Parser().parse(
        sf30_text="MOD P00006: Incorporate WD 2015-4281 Rev 27.",
        effective_date=date(2026, 10, 1),
        verified_receipt_date=date(2026, 10, 1),
        written_extension_date=date(2026, 11, 15),
    )
    res_ext = Agent2Quant().evaluate_case(
        contract_wd_number="2015-4281",
        contract_next_option_date=date(2027, 10, 1),
        is_eo13706_applicable=True,
        has_complex_cba=False,
        old_wd=old_wd,
        new_wd=new_wd,
        wd_diff=diff,
        sf30_mod=sf30_with_ext,
        payroll_lines=payroll,
        tax_config=StatutoryTaxConfig(),
        evaluation_date=date(2026, 11, 5),
    )
    assert res_ext.is_late_notice_flagged is False
    assert res_ext.days_remaining_30d_clock == 10


def test_golden_case_6_insufficient_data_gate_and_overtime_hw_exclusion():
    """Golden Case 6: Fail-closed INSUFFICIENT_DATA when occupation is unmapped or CBA is complex;
    and when SUPPORTED with overtime hours, overtime is excluded from H&W fringe calculation.
    """
    _, old_wd, new_wd, diff = _sample_wds()
    sf30 = SF30Parser().parse(
        sf30_text="MOD P00007: Incorporate WD 2015-4281 Rev 27.",
        effective_date=date(2026, 10, 1),
        verified_receipt_date=date(2026, 10, 15),
    )

    unmapped_payroll = [
        ScrubbedPayrollLine(
            worker_hash="WRK-UNMAPPED",
            internal_job_code="UNKNOWN-99",
            scls_occupation_code=None,
            regular_hours=Decimal("500.0000"),
            actual_prev_wage_rate=Decimal("16.5000"),
            actual_new_wage_rate=Decimal("18.2000"),
            actual_prev_hw_rate=Decimal("4.5700"),
            actual_new_hw_rate=Decimal("4.9800"),
        )
    ]
    res_unmapped = Agent2Quant().evaluate_case(
        contract_wd_number="2015-4281",
        contract_next_option_date=date(2027, 10, 1),
        is_eo13706_applicable=True,
        has_complex_cba=False,
        old_wd=old_wd,
        new_wd=new_wd,
        wd_diff=diff,
        sf30_mod=sf30,
        payroll_lines=unmapped_payroll,
        tax_config=StatutoryTaxConfig(),
        evaluation_date=date(2026, 10, 25),
    )
    assert res_unmapped.state_gate == StateGate.INSUFFICIENT_DATA
    assert res_unmapped.total_claim_amount == Decimal("0.00")

    ot_payroll = [
        ScrubbedPayrollLine(
            worker_hash="WRK-OT001",
            internal_job_code="JAN-1",
            scls_occupation_code="23470",
            regular_hours=Decimal("1000.0000"),
            overtime_hours=Decimal("200.0000"),
            vacation_holiday_hours=Decimal("80.0000"),
            actual_prev_wage_rate=Decimal("16.5000"),
            actual_new_wage_rate=Decimal("18.2000"),
            actual_prev_hw_rate=Decimal("4.5700"),
            actual_new_hw_rate=Decimal("4.9800"),
        )
    ]
    res_ot = Agent2Quant().evaluate_case(
        contract_wd_number="2015-4281",
        contract_next_option_date=date(2027, 10, 1),
        is_eo13706_applicable=True,
        has_complex_cba=False,
        old_wd=old_wd,
        new_wd=new_wd,
        wd_diff=diff,
        sf30_mod=sf30,
        payroll_lines=ot_payroll,
        tax_config=StatutoryTaxConfig(),
        evaluation_date=date(2026, 10, 25),
    )
    assert res_ot.state_gate == StateGate.SUPPORTED
    line = res_ot.ledger_lines[0]
    assert line.eligible_wage_hours == Decimal("1280.0000")
    assert line.eligible_hw_hours == Decimal("1080.0000")
    assert line.overtime_hours_excluded_from_hw == Decimal("200.0000")
    assert line.line_wage_entitlement == q2(Decimal("1.7000") * Decimal("1280.0000"))
    assert line.line_hw_entitlement == q2(Decimal("0.4100") * Decimal("1080.0000"))


def test_golden_case_7_zero_pii_payroll_scrubber_and_float_rejection():
    """Golden Case 7: Zero-PII Payroll Scrubber strips employee names, SSNs, emails, and addresses,
    produces deterministic Worker_Hash, and rejects float inputs across schemas.
    """
    scrubber = PrivacyScrubber(secret_salt="test-salt-2026")
    raw_rows = [
        {
            "employee_name": "Jane Doe",
            "ssn": "987-65-4321",
            "email": "jane.doe@example.com",
            "home_address": "742 Evergreen Terrace",
            "internal_job_code": "JAN-01 (SSN 987-65-4321)",
            "regular_hours": "160.0000",
            "actual_prev_wage_rate": "16.5000",
            "actual_new_wage_rate": "18.2000",
            "actual_prev_hw_rate": "4.5700",
            "actual_new_hw_rate": "4.9800",
        }
    ]
    lines, stripped_count, batch_hash = scrubber.scrub_payroll_rows(
        raw_rows, org_id="org-123", occupation_map={"JAN-01 (SSN [REDACTED])": "23470"}
    )
    assert stripped_count == 4
    assert len(lines) == 1
    serialized = lines[0].model_dump_json()
    assert "Jane Doe" not in serialized
    assert "987-65-4321" not in serialized
    assert "jane.doe@example.com" not in serialized
    assert lines[0].worker_hash.startswith("WRK-")
    assert len(batch_hash) == 64

    lines_2, _, _ = scrubber.scrub_payroll_rows(raw_rows, org_id="org-123")
    assert lines[0].worker_hash == lines_2[0].worker_hash

    raised = False
    try:
        q2(18.20)  # type: ignore[arg-type]
    except TypeError:
        raised = True
    assert raised is True


def test_golden_case_8_agent3_outbox_idempotency_billing_reconciler_and_prospect_audit(db_session=None):
    """Golden Case 8: Transactional Outbox idempotency, full lifecycle progression
    (DETECTED -> SUPPORTED -> SUBMITTED -> AGREED -> BILLED -> PAID), billing variance detection,
    and self-selling Prospect Audit loop (`task_type = "prospect_audit"`).
    """
    session = db_session or _make_test_session()
    executor = Agent3Executor()

    rec1, created1 = executor.enqueue_outbox_task(
        session,
        org_id=None,
        idempotency_key="IDEMP-KEY-001",
        task_type="prospect_audit",
        payload={"piid": "47PM0924C0012"},
    )
    rec2, created2 = executor.enqueue_outbox_task(
        session,
        org_id=None,
        idempotency_key="IDEMP-KEY-001",
        task_type="prospect_audit",
        payload={"piid": "47PM0924C0012"},
    )
    assert created1 is True
    assert created2 is False
    assert rec1.id == rec2.id

    org = Organization(name="Test GovCon Org", uei="UEI123456789")
    session.add(org)
    session.flush()

    contract = Contract(
        org_id=org.id,
        piid="47PM0924C0099",
        agency_name="GSA",
        pop_state="VA",
        pop_county="Arlington",
        wd_number="2015-4281",
        next_option_start_date=date(2027, 10, 1),
    )
    session.add(contract)
    session.flush()

    case = AdjustmentCase(
        org_id=org.id,
        contract_id=contract.id,
        old_wd_id="wd-old",
        new_wd_id="wd-new",
        state_gate=StateGate.SUPPORTED.value,
        lifecycle_status=LifecycleStatus.DETECTED.value,
        total_claim_amount=Decimal("2339.50"),
        gate_reason="Verified",
    )
    session.add(case)
    session.commit()

    for next_stage in [
        LifecycleStatus.SUPPORTED,
        LifecycleStatus.SUBMITTED,
        LifecycleStatus.AGREED,
        LifecycleStatus.BILLED,
        LifecycleStatus.PAID,
    ]:
        case = executor.advance_lifecycle(session, case, next_stage)
        assert case.lifecycle_status == next_stage.value

    recon = executor.reconcile_billing(
        session,
        org_id=org.id,
        case=case,
        executed_mod_number="P00008",
        agreed_amount=Decimal("2339.50"),
        invoice_number="INV-2026-104",
        billed_amount=Decimal("2339.50"),
        billed_at=date(2026, 11, 1),
        paid_amount=Decimal("2339.50"),
        paid_at=date(2026, 11, 15),
    )
    assert recon.variance_amount == Decimal("0.00")
    assert recon.reconciliation_status == "RECONCILED_PAID_IN_FULL"

    teaser = SampleGenerator().build_prospect_audit(
        prospect_company_name="Potomac Facilities Maintenance LLC",
        prospect_uei="PFM998877665",
        contract_piid="GS03P24CD0019",
        agency_name="GSA Public Buildings Service",
        locality="Montgomery County, MD",
        wd_number="2015-4281",
        old_revision=26,
        new_revision=27,
        next_option_date=date(2027, 1, 15),
        old_wd_rate=Decimal("16.50"),
        new_wd_rate=Decimal("18.20"),
        old_hw_rate=Decimal("4.57"),
        new_hw_rate=Decimal("4.98"),
        estimated_janitor_fte=20,
        as_of_date=date(2026, 10, 30),
    )
    assert teaser.task_type == "prospect_audit"
    assert teaser.days_until_option == 77
    assert teaser.estimated_annual_recovery_usd > Decimal("90000.00")
    assert "[REDACTED]" in teaser.redacted_evidence_preview


class TestGoldenEdgeCases(unittest.TestCase):
    """Unittest runner wrapper for all 8 Golden Edge Cases."""

    def test_01_eligible_entitlement_and_voluntary_raise_exclusion(self):
        test_golden_case_1_eligible_entitlement_and_voluntary_raise_exclusion()

    def test_02_already_paying_above_new_wd_minimum(self):
        test_golden_case_2_already_paying_above_new_wd_minimum()

    def test_03_formatting_only_html_change_triggers_ignore_gate(self):
        test_golden_case_3_formatting_only_html_change_triggers_ignore_gate()

    def test_04_mid_year_wd_without_sf30_and_pre_option_alert(self):
        test_golden_case_4_mid_year_wd_without_sf30_and_pre_option_alert()

    def test_05_30_day_notification_clock_and_written_extension(self):
        test_golden_case_5_30_day_notification_clock_and_written_extension()

    def test_06_insufficient_data_gate_and_overtime_hw_exclusion(self):
        test_golden_case_6_insufficient_data_gate_and_overtime_hw_exclusion()

    def test_07_zero_pii_payroll_scrubber_and_float_rejection(self):
        test_golden_case_7_zero_pii_payroll_scrubber_and_float_rejection()

    def test_08_agent3_outbox_idempotency_billing_reconciler_and_prospect_audit(self):
        test_golden_case_8_agent3_outbox_idempotency_billing_reconciler_and_prospect_audit()


if __name__ == "__main__":
    unittest.main(verbosity=2)
