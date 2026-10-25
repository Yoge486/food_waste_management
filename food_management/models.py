from datetime import date

from django.conf import settings
from django.db import models


class InventoryItem(models.Model):
    RISK_CHOICES = [
        ('low', 'Low'),
        ('medium', 'Medium'),
        ('high', 'High'),
        ('critical', 'Critical'),
    ]

    # Tenant owner – nullable so existing rows are not broken.
    # New items should always have an owner assigned by the view.
    business = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='inventory_items',
        help_text='The business/user account that owns this inventory record.',
    )

    name = models.CharField(max_length=150)
    category = models.CharField(max_length=100)
    quantity = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    unit = models.CharField(max_length=30, default='kg')
    purchase_date = models.DateField()
    expiry_date = models.DateField()
    storage_location = models.CharField(max_length=200, default='Main storage')
    risk_level = models.CharField(max_length=20, choices=RISK_CHOICES, default='low')
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['expiry_date', 'name']
        indexes = [
            models.Index(fields=['business', 'expiry_date']),
            models.Index(fields=['business', 'category']),
        ]

    def __str__(self):
        return f'{self.name} ({self.quantity} {self.unit})'

    def days_until_expiry(self):
        return (self.expiry_date - date.today()).days

    def calculate_waste_risk_score(self):
        days_left = self.days_until_expiry()
        score = 10
        if days_left <= 3:
            score += 60
        elif days_left <= 7:
            score += 45
        elif days_left <= 14:
            score += 25
        elif days_left <= 30:
            score += 15

        quantity = float(self.quantity or 0)
        score += min(int(quantity / 10), 25)

        if self.risk_level == 'critical':
            score += 15
        elif self.risk_level == 'high':
            score += 10
        elif self.risk_level == 'medium':
            score += 5

        return min(score, 100)


class SurplusListing(models.Model):
    STATUS_CHOICES = [
        ('available', 'Available'),
        ('reserved', 'Reserved'),
        ('collected', 'Collected'),
        ('cancelled', 'Cancelled'),
    ]

    # Tenant owner
    business = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='surplus_listings',
    )

    food_name = models.CharField(max_length=150)
    category = models.CharField(max_length=100)
    quantity = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    unit = models.CharField(max_length=30, default='kg')
    expiry_date = models.DateField()
    pickup_location = models.CharField(max_length=250)
    availability_window = models.CharField(max_length=200, default='Today')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='available')
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f'{self.food_name} - {self.status}'


class DonationRequest(models.Model):
    STATUS_CHOICES = [
        ('requested', 'Requested'),
        ('scheduled', 'Scheduled'),
        ('collected', 'Collected'),
        ('cancelled', 'Cancelled'),
    ]

    listing = models.ForeignKey(SurplusListing, on_delete=models.CASCADE, related_name='requests')
    ngo_name = models.CharField(max_length=200)
    requested_quantity = models.DecimalField(max_digits=10, decimal_places=2)
    pickup_date = models.DateField()
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='requested')
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f'{self.ngo_name} - {self.listing.food_name}'


class Transaction(models.Model):
    """
    Daily sales / purchase / waste record per business per category.

    This table is the bridge between the Django inventory system and the
    Milestone 2 ML pipeline.  The ML service reads daily_transactions.csv
    (synthetic for now); once real data accumulates here a management
    command can export it to that CSV or the ML service can query this table
    directly via the Django ORM.
    """
    TX_TYPE_CHOICES = [
        ('sale', 'Sale'),
        ('purchase', 'Purchase'),
        ('waste', 'Waste'),
        ('donation', 'Donation'),
    ]

    business = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='transactions',
    )
    date = models.DateField(db_index=True)
    category = models.CharField(max_length=100, db_index=True)
    # Aggregated quantities for the day (ML pipeline uses daily aggregates)
    sales_qty = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    purchase_qty = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    waste_qty = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    donation_qty = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    unit = models.CharField(max_length=30, default='kg')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        # One row per (business, date, category) — enforced at DB level
        unique_together = [('business', 'date', 'category')]
        ordering = ['-date', 'category']
        indexes = [
            models.Index(fields=['business', 'date', 'category']),
        ]

    def __str__(self):
        return f'{self.business_id} | {self.date} | {self.category}'


class POSApiKey(models.Model):
    """
    Per-tenant API key for the POS REST endpoint (M1 Req 1.3).
    One business can have multiple keys (rotation support).
    """
    business = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='pos_api_keys',
    )
    key = models.CharField(max_length=64, unique=True, db_index=True)
    label = models.CharField(max_length=100, default='Default POS key')
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    last_used_at = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return f'{self.business.username} — {self.label}'


class POSIdempotencyKey(models.Model):
    """
    Stores idempotency keys submitted by POS clients.
    If the same key is sent twice the second request returns the cached response
    without creating a duplicate inventory row.
    """
    key = models.CharField(max_length=128, unique=True, db_index=True)
    api_key = models.ForeignKey(POSApiKey, on_delete=models.CASCADE, related_name='idempotency_keys')
    response_body = models.JSONField()          # cached JSON response
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f'{self.key[:20]}…'
