# AI-Powered Food Waste Management Platform
### Surplus Identification & Redistribution Optimization
**Infosys Springboard Virtual Internship 7.0 — Batch 4 (AI Domain)** · *Milestone 2*

---

## Project Overview

Full-stack platform that minimises food waste across restaurants, supermarkets, and caterers and routes surplus food to NGOs.  
**Stack:** Django 6 · SQLite/Supabase PostgreSQL · FastAPI · PyTorch LSTM · Prophet · Bootstrap 5

---

## Quick Start

### Prerequisites
- Python 3.11+
- Git

### 1 — Clone & create virtual environment

```bash
git clone <repo-url>
cd infosys-project
python -m venv .venv
# Windows
.venv\Scripts\activate
# macOS/Linux
source .venv/bin/activate
```

### 2 — Install dependencies

```bash
# Django web app
pip install -r requirements.txt

# ML microservice (separate venv recommended)
cd ml-service
pip install -r requirements.txt
cd ..
```

### 3 — Configure environment variables

```bash
# Django side
cp .env.example .env
# Fill in: SECRET_KEY, DB_*, ML_SERVICE_API_KEY

# ML service side
cp ml-service/.env.example ml-service/.env
# Fill in: API_KEY (must match ML_SERVICE_API_KEY above)
# Generate a strong key: openssl rand -hex 32
```

### 4 — Run Django migrations

```bash
python manage.py migrate
python manage.py createsuperuser   # optional
```

### 5 — Generate synthetic ML data & train models

```bash
cd ml-service

# Generate synthetic transaction data (365 days, 3 businesses)
python data/generate_data.py --days 365 --output-dir data

# Train Prophet + LSTM models for all 6 categories (~2-3 min on CPU)
python models/train_and_eval.py --data data/daily_transactions.csv

cd ..
```

Expected output:
```
[OK] Metrics saved to: models/metrics.json
[OK] Forecast comparison plots saved to: reports/
[OK] Trained models saved to: models/saved/
```

### 6 — Run the services

Open **two terminals**:

**Terminal 1 — Django web app (port 8000):**
```bash
# Windows
.venv\Scripts\activate
python manage.py runserver
```

**Terminal 2 — FastAPI ML service (port 8001):**
```bash
cd ml-service
# Windows
..\..\.venv\Scripts\activate
uvicorn api.main:app --host 127.0.0.1 --port 8001 --reload
```

Access:
- Web app: http://127.0.0.1:8000
- ML API docs: http://127.0.0.1:8001/docs

---

## Environment Variables

### Django (`.env`)

| Variable | Required | Description |
|:---|:---|:---|
| `SECRET_KEY` | Yes | Django secret key — generate with `python -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"` |
| `DEBUG` | No | `True` for development (default), `False` for production |
| `DB_NAME` | Yes | Supabase/PostgreSQL database name |
| `DB_USER` | Yes | Database user |
| `DB_PASSWORD` | Yes | Database password |
| `DB_HOST` | Yes | Database host |
| `DB_PORT` | No | Default `5432` |
| `ML_SERVICE_URL` | No | FastAPI service URL, default `http://127.0.0.1:8001` |
| `ML_SERVICE_API_KEY` | Yes | Must match `API_KEY` in `ml-service/.env` |
| `ML_SERVICE_TIMEOUT` | No | Request timeout seconds, default `4.0` |

### ML Service (`ml-service/.env`)

| Variable | Required | Description |
|:---|:---|:---|
| `API_KEY` | Yes | Strong random secret — `openssl rand -hex 32`. Service refuses to start if missing or set to the known default. |
| `ENVIRONMENT` | No | `development` or `production` |
| `ALLOWED_BUSINESS_IDS` | No | Comma-separated tenant IDs the key may access, e.g. `biz_001,biz_002`. Empty = dev mode (all IDs accepted with warning). |

---

## Project Structure

```
infosys-project/
├── food_management/          # Django app — inventory, surplus, donations
│   ├── models.py             # InventoryItem, SurplusListing, DonationRequest, Transaction
│   ├── views.py              # All web views (scoped by business/user)
│   ├── ml_client.py          # HTTP client to ML service with fallback
│   └── templates/
├── core/                     # User profiles, gamification, RBAC
├── food_waste_manager/       # Django settings, urls, wsgi
├── ml-service/               # FastAPI AI microservice
│   ├── api/                  # main.py, config.py, scheduler.py, schemas.py
│   ├── models/               # Prophet + LSTM forecasters, train_and_eval.py
│   ├── risk/                 # risk_scorer.py (0-100 waste risk)
│   ├── reorder/              # optimizer.py (safety stock + capacity)
│   ├── data/                 # generate_data.py, preprocess.py
│   ├── tests/                # 39 unit + integration tests
│   ├── reports/              # Forecast comparison plots (PNG)
│   └── Dockerfile
├── AUDIT_REPORT.md           # Full feature audit, issues, and plan
├── .env.example              # Template — copy to .env
└── requirements.txt
```

---

## API Reference (ML Service)

All endpoints except `/health` require header: `X-API-Key: <your-key>`

| Method | Endpoint | Description |
|:---|:---|:---|
| GET | `/health` | Service liveness + loaded model list |
| POST | `/predict/demand` | Daily demand forecast (Prophet / LSTM / best) |
| POST | `/risk/score` | Real-time waste risk score 0–100 |
| GET | `/risk/batch/{business_id}` | Tenant batch risk assessment |
| POST | `/reorder/recommend` | Smart reorder quantity with reasoning |
| GET | `/models/metrics` | MAE / RMSE / MAPE vs naive baseline |

Full interactive docs: http://127.0.0.1:8001/docs

---

## Running Tests

```bash
# ML service tests (39 tests)
cd ml-service
pytest tests/ -q --tb=short

# Django tests
cd ..
python manage.py test food_management
```

---

## Demo Flow

```
1. Register as "business" user at /accounts/register/
2. Add bakery item expiring in 2 days → risk auto-sets to "critical"
3. Dashboard shows expiry alert and AI risk prediction
4. POST /risk/score → score ~90, Critical, NGO donation recommendation
5. POST /reorder/recommend → order qty calculated from trained LSTM model
6. Import CSV (10 items) → row-wise error report shown on screen
7. GET /risk/batch/biz_001 → full tenant batch risk report
8. GET /models/metrics → benchmark comparison (MAE/RMSE/MAPE)
```

---

## Milestone Status

| Milestone | Status |
|:---|:---|
| M1 — Inventory & Expiry Tracking | ✅ Core complete (POS API, barcode scan: P1) |
| M2 — AI Waste Prediction Engine | ✅ Complete (Prophet, LSTM, risk score, reorder, batch scheduler) |
| M3 — Marketplace, NGO matching, cloud deploy | 🔜 Planned |
