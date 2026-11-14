# OptionMargin

Autonomous FAR 52.222-43 contract margin recovery for US federal service contractors. The first wedge is janitorial work, NAICS 561720, occupation 23470 Janitor.

OptionMargin compares Department of Labor wage determinations, waits for the SF-30 that incorporates a revision, and prices only the mandatory wage delta, the fixed health-and-welfare delta, and statutory payroll tax. Overhead, G&A, and profit are asserted at zero. Names and Social Security numbers are hashed before payroll is stored.

## Run

```bash
pip install -r requirements.txt
pytest -v
uvicorn app.main:app --reload
```

Open http://localhost:8000. The process creates a local SQLite database and seeds janitorial contracts, wage determinations, SF-30 modifications, scrubbed payroll, and billing rows. `supabase_schema.sql` is the Postgres shape, including row-level security on all 14 tables.

Copy `.env.example` to `.env` and replace the placeholder secret names. With no API keys, wage parsing, SF-30 extraction, and the USAspending prospect list use the built-in deterministic fallback.

## Deploy

Render deployment files are not part of this repository. Ship the container with Docker, or use the Railway config already in `railway.json`.

```bash
docker build -t optionmargin .
docker run -p 8000:8000 optionmargin
```

The health check is `GET /api/health`.
