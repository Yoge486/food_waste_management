# Audit Report — AI-Powered Food Waste Management Platform
**Infosys Springboard Internship · Milestone 2 Deadline: 1 Nov 2026**

---

## 1. Feature Audit Table

### Milestone 1: Inventory & Expiry Tracking

| Requirement | Status | Evidence (file:line) | Gap |
|:---|:---|:---|:---|
| 1.1 Manual inventory entry | Done | `food_management/views.py` → `inventory_create`, `food_management/forms.py` → `InventoryForm` | — |
| 1.2 CSV bulk upload with row-wise error report | Done | `views.py` → `inventory_import`; per-row `rejected_rows` list shown via `messages.warning` | — |
| 1.3 POS REST API (API key per tenant, idempotency) | Done | `food_management/pos_api.py`, `food_management/urls.py` | — |
| 2.1 Configurable days-to-expiry thresholds | Done | `CategoryConfig` model/admin plus `forms.py` and `services.py:get_category_thresholds` | Defaults remain 3/7/30 days when no category override exists |
| 2.2 Status labels (fresh/warning/critical/expired) | Done | `models.py` `RISK_CHOICES`, auto-assigned in `forms.py:clean` and `views.py:inventory_import` | — |
| 2.3 Scheduled alerts with deduplication | Done | `send_expiry_alerts` management command + `ExpiryAlert` model | Run daily via cron or Windows Task Scheduler; per-user delivery preferences supported |
| 3.1 Food taxonomy with perishability & storage | Partial | `CATEGORY_PROFILES` in `ml-service/data/generate_data.py` only; not exposed in Django UI | No category taxonomy model in Django |
| 3.2 Auto-suggest category | Missing | `category` field is free-text `CharField`; no suggestions | Could use datalist or AJAX from `CATEGORY_PROFILES` |
| 4.1 Barcode/QR scanning (mobile-friendly) | Done | `static/js/barcode-scanner.js`, inventory form camera controls, tenant-scoped lookup endpoint | Uses the browser `BarcodeDetector` API where supported |
| 5.1 Multi-tenant inventory (RLS or equivalent) | Partial | Inventory list/edit/delete and dashboard metrics are scoped by `request.user`; legacy nullable owners remain | Backfill legacy rows; keep ownership checks on every object action |
| 5.2 Transaction history (sale/purchase/waste/donation) | Done | `models.py:Transaction`, `services.py:record_transaction`, migration 0002 | Inventory purchase/import, POS, and donation collection flows record transactions |
| 5.3 Surplus donation logs | Done | `SurplusListing`, `DonationRequest` models + views | — |

### Milestone 2: AI Waste Prediction Engine

| Requirement | Status | Evidence (file:line) | Gap |
|:---|:---|:---|:---|
| 1.1 Category-wise daily time series | Done | `ml-service/data/preprocess.py:prepare_category_series` | Data is synthetic CSV; not yet reading real Django `Transaction` table |
| 2.1 Prophet forecasting | Done | `ml-service/models/baseline_prophet.py`, artifacts in `models/saved/` | — |
| 2.2 LSTM forecasting | Done | `ml-service/models/lstm_model.py`, `.pt` artifacts | — |
| 2.3 Daily + weekly forecast | Done | `/predict/demand` returns `weekly_summary` alongside daily forecasts | — |
| 2.4 Naive baseline | Done | `train_and_eval.py:naive_seasonal_baseline` lag-7 | — |
| 2.5 MAE / RMSE / MAPE evaluation | Done | `train_and_eval.py:compute_metrics`, `models/metrics.json` | MAPE uses safe denominator `max(\|y\|, 1.0)` — documented |
| 2.6 High-risk item flagging | Done | `risk_scorer.py` returns `risk_level` Critical/High/Medium/Low + `action_recommendation` | — |
| 3.1 Waste risk score 0–100 | Done | `risk_scorer.py:calculate_waste_risk` combining D, S, F | — |
| 4.1 Smart reorder recommendation | Done (fixed) | `reorder/optimizer.py`; endpoint now calls trained model when `forecast_lead_demand` omitted | — |
| 5.1 On-demand scoring endpoints | Done | `/predict/demand`, `/risk/score`, `/reorder/recommend` with API-key auth | — |
| 5.2 Scheduled batch predictions | Done | `api/scheduler.py` daily 02:00 AM cron, now uses Prophet/LSTM models | — |

---

## 2. Extra Features Built (beyond requirements)

- **Gamification system** — points, streaks, levels, badges (`services.py`, `core/models.py`)
- **Leaderboard** — top users by points (`views.py:leaderboard`)
- **Admin user management** — suspend / delete users (`views.py:admin_user_toggle_status`, `admin_user_delete`)
- **Role-based access** — business / NGO / admin roles with `@role_required` decorator
- **Dashboard real-time metrics** — auto-refreshing `/dashboard/metrics/` JSON endpoint
- **Forecast comparison plots** — 6 PNG charts saved to `ml-service/reports/`
- **Docker packaging** — `ml-service/Dockerfile` + healthcheck for ML service
- **`ml_client.py`** — zero-dependency HTTP client with graceful offline fallback

---

## 3. Quality & Security Issues

### High Severity

| # | Issue | Evidence | Fix Applied |
|:---|:---|:---|:---|
| H1 | Hardcoded API key in source (`dev-secret-key-food-waste-2026`) | `ml-service/api/config.py:15` (original) | ✅ Fixed — commit `401901d`: no default, startup validator rejects weak keys |
| H2 | Same hardcoded key in Django `ml_client.py` | `food_management/ml_client.py:27` (original) | ✅ Fixed — commit `2677be9`: empty string default, reads from env |
| H3 | No tenant isolation on inventory — all users saw all records | `views.py:inventory_list` no filter | ✅ Fixed — commit `d794116`: `business` FK + per-user queryset filter |
| H4 | `/risk/batch/{business_id}` accepted any tenant ID with no check | `main.py:get_batch_risk` (original) | ✅ Fixed — commit `401901d`: `verify_tenant_access` + `ALLOWED_BUSINESS_IDS` |
| H5 | Scheduler batch used static heuristic, not trained models | `scheduler.py:94` | ✅ Fixed — commit `c459313`: `_get_forecast_demand()` with Prophet/LSTM |
| H6 | Django `SECRET_KEY` hardcoded in settings | `config/settings.py` | ✅ Fixed — startup fails when `SECRET_KEY` is absent |

### Medium Severity

| # | Issue | Evidence | Fix Applied |
|:---|:---|:---|:---|
| M1 | Reorder endpoint docstring claimed model query but used heuristic | `main.py:307` | ✅ Fixed — commit `8485524` |
| M2 | Report overclaims Prophet beats naive on all categories | `MILESTONE2_REPORT.md §3` / `metrics.json` | ⚠️ Not fixed — Prophet loses to naive on bakery/produce |
| M3 | Scheduler tenant filter fell back to all-items on miss | `scheduler.py:55-58` | ✅ Fixed — commit `401901d` |
| M4 | No weekly-aggregated forecast output | `/predict/demand` response | ✅ Fixed — response includes `weekly_summary` |
| M5 | Django transactions are not yet consumed by the ML service — pipeline still uses synthetic CSV | `models.py`, `ml-service/data/` | ⚠️ Open — export or query real transactions in the next integration phase |
| M6 | Silent exception swallowing in batch cache read | `main.py:get_batch_risk` | ✅ Fixed — invalid cache reports are logged and recomputed |
| M7 | `business_id` field in `DemandPredictRequest` accepted but never used | `main.py` / `schemas.py` | ✅ Fixed — tenant is validated and LSTM history is filtered |

### Low Severity

| # | Issue | Evidence | Fix Applied |
|:---|:---|:---|:---|
| L1 | `/health` discloses model inventory without auth | `main.py:116` | By design (Docker healthcheck); acceptable |
| L2 | MAPE uses safe denominator `max(\|y\|, 1.0)` — not textbook formula | `train_and_eval.py:49-51` | Documented in report; acceptable |
| L3 | No POS REST API (M1 Req 1.3) | `food_management/pos_api.py` | ✅ Fixed |
| L4 | No barcode/QR scanning | Templates | ✅ Fixed — native browser `BarcodeDetector` integration and barcode lookup |
| L5 | No scheduled expiry alerts | Django | ✅ Fixed — `send_expiry_alerts` management command |
| L6 | Category thresholds hardcoded (3/7/30 days) | `forms.py` | ✅ Fixed — category overrides are stored in `CategoryConfig`; defaults remain configurable through admin |

---

## 4. Prioritized Plan (Milestone 2 by 1 Nov 2026)

### P0 — Must fix before submission

| Item | Why | Effort | Files |
|:---|:---|:---|:---|
| Fix Django `SECRET_KEY` to load from env (done) | Security — hardcoded in `settings.py` | 15 min | `config/settings.py`, `.env` |
| Wire `Transaction` rows on inventory CRUD (done) | M2 data pipeline needs real sales/waste history | 1 hr | `food_management/views.py`, `models.py` |
| Run `python manage.py migrate` | Apply all current migrations to DB | Done — migrations applied locally on 1 Nov 2026 | DB |
| Fix MILESTONE2_REPORT.md §3 Prophet claim | Submission accuracy | 15 min | `ml-service/MILESTONE2_REPORT.md` |

### P1 — Should add if time allows

| Item | Why | Effort | Files |
|:---|:---|:---|:---|
| POS REST API endpoint (done) | M1 Req 1.3 — completes Milestone 1 | 2 hrs | `food_management/pos_api.py`, `urls.py` |
| Weekly-horizon forecast output (done) | M2 Req 2.3 — adds aggregate weekly view | 1 hr | `ml-service/api/main.py`, `schemas.py` |
| Scheduled expiry alerts (management command) (done) | M1 Req 2.3 | 2 hrs | `management/commands/send_expiry_alerts.py` |
| Seed/demo data script (full flow) | Demo & evaluation | 1.5 hrs | New `scripts/seed_demo.py` |

### P2 — Milestone 3 / polish

| Item | Why | Effort | Files |
|:---|:---|:---|:---|
| Food taxonomy and category suggestions | M1 Req 3.1/3.2 | 3 hrs | Add a managed taxonomy and category suggestions to Django forms |
| Item-level LSTM forecasting | Better accuracy than category-level | 4 hrs | `ml-service/models/` |
| Automatic ML ingestion from Django transactions | Removes manual export dependency | 3 hrs | `ml-service/data/preprocess.py`, service integration |

---

## 5. Demo Flow

Run this sequence for the strongest demo:

```
1. Register as "business" user
2. Add inventory item (bakery, expiry 2 days) → risk_level auto-sets to "critical"
3. View dashboard → expiry alert appears
4. POST /risk/score with that item's data → score ~90, Critical
5. POST /reorder/recommend → order quantity with reasoning
6. Import CSV with 10 items → row-wise error report shown
7. GET /risk/batch/biz_001 → full tenant batch report
8. GET /models/metrics → MAE/RMSE/MAPE comparison table
```

---

## 6. Commits Applied During Audit

| Commit | Description |
|:---|:---|
| `401901d` | Remove hardcoded API key; add tenant isolation on batch endpoint |
| `c459313` | Scheduler batch uses trained Prophet/LSTM models |
| `2677be9` | Remove hardcoded ML key from Django ml_client.py |
| `adf1374` | Django UX: dashboard metrics endpoint, CSV validation |
| `8485524` | Reorder endpoint uses trained model for auto-forecast |
| `d794116` | Add business FK + Transaction model (migration 0002) |
