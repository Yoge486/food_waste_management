from datetime import date, timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.db import transaction

from core.models import UserProfile
from food_management.models import DonationRequest, InventoryItem, SurplusListing
from food_management.services import record_transaction


class Command(BaseCommand):
    help = 'Create deterministic inventory, surplus, donation, and risk-scoring demo data.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--reset',
            action='store_true',
            help='Remove records owned by the demo accounts before seeding.',
        )

    @transaction.atomic
    def handle(self, *args, **options):
        user_model = get_user_model()
        business, _ = user_model.objects.get_or_create(
            username='demo_business',
            defaults={'email': 'demo-business@example.com'},
        )
        business.set_password('DemoPassword9!')
        business.save(update_fields=['password', 'email'])
        UserProfile.objects.update_or_create(
            user=business,
            defaults={
                'role': 'business',
                'organization_name': 'Green Kitchen Demo',
                'points': 180,
                'level': 2,
                'streak_days': 7,
                'badges': ['Inventory Keeper', 'Rapid Rescuer'],
            },
        )

        ngo, _ = user_model.objects.get_or_create(
            username='demo_ngo',
            defaults={'email': 'demo-ngo@example.com'},
        )
        ngo.set_password('DemoPassword9!')
        ngo.save(update_fields=['password', 'email'])
        UserProfile.objects.update_or_create(
            user=ngo,
            defaults={
                'role': 'ngo',
                'organization_name': 'Community Food Bank Demo',
            },
        )

        if options['reset']:
            InventoryItem.objects.filter(business=business).delete()
            SurplusListing.objects.filter(business=business).delete()
            business.transactions.all().delete()

        today = date.today()
        inventory_specs = [
            {
                'name': 'Expired Milk - Demo',
                'category': 'dairy',
                'quantity': Decimal('24'),
                'unit': 'litres',
                'expiry_date': today - timedelta(days=1),
                'risk_level': 'critical',
                'notes': 'Expected critical risk: expired stock.',
            },
            {
                'name': 'Biryani Trays - Demo',
                'category': 'prepared',
                'quantity': Decimal('30'),
                'unit': 'kg',
                'expiry_date': today + timedelta(days=1),
                'risk_level': 'critical',
                'notes': 'Expected high risk: urgent redistribution candidate.',
            },
            {
                'name': 'Fresh Rice Bags - Demo',
                'category': 'packaged',
                'quantity': Decimal('10'),
                'unit': 'kg',
                'expiry_date': today + timedelta(days=60),
                'risk_level': 'low',
                'notes': 'Expected low risk: demand should absorb stock.',
            },
        ]

        items = []
        for spec in inventory_specs:
            item, _ = InventoryItem.objects.update_or_create(
                business=business,
                name=spec['name'],
                defaults={
                    **spec,
                    'purchase_date': today - timedelta(days=3),
                    'storage_location': 'Demo storage',
                },
            )
            items.append(item)

        surplus, _ = SurplusListing.objects.update_or_create(
            business=business,
            food_name='Biryani Trays - Demo',
            defaults={
                'category': 'prepared',
                'quantity': Decimal('12'),
                'unit': 'kg',
                'expiry_date': today + timedelta(days=1),
                'pickup_location': 'Green Kitchen Demo',
                'availability_window': 'Today, 4 PM - 7 PM',
                'status': 'available',
                'notes': 'Seeded demo surplus listing.',
            },
        )
        DonationRequest.objects.get_or_create(
            listing=surplus,
            ngo_name='Community Food Bank Demo',
            defaults={
                'requested_by': ngo,
                'requested_quantity': Decimal('6'),
                'pickup_date': today,
                'status': 'requested',
                'notes': 'Seeded demo donation request.',
            },
        )

        for item in items:
            record_transaction(
                business=business,
                category=item.category,
                purchase_qty=float(item.quantity),
                unit=item.unit,
            )

        self.stdout.write(self.style.SUCCESS('Demo data seeded successfully.'))
        self.stdout.write(f'Business login: demo_business / DemoPassword9!')
        self.stdout.write(f'NGO login: demo_ngo / DemoPassword9!')
        self.stdout.write(f'Inventory records: {len(items)}')
        self.stdout.write('Risk checks:')
        for item in items:
            score = item.calculate_waste_risk_score()
            expected = 'Critical' if item.days_until_expiry() <= 0 else (
                'High/Critical' if item.days_until_expiry() <= 3 else 'Low/Medium'
            )
            self.stdout.write(
                f'  {item.name}: {score}/100 ({item.risk_level}) '
                f'[{item.days_until_expiry()} days; expected {expected}]'
            )
