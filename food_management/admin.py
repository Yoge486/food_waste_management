from django.contrib import admin

from .models import (
    CategoryConfig,
    DonationRequest,
    ExpiryAlert,
    InAppNotification,
    InventoryItem,
    NotificationPreference,
    POSApiKey,
    POSIdempotencyKey,
    SurplusListing,
    Transaction,
)


@admin.register(InventoryItem)
class InventoryItemAdmin(admin.ModelAdmin):
    list_display = ('name', 'category', 'barcode', 'quantity', 'expiry_date', 'risk_level', 'business')
    list_filter = ('category', 'risk_level')
    search_fields = ('name', 'category', 'storage_location')
    autocomplete_fields = ['business']


@admin.register(SurplusListing)
class SurplusListingAdmin(admin.ModelAdmin):
    list_display = ('food_name', 'category', 'quantity', 'expiry_date', 'status', 'business')
    list_filter = ('status', 'category')
    search_fields = ('food_name', 'pickup_location')


@admin.register(DonationRequest)
class DonationRequestAdmin(admin.ModelAdmin):
    list_display = ('ngo_name', 'listing', 'requested_quantity', 'pickup_date', 'status')
    list_filter = ('status',)
    search_fields = ('ngo_name', 'listing__food_name')


@admin.register(Transaction)
class TransactionAdmin(admin.ModelAdmin):
    list_display = ('business', 'date', 'category', 'sales_qty', 'purchase_qty', 'waste_qty', 'unit')
    list_filter = ('category', 'date')
    search_fields = ('business__username', 'category')
    date_hierarchy = 'date'


@admin.register(POSApiKey)
class POSApiKeyAdmin(admin.ModelAdmin):
    list_display = ('business', 'label', 'is_active', 'created_at', 'last_used_at')
    list_filter = ('is_active',)
    search_fields = ('business__username', 'label')
    readonly_fields = ('key', 'created_at', 'last_used_at')


@admin.register(POSIdempotencyKey)
class POSIdempotencyKeyAdmin(admin.ModelAdmin):
    list_display = ('key', 'api_key', 'created_at')
    search_fields = ('key',)
    readonly_fields = ('key', 'api_key', 'response_body', 'created_at')


@admin.register(ExpiryAlert)
class ExpiryAlertAdmin(admin.ModelAdmin):
    list_display = ('item', 'threshold_days', 'alert_date', 'sent_at')
    list_filter = ('threshold_days', 'alert_date')
    search_fields = ('item__name', 'item__category')
    date_hierarchy = 'alert_date'
    readonly_fields = ('sent_at',)


@admin.register(CategoryConfig)
class CategoryConfigAdmin(admin.ModelAdmin):
    list_display = (
        'category', 'perishability', 'critical_days', 'high_days',
        'medium_days', 'shelf_life_days', 'is_active',
    )
    list_filter = ('is_active',)
    search_fields = ('category',)


@admin.register(InAppNotification)
class InAppNotificationAdmin(admin.ModelAdmin):
    list_display = ('user', 'title', 'notification_type', 'is_read', 'created_at')
    list_filter = ('notification_type', 'is_read')
    search_fields = ('user__username', 'title', 'message')
    readonly_fields = ('created_at',)


@admin.register(NotificationPreference)
class NotificationPreferenceAdmin(admin.ModelAdmin):
    list_display = ('user', 'receive_expiry_alerts', 'receive_expiry_emails')
    list_filter = ('receive_expiry_alerts', 'receive_expiry_emails')
    search_fields = ('user__username',)
