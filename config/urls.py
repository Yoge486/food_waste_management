"""
Root URL configuration for AI-Powered Food Waste Management Platform.

Routes:
  /          → core app  (public homepage, login, register)
  /          → food_management app  (dashboard, inventory, surplus, donations)
  /admin/    → Django admin
"""

from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path('admin/', admin.site.urls),
    # Public homepage, login, register
    path('', include('core.urls')),
    # All app views (dashboard, inventory, surplus, donations, POS API)
    path('', include('food_management.urls')),
]
