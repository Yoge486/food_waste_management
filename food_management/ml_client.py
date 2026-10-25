"""
Integration Client for Milestone 2 AI Waste Prediction Microservice.

Connects the Django Food Management application to the FastAPI ML service.
Uses standard library urllib (zero external package dependencies) for maximum portability.

Features:
- Demand forecasting integration
- Real-time waste risk scoring
- Batch risk assessment query
- Smart reorder recommendation
- Graceful offline fallback to Milestone 1 heuristic logic if ML service is unreachable
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any, Dict, Optional
import urllib.error
import urllib.parse
import urllib.request

logger = logging.getLogger(__name__)

ML_SERVICE_URL = os.getenv('ML_SERVICE_URL', 'http://127.0.0.1:8001')
# No hardcoded default key — must be set in .env as ML_SERVICE_API_KEY.
# Falls back to empty string so connection attempts fail fast rather than
# authenticating with a known-public credential.
ML_SERVICE_API_KEY = os.getenv('ML_SERVICE_API_KEY', '')
REQUEST_TIMEOUT = float(os.getenv('ML_SERVICE_TIMEOUT', '4.0'))


class MLServiceClient:
    """Standard-library HTTP client for communicating with the FastAPI ML microservice."""

    def __init__(self, base_url: str = ML_SERVICE_URL, api_key: str = ML_SERVICE_API_KEY):
        self.base_url = base_url.rstrip('/')
        self.api_key = api_key

    def _request(self, method: str, endpoint: str, payload: Optional[Dict] = None) -> Optional[Dict[str, Any]]:
        url = f'{self.base_url}{endpoint}'
        headers = {
            'X-API-Key': self.api_key,
            'Content-Type': 'application/json',
            'Accept': 'application/json',
        }
        data = json.dumps(payload).encode('utf-8') if payload is not None else None

        req = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT) as resp:
                if 200 <= resp.status < 300:
                    body = resp.read().decode('utf-8')
                    return json.loads(body)
                return None
        except urllib.error.HTTPError as e:
            logger.error(f'ML service HTTP error {e.code} on {endpoint}: {e.read().decode("utf-8", errors="ignore")}')
            return None
        except Exception as e:
            logger.warning(f'Failed to communicate with ML service on {endpoint}: {e}')
            return None

    def check_health(self) -> Dict[str, Any]:
        """Queries the ML service health status (public endpoint)."""
        url = f'{self.base_url}/health'
        req = urllib.request.Request(url, method='GET')
        try:
            with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT) as resp:
                if resp.status == 200:
                    return json.loads(resp.read().decode('utf-8'))
                return {'status': 'unhealthy', 'code': resp.status}
        except Exception as e:
            logger.warning(f'ML service health check failed: {e}')
            return {'status': 'offline', 'error': str(e)}

    def predict_demand(self, category: str, horizon_days: int = 14, model_type: str = 'best') -> Optional[Dict[str, Any]]:
        """Requests future demand forecast for a product category."""
        payload = {
            'category': category.lower(),
            'horizon_days': horizon_days,
            'model_type': model_type,
        }
        return self._request('POST', '/predict/demand', payload)

    def calculate_inventory_risk(self, item, forecast_demand: Optional[float] = None) -> Dict[str, Any]:
        """
        Calculates waste risk for a Django InventoryItem.
        Falls back to Milestone 1 heuristic calculate_waste_risk_score() if service is unreachable.
        """
        days_left = item.days_until_expiry() if hasattr(item, 'days_until_expiry') else 3
        stock = float(getattr(item, 'quantity', 0.0) or 0.0)

        # Approximate default forecast demand if not supplied
        if forecast_demand is None:
            forecast_demand = max(0.0, (stock / 2.0))

        payload = {
            'item_name': getattr(item, 'name', 'Item'),
            'category': getattr(item, 'category', 'dairy'),
            'days_to_expiry': days_left,
            'current_stock': stock,
            'forecast_demand': forecast_demand,
        }

        api_result = self._request('POST', '/risk/score', payload)
        if api_result:
            return api_result

        # Milestone 1 Fallback Heuristic
        fallback_score = item.calculate_waste_risk_score() if hasattr(item, 'calculate_waste_risk_score') else 50
        risk_level = getattr(item, 'risk_level', 'medium')
        return {
            'item_name': getattr(item, 'name', 'Item'),
            'category': getattr(item, 'category', 'dairy'),
            'risk_score': float(fallback_score),
            'risk_level': risk_level.capitalize() if isinstance(risk_level, str) else 'Medium',
            'surplus_qty': round(max(0.0, stock - forecast_demand), 2),
            'surplus_ratio': round(max(0.0, stock - forecast_demand) / stock, 2) if stock > 0 else 0.0,
            'urgency_factor': 0.5,
            'action_recommendation': 'Score estimated via local fallback rules (ML service offline).',
            'is_fallback': True,
        }

    def recommend_reorder(
        self,
        category: str,
        current_stock: float,
        lead_time_days: int = 2,
        storage_capacity: Optional[float] = None,
    ) -> Optional[Dict[str, Any]]:
        """Requests replenishment order recommendation with reasoning."""
        payload = {
            'category': category.lower(),
            'current_stock': current_stock,
            'lead_time_days': lead_time_days,
            'storage_capacity': storage_capacity,
        }
        return self._request('POST', '/reorder/recommend', payload)

    def get_batch_risk(self, business_id: str = 'biz_001') -> Optional[Dict[str, Any]]:
        """Fetches the latest tenant batch risk evaluation."""
        return self._request('GET', f'/risk/batch/{business_id}')


# Global singleton instance
ml_client = MLServiceClient()
