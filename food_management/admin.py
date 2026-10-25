from django.contrib import admin

from .models import DonationRequest, InventoryItem, SurplusListing, Transaction


@admin.register(InventoryItem)
class InventoryItemAdmin(admin.ModelAdmin):
    list_display = ('name', 'category', 'quantity', 'expiry_date', 'risk_level', 'business')
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
