# OptionMargin — Autonomous Contract Margin Recovery Engine

**OptionMargin** is an autonomous FinOps & GovCon compliance engine built for US Federal Service Contractors (initial wedge: **NAICS 561720 Janitorial Services**). It continuously monitors Department of Labor (DOL) Service Contract Labor Standards (SCLS / McNamara-O'Hara Service Contract Act) Wage Determinations (WDs), connects them to active Federal Contracts, Standard Form 30 (SF-30) Modifications, Zero-PII Payroll registers, and Billing records, and deterministically computes exact price adjustment entitlements under **FAR 52.222-43**.

## Key Capabilities & Regulatory Safeguards

1. **Applicability Trigger & Pre-Option Radar (`Agent 1: Hunter`)**
   - Dual SHA-256 hashing (`raw_content_hash` vs. `semantic_rate_hash`) separates HTML formatting noise (`IGNORE`) from true rate increases.
   - Enforces FAR 52.222-43 applicability: public WD updates remain in `POTENTIAL` until incorporated via an SF-30 modification, while automatically flagging contracts within **60–90 days** of an upcoming Option Period (`is_pre_option_alert = True`).
   - Built-in **USAspending Sniper** identifies expiring NAICS 561720 contracts for zero-touch prospect audits.

2. **Deterministic `Decimal` FAR 52.222-43 Quant Engine (`Agent 2: Quant`)**
   - Zero `float` usage anywhere in financial calculations; strictly enforces `decimal.Decimal` with `ROUND_HALF_UP`.
   - **Eligible Wage Delta Formula:**
     $$\Delta W_{\text{eligible}} = \max\left(0.00, \min(W_{\text{act\_new}}, W_{\text{req\_new}}) - W_{\text{prev}}\right)$$
   - Strictly excludes voluntary raises above $W_{\text{req\_new}}$ and yields `0.00` when $W_{\text{prev}} \ge W_{\text{req\_new}}$.
   - **Accompanying Statutory Add-Ons:** Computes FICA (`7.65%` default), FUTA, SUTA, and Workers' Compensation strictly on eligible wage deltas.
   - **Strict FAR 52.222-43(d) Exclusion:** Overhead (`0.00`), G&A (`0.00`), and Profit (`0.00`) are hard-blocked at the schema, engine, and database constraints levels.
   - **30-Day Notification Clock:** Independently tracks `source_published_at`, `verified_receipt_date`, and `written_extension_date`.
   - **Fail-Closed State Gates:** `ARCHIVE`, `IGNORE`, `POTENTIAL`, `INSUFFICIENT_DATA`, `SUPPORTED`.

3. **Transactional Outbox, Evidence Package & Billing Reconciler (`Agent 3: Executor`)**
   - Idempotent transactional outbox pattern (`idempotency_key`) prevents duplicate notifications or claim generations.
   - Every input in a `SUPPORTED` claim is cryptographically and structurally linked to a verbatim `EvidenceSpan` (WD revision, SF-30 clause, scrubbed payroll batch, statutory tax notice).
   - Tracks full lifecycle progression: `DETECTED -> SUPPORTED -> SUBMITTED -> AGREED -> BILLED -> PAID`.
   - Includes `SampleGenerator` (`task_type = "prospect_audit"`) for the self-selling acquisition loop.

## Quickstart

```bash
pip install -r requirements.txt
pytest -v
uvicorn app.main:app --reload --port 8000
```
