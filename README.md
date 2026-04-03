---
title: ForensicAuditEnv
emoji: 🔍
colorFrom: blue
colorTo: green
sdk: docker
pinned: false
license: mit
---

# ForensicAuditEnv

A production-ready, OpenEnv-compliant reinforcement learning environment that simulates forensic accounting workflows with multi-source financial data. AI agents investigate General Ledger (GL) records, Sub-Ledger (SL) records, financial statements, and narrative reports (10-K/10-Q style) to detect anomalies, reconcile discrepancies, and issue evidence-backed verdicts.

## Architecture

```
Agent
  │
  ▼ HTTP (JSON)
FastAPI Server (:8000)
  │
  ▼
ForensicAuditEnv
  ├── NavigateHandler ──────► JSON Financial Docs
  │                           (income_statement, balance_sheet,
  │                            cashflow, narrative)
  ├── LedgerQueryEngine ────► SQLite DBs
  │                           (ledger.db ◄──► sub_ledger.db)
  ├── EvidenceLinker ───────► Scratchpad
  ├── VerdictHandler ───────► Task1/2/3 Graders
  └── RewardComputer ───────► Shaped Reward [-2.0, +3.0]

Data Layer:
  GL ◄──────────────────────► SL (Accounts Payable/Receivable)
   │                           │
   └──► Financial Statements ◄─┘
              │
              └──► MD&A Narrative (10-K/10-Q)
```

## Quickstart

### Local

```bash
pip install -r requirements.txt
python src/data_generator.py          # generate synthetic data
uvicorn src.main:app --port 8000      # start server
```

### Docker (local)

```bash
docker build -t forensic-audit-env .
docker run -p 8000:7860 forensic-audit-env
# Data is auto-generated inside the image at build time
```

If port 8000 is taken:
```bash
docker run -p 8001:7860 forensic-audit-env
```

### Windows (PowerShell)

```powershell
py -m pip install -r requirements.txt
py src/data_generator.py
uvicorn src.main:app --port 8000
```

## Deploy to Hugging Face Spaces

1. Go to [huggingface.co](https://huggingface.co) → New Space
2. Choose **Docker** SDK, set visibility
3. Connect your GitHub repo or upload files
4. The Space will build and expose your API at:
   `https://<your-username>-<space-name>.hf.space`

Test after deployment:
```bash
curl https://<your-space>.hf.space/
# {"status":"ok","name":"forensic-audit-env","version":"1.0.0"}

curl -X POST https://<your-space>.hf.space/reset \
  -H "Content-Type: application/json" \
  -d '{"company_id": "company_4", "task_id": 1}'
```

Set `ENV_BASE_URL` when running inference against HF:
```bash
export ENV_BASE_URL=https://<your-space>.hf.space
python inference.py
```

## Push to GitHub

```bash
cd forensic_audit_env
git init
git add .
git commit -m "initial commit"
git branch -M main
git remote add origin https://github.com/<your-username>/forensic-audit-env.git
git push -u origin main
```

## API Reference

### Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/` | Health check |
| POST | `/reset` | Start new episode |
| POST | `/step` | Submit action |
| GET | `/state` | Get current observation |

### POST /reset

```json
{
  "company_id": "company_4",
  "task_id": 1,
  "force": false
}
```

Returns `AuditObservation`. Raises `409` if episode active without `force: true`.

### POST /step

Submit one of the four action types:

| Action | Fields | Description |
|--------|--------|-------------|
| `navigate` | `view` | Switch to a financial view |
| `query_ledger` | `filters` | Query GL or SL with filters |
| `link_evidence` | `source_id`, `target_id`, `relationship` | Add to evidence chain |
| `issue_verdict` | `conclusion`, `rationale`, `evidence_chain` | End episode with verdict |

Returns `StepResponse`: `{observation, reward, done, info}`.

### Action Examples

```json
// Navigate
{"action_type": "navigate", "view": "income_statement"}

// Query ledger
{"action_type": "query_ledger", "filters": {
  "account_code": "Accounts Payable",
  "date_from": "2024-01-01",
  "date_to": "2024-03-31"
}}

// Link evidence
{"action_type": "link_evidence",
  "source_id": "operating_margin_0.235",
  "target_id": "narrative_n7",
  "relationship": "supports"}

// Issue verdict
{"action_type": "issue_verdict",
  "conclusion": "non_gaap_manipulation",
  "rationale": "AR spike of $80M with negative OCF indicates revenue recognition manipulation.",
  "evidence_chain": [
    {"id": "income_statement_net_income", "value": 50000000},
    {"id": "cashflow_operating_cash", "value": -30000000},
    {"id": "balance_sheet_ar", "value": 80000000}
  ]}
```

### Observation Fields

| Field | Type | Description |
|-------|------|-------------|
| `current_view` | string | Active financial view |
| `visible_data` | dict | Data for current view |
| `scratchpad` | list | Linked evidence chain |
| `available_actions` | list | Valid action strings |
| `anomaly_alerts` | list | System-flagged issues |
| `investigation_progress` | float | 0.0–1.0 episode progress |

## Reward Function

| Event | Delta |
|-------|-------|
| Navigate to new view | +0.1 |
| Query returns results | +0.3 |
| Valid evidence link | +0.2 |
| Correct verdict + complete evidence | +1.0 |
| Correct verdict + incomplete evidence | +0.5 |
| Repeated action (loop) | -0.1 |
| Query returns 0 results | -0.05 |
| Contradictory evidence link | -0.15 |

Total reward clamped to **[-2.0, +3.0]** per episode.

## Tasks

### Task 1 — KPI Extraction & Multi-Modal Linking (Easy)
- **Company**: FinanceHub (`company_4`)
- **Objective**: Find Operating Margin (23.5%) in income statement, link to narrative chunk `n7`
- **Scoring**: 1.0 if both extracted and linked correctly, else 0.0

### Task 2 — Cross-System Reconciliation Audit (Medium)
- **Company**: RetailCo (`company_2`)
- **Objective**: Find 12 duplicate invoice payments in AP sub-ledger
- **Scoring**: F1-style `(precision + recall) / 2` against 12 ground-truth transaction IDs

### Task 3 — Narrative vs. Numeric Deception Detection (Hard)
- **Company**: TechCorp (`company_1`)
- **Objective**: Prove "15% delivery growth" narrative is non-GAAP manipulation
- **Evidence chain**: Net Income +$50M, OCF -$30M, AR +$80M
- **Scoring**: 1.0 (all evidence + correct verdict + rationale), 0.7 (no rationale), 0.4 (wrong verdict), 0.0 (missing evidence)

## Data Generation

```bash
python src/data_generator.py [output_dir]
```

Generates 5 synthetic companies with planted anomalies:

| Company | ID | Anomaly |
|---------|-----|---------|
| TechCorp | company_1 | AR spike + OCF decline (Task 3) |
| RetailCo | company_2 | 12 duplicate invoice payments (Task 2) |
| ManufacturingInc | company_3 | Negative OCF with "strong cash" narrative |
| FinanceHub | company_4 | Operating margin 23.5% linked to narrative n7 (Task 1) |
| HealthcarePlus | company_5 | Clean baseline |

## Baseline Agent

The agent uses an OpenAI-compatible client and supports HuggingFace router, OpenAI, or any compatible API.

### Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `HF_TOKEN` | HuggingFace token (preferred) | — |
| `API_KEY` | Fallback API key | `none` |
| `API_BASE_URL` | LLM API base URL | `https://router.huggingface.co/v1` |
| `MODEL_NAME` | Model to use | `Qwen/Qwen2.5-72B-Instruct` |
| `ENV_BASE_URL` | Environment server URL | `http://localhost:8000` |

### Linux / macOS

```bash
# HuggingFace router
export HF_TOKEN=hf_...
export MODEL_NAME=Qwen/Qwen2.5-72B-Instruct
export ENV_BASE_URL=http://localhost:8000
python inference.py

# OpenAI
export API_KEY=sk-...
export API_BASE_URL=https://api.openai.com/v1
export MODEL_NAME=gpt-4o
python inference.py

# Run specific task
python inference.py --task 1 --company company_4

# Heuristic mode (no LLM, for testing)
python inference.py  # uses built-in heuristic if no API key configured
```

### Windows (PowerShell)

```powershell
# HuggingFace router
$env:HF_TOKEN = "hf_..."
$env:MODEL_NAME = "Qwen/Qwen2.5-72B-Instruct"
$env:ENV_BASE_URL = "http://localhost:8001"  # if Docker mapped to 8001
py inference.py

# Run specific task
py inference.py --task 1 --company company_4
```

### Baseline Scores

| Task | Min Target | Expected (Qwen2.5-72B) | Expected (GPT-4o) |
|------|-----------|------------------------|-------------------|
| Task 1 | 0.6 | ~0.9 | ~0.9 |
| Task 2 | 0.4 | ~0.6 | ~0.7 |
| Task 3 | 0.3 | ~0.5 | ~0.6 |

## Testing

```bash
# Linux / macOS
pytest tests/ -v

# Windows
py -m pytest tests/ -v
```

80 tests covering: environment lifecycle, API routes, graders, reward computation, ledger queries, data generation, and model round-trips.

## Real-World Utility

ForensicAuditEnv trains agents for:
- **Fraud detection**: Identifying duplicate payments, fictitious vendors, round-trip transactions
- **GAAP compliance verification**: Cross-checking narrative claims against numeric statements
- **Financial statement auditing**: Reconciling GL/SL discrepancies with reported figures
- **Forensic accounting automation**: Systematic evidence gathering and chain-of-custody documentation
