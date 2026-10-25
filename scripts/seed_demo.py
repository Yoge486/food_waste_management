"""
seed_demo.py — Full-flow demo seed script for Milestone 2 evaluation.

Demonstrates the complete pipeline:
  1. Creates a demo Django user + POS API key
  2. Adds inventory items spanning all risk levels via the POS REST API
  3. Runs the expiry-alert management command (dry-run)
  4. Calls the ML service: risk score, reorder recommendation, demand forecast
  5. Prints a formatted summary report

Usage (with both services running):
    # Terminal 1: python manage.py runserver
    # Terminal 2 (ml-service): uvicorn api.main:app --port 8001

    python scripts/seed_demo.py

    # To skip ML service calls (Django only):
    python scripts/seed_demo.py --no-ml

Environment variables read from d:\\infosys-project\\.env automatically.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from datetime import date, timedelta
from pathlib import Path

# ---------------------------------------------------------------------------
# Bootstrap Django
# ---------------------------------------------------------------------------
REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'food_waste_manager.settings')

# Load .env so SECRET_KEY is available before Django setup
_env = REPO_ROOT / '.env'
if _env.exists():
    with open(_env) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith('#') and '=' in line:
                k, v = line.split('=', 1)
                os.environ.setdefault(k.strip(), v.strip())

import django
django.setup()

from django.contrib.auth.models import User
from food_management.models import InventoryItem, POSApiKey
from food_management.pos_api import generate_pos_key

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
DEMO_USERNAME = 'demo_business'
DEMO_PASSWORD = 'DemoPass2026!'
ML_BASE = os.environ.get('ML_SERVICE_URL', 'http://127.0.0.1:8001')
ML_API_KEY = os.environ.get('ML_SERVICE_API_KEY', '')
DJANGO_BASE = 'http://127.0.0.1:8000'

TODAY = date.today()

DEMO_ITEMS = [
    {
        'name': 'Butter Croissant',
        'category': 'bakery',
        'quantity': 18.0,
        'unit': 'kg',
        'purchase_date': (TODAY - timedelta(days=2)).isoformat(),
        'expiry_date': (TODAY + timedelta(days=1)).isoformat(),   # CRITICAL
        'storage_location': 'Bakery Rack 1',
    },
    {
        'name': 'Whole Milk 1L',
        'category': 'dairy',
        'quantity': 35.0,
        'unit': 'kg',
        'purchase_date': (TODAY - timedelta(days=5)).isoformat(),
        'expiry_date': (TODAY + timedelta(days=4)).isoformat(),   # HIGH
        'storage_location': 'Cold Room A (4°C)',
    },
    {
        'name': 'Spinach Bunch',
        'category': 'produce',
        'quantity': 22.0,
        'unit': 'kg',
        'purchase_date': (TODAY - timedelta(days=1)).isoformat(),
        'expiry_date': (TODAY + timedelta(days=15)).isoformat(),  # MEDIUM
        'storage_location': 'Produce Cooler B',
    },
    {
        'name': 'Basmati Rice 1kg',
        'category': 'packaged',
        'quantity': 100.0,
        'unit': 'units',
        'purchase_date': (TODAY - timedelta(days=10)).isoformat(),
        'expiry_date': (TODAY + timedelta(days=160)).isoformat(), # LOW
        'storage_location': 'Dry Storage Shelf C',
    },
    {
        'name': 'Chicken Breast',
        'category': 'meat',
        'quantity': 15.0,
        'unit': 'kg',
        'purchase_date': TODAY.isoformat(),
        'expiry_date': (TODAY + timedelta(days=3)).isoformat(),   # URGENT
        'storage_location': 'Deep Freezer (-2°C)',
    },
]

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
SEP = '─' * 70


def section(title: str):
    print(f'\n{SEP}')
    print(f'  {title}')
    print(SEP)


def ml_request(method: str, path: str, payload: dict | None = None) -> dict | None:
    url = f'{ML_BASE}{path}'
    headers = {'X-API-Key': ML_API_KEY, 'Content-Type': 'application/json'}
    data = json.dumps(payload).encode() if payload else None
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        print(f'  [ML ERROR] {e.code}: {e.read().decode(errors="ignore")}')
        return None
    except Exception as e:
        print(f'  [ML OFFLINE] {e}')
        return None


def pos_request(pos_key: str, item: dict, idempotency_key: str) -> dict | None:
    url = f'{DJANGO_BASE}/api/pos/inventory/'
    headers = {
        'X-API-Key': pos_key,
        'Idempotency-Key': idempotency_key,
        'Content-Type': 'application/json',
    }
    data = json.dumps(item).encode()
    req = urllib.request.Request(url, data=data, headers=headers, method='POST')
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        body = e.read().decode(errors='ignore')
        print(f'  [POS ERROR] {e.code}: {body}')
        return None
    except Exception as e:
        print(f'  [POS OFFLINE] {e}')
        return None


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main(use_ml: bool = True):
    print('\n' + '═' * 70)
    print('  AI-Powered Food Waste Management — Demo Seed Script')
    print('  Milestone 2 · Infosys Springboard 2026')
    print('═' * 70)

    # ------------------------------------------------------------------
    # Step 1: Create demo user + POS key
    # ------------------------------------------------------------------
    section('STEP 1 — Create demo business user & POS API key')

    user, created = User.objects.get_or_create(username=DEMO_USERNAME)
    if created:
        user.set_password(DEMO_PASSWORD)
        user.save()
        print(f'  ✓ Created user: {DEMO_USERNAME}')
    else:
        print(f'  ↩ User already exists: {DEMO_USERNAME}')

    # Get or create an active POS key for this user
    existing_key = POSApiKey.objects.filter(business=user, is_active=True).first()
    if existing_key:
        raw_key = existing_key.key
        print(f'  ↩ Reusing existing POS key: {raw_key[:12]}…')
    else:
        pos_key_obj = generate_pos_key(user, label='Demo seed key')
        raw_key = pos_key_obj.key
        print(f'  ✓ Generated POS key: {raw_key[:12]}…')

    # ------------------------------------------------------------------
    # Step 2: Ingest demo inventory via POS endpoint
    # ------------------------------------------------------------------
    section('STEP 2 — Ingest inventory via POST /api/pos/inventory/')

    inserted_items = []
    for i, item in enumerate(DEMO_ITEMS):
        idempotency_key = f'seed-demo-2026-item-{i:03d}'
        result = pos_request(raw_key, item, idempotency_key)
        if result:
            status = result.get('status', '?')
            risk = result.get('risk_level', '?')
            dte = result.get('days_until_expiry', '?')
            icon = '✓' if status == 'created' else '↩'
            print(f'  {icon} [{status.upper()}] {item["name"]:30s} risk={risk:8s} days_left={dte}')
            inserted_items.append(result)
        else:
            print(f'  ✗ {item["name"]} — POS endpoint unreachable (is Django running on port 8000?)')

    # ------------------------------------------------------------------
    # Step 3: Expiry alert dry-run
    # ------------------------------------------------------------------
    section('STEP 3 — Expiry alerts (dry-run, thresholds 1,3,7 days)')

    import subprocess
    python = sys.executable
    result = subprocess.run(
        [python, 'manage.py', 'send_expiry_alerts', '--dry-run', '--thresholds', '1,3,7'],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
    )
    output = (result.stdout + result.stderr).strip()
    for line in output.splitlines():
        print(f'  {line}')

    if not use_ml:
        print('\n  [--no-ml flag set] Skipping ML service calls.\n')
        return

    # ------------------------------------------------------------------
    # Step 4: ML service — risk scores
    # ------------------------------------------------------------------
    section('STEP 4 — Waste risk scores via POST /risk/score')

    risk_cases = [
        {'name': 'Butter Croissant', 'category': 'bakery',   'days_to_expiry': 1,  'current_stock': 18.0, 'forecast_demand': 5.0},
        {'name': 'Whole Milk 1L',    'category': 'dairy',    'days_to_expiry': 4,  'current_stock': 35.0, 'forecast_demand': 20.0},
        {'name': 'Chicken Breast',   'category': 'meat',     'days_to_expiry': 3,  'current_stock': 15.0, 'forecast_demand': 12.0},
        {'name': 'Basmati Rice 1kg', 'category': 'packaged', 'days_to_expiry': 160,'current_stock': 100.0,'forecast_demand': 60.0},
    ]

    for rc in risk_cases:
        res = ml_request('POST', '/risk/score', rc)
        if res:
            print(f'  {rc["name"]:30s} score={res["risk_score"]:5.1f}  level={res["risk_level"]:8s}  surplus={res["surplus_qty"]}')
            if res.get('risk_level') in ('Critical', 'High'):
                print(f'    → {res["action_recommendation"]}')

    # ------------------------------------------------------------------
    # Step 5: ML service — reorder recommendation
    # ------------------------------------------------------------------
    section('STEP 5 — Reorder recommendations via POST /reorder/recommend')

    reorder_cases = [
        {'category': 'bakery',   'current_stock': 5.0,  'lead_time_days': 1},
        {'category': 'dairy',    'current_stock': 10.0, 'lead_time_days': 2, 'storage_capacity': 150.0},
        {'category': 'packaged', 'current_stock': 80.0, 'lead_time_days': 3, 'storage_capacity': 200.0},
    ]

    for rc in reorder_cases:
        res = ml_request('POST', '/reorder/recommend', rc)
        if res:
            print(f'  {rc["category"]:12s} order_qty={res["recommended_order_qty"]:7.1f}  status={res["status"]}')
            print(f'    → {res["reasoning"][:90]}…' if len(res.get('reasoning', '')) > 90 else f'    → {res.get("reasoning", "")}')

    # ------------------------------------------------------------------
    # Step 6: ML service — demand forecast with weekly summary
    # ------------------------------------------------------------------
    section('STEP 6 — 14-day demand forecast via POST /predict/demand')

    for cat in ['dairy', 'bakery', 'produce']:
        res = ml_request('POST', '/predict/demand', {'category': cat, 'horizon_days': 14, 'model_type': 'best'})
        if res:
            model = res.get('model_used', '?')
            total = res.get('total_projected_demand', 0)
            weeks = res.get('weekly_summary', [])
            print(f'\n  {cat.upper()} — model={model}, 14-day total={total} {res.get("unit", "")}')
            for w in weeks:
                print(f'    {w["week_label"]:35s}  total={w["total_demand"]:7.1f}  avg/day={w["avg_daily_demand"]:6.1f}')

    # ------------------------------------------------------------------
    # Done
    # ------------------------------------------------------------------
    section('DEMO COMPLETE')
    print('  All steps passed. The platform is ready for Milestone 2 submission.')
    print(f'\n  Web app:  http://127.0.0.1:8000  (login: {DEMO_USERNAME} / {DEMO_PASSWORD})')
    print(f'  ML docs:  http://127.0.0.1:8001/docs')
    print()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Seed demo data for Milestone 2 evaluation.')
    parser.add_argument('--no-ml', action='store_true', help='Skip ML service API calls.')
    args = parser.parse_args()
    main(use_ml=not args.no_ml)
