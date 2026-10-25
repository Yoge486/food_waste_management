"""
POS REST API — Milestone 1 Req 1.3.

Endpoint: POST /api/pos/inventory/

Authentication:  X-API-Key: <per-tenant key from POSApiKey table>
Idempotency:     Idempotency-Key: <client-generated UUID> header
                 Duplicate requests return the cached response (HTTP 200)
                 without re-inserting inventory rows.

Request body (JSON):
{
    "name":             "Whole Milk 1L",
    "category":         "dairy",
    "quantity":         24.5,
    "unit":             "kg",              // optional, default "kg"
    "purchase_date":    "2026-10-25",
    "expiry_date":      "2026-11-04",
    "storage_location": "Cold Room A",     // optional
    "notes":            ""                 // optional
}

Success response (HTTP 201):
{
    "status": "created",
    "item_id": 42,
    "risk_level": "low",
    "days_until_expiry": 10
}

Idempotent repeat (HTTP 200):
{
    "status": "duplicate",
    "item_id": 42,
    ...
}
"""

from __future__ import annotations

import json
import secrets
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from .models import InventoryItem, POSApiKey, POSIdempotencyKey
from .services import record_transaction


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _error(message: str, status: int = 400) -> JsonResponse:
    return JsonResponse({'status': 'error', 'detail': message}, status=status)


def _authenticate(request) -> POSApiKey | None:
    """Validates X-API-Key header and returns the matching active POSApiKey or None."""
    raw_key = request.headers.get('X-API-Key', '').strip()
    if not raw_key:
        return None
    try:
        pos_key = POSApiKey.objects.select_related('business').get(
            key=raw_key, is_active=True
        )
        # Update last_used_at without triggering updated_at on inventory
        POSApiKey.objects.filter(pk=pos_key.pk).update(last_used_at=timezone.now())
        return pos_key
    except POSApiKey.DoesNotExist:
        return None


def _auto_risk_level(expiry_date: date) -> str:
    days = (expiry_date - date.today()).days
    if days <= 3:
        return 'critical'
    if days <= 7:
        return 'high'
    if days <= 30:
        return 'medium'
    return 'low'


# ---------------------------------------------------------------------------
# Endpoint
# ---------------------------------------------------------------------------

@csrf_exempt
@require_http_methods(['POST'])
def pos_inventory_ingest(request):
    """
    POS inventory ingestion endpoint.
    Accepts a single inventory item per request.
    Supports idempotency via the Idempotency-Key header.
    """
    # 1. Authenticate
    pos_key = _authenticate(request)
    if pos_key is None:
        return _error('Missing or invalid X-API-Key.', status=401)

    # 2. Idempotency check
    idempotency_key = request.headers.get('Idempotency-Key', '').strip()
    if idempotency_key:
        try:
            cached = POSIdempotencyKey.objects.get(
                key=idempotency_key, api_key=pos_key
            )
            # Return the stored response unchanged (idempotent replay)
            return JsonResponse(cached.response_body, status=200)
        except POSIdempotencyKey.DoesNotExist:
            pass  # New request — continue processing

    # 3. Parse request body
    try:
        body = json.loads(request.body.decode('utf-8'))
    except (json.JSONDecodeError, UnicodeDecodeError):
        return _error('Request body must be valid JSON.')

    # 4. Validate required fields
    required = ['name', 'category', 'quantity', 'purchase_date', 'expiry_date']
    missing = [f for f in required if not body.get(f)]
    if missing:
        return _error(f'Missing required fields: {", ".join(missing)}.')

    name = str(body['name']).strip()
    category = str(body['category']).strip().lower()

    if len(name) > 150:
        return _error('name must be 150 characters or fewer.')
    if len(category) > 100:
        return _error('category must be 100 characters or fewer.')

    try:
        quantity = Decimal(str(body['quantity']))
        if not quantity.is_finite() or quantity <= 0:
            raise ValueError
    except (InvalidOperation, ValueError, TypeError):
        return _error('quantity must be a positive number.')

    try:
        purchase_date = date.fromisoformat(str(body['purchase_date']))
        expiry_date = date.fromisoformat(str(body['expiry_date']))
    except (ValueError, TypeError):
        return _error('purchase_date and expiry_date must be ISO format dates (YYYY-MM-DD).')

    if expiry_date < purchase_date:
        return _error('expiry_date cannot be before purchase_date.')

    unit = str(body.get('unit', 'kg')).strip() or 'kg'
    storage_location = str(body.get('storage_location', 'Main storage')).strip() or 'Main storage'
    notes = str(body.get('notes', '')).strip()

    risk_level = _auto_risk_level(expiry_date)

    # 5. Create inventory item
    item = InventoryItem.objects.create(
        business=pos_key.business,
        name=name,
        category=category,
        quantity=quantity,
        unit=unit,
        purchase_date=purchase_date,
        expiry_date=expiry_date,
        storage_location=storage_location,
        risk_level=risk_level,
        notes=notes,
    )

    # 6. Record purchase transaction for ML pipeline
    record_transaction(
        business=pos_key.business,
        category=category,
        purchase_qty=float(quantity),
        unit=unit,
        tx_date=date.today(),
    )

    # 7. Build response
    response_body = {
        'status': 'created',
        'item_id': item.pk,
        'name': item.name,
        'category': item.category,
        'quantity': float(item.quantity),
        'unit': item.unit,
        'risk_level': risk_level,
        'days_until_expiry': item.days_until_expiry(),
        'expiry_date': expiry_date.isoformat(),
    }

    # 8. Store idempotency record (only when client sent a key)
    if idempotency_key:
        # Truncate to model field length for safety
        POSIdempotencyKey.objects.create(
            key=idempotency_key[:128],
            api_key=pos_key,
            response_body=response_body,
        )

    return JsonResponse(response_body, status=201)


# ---------------------------------------------------------------------------
# Key management helpers (called from admin or a management command)
# ---------------------------------------------------------------------------

def generate_pos_key(business_user, label: str = 'Default POS key') -> POSApiKey:
    """
    Generates a new cryptographically random POS API key for a business user.
    Safe to call from the Django shell or a management command.

    Usage:
        from food_management.pos_api import generate_pos_key
        from django.contrib.auth.models import User
        key_obj = generate_pos_key(User.objects.get(username='mybusiness'))
        print(key_obj.key)
    """
    raw_key = secrets.token_hex(32)   # 64-char hex string
    return POSApiKey.objects.create(
        business=business_user,
        key=raw_key,
        label=label,
    )
