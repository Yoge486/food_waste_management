"""
Management command: send_expiry_alerts

Scans all active inventory items, identifies those expiring within the
configured threshold(s), deduplicates against ExpiryAlert records so the
same alert is never sent twice on the same calendar day, and prints or
emails alerts.

Usage:
    python manage.py send_expiry_alerts
    python manage.py send_expiry_alerts --thresholds 1,3,7
    python manage.py send_expiry_alerts --dry-run

Schedule (cron example — runs once daily at 07:00):
    0 7 * * * /path/to/.venv/bin/python /path/to/manage.py send_expiry_alerts

Schedule (Windows Task Scheduler):
    Program: C:\\...\\python.exe
    Arguments: manage.py send_expiry_alerts
    Start in: D:\\infosys-project
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import List

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from food_management.models import ExpiryAlert, InventoryItem


# Default configurable thresholds (days before expiry that trigger an alert)
DEFAULT_THRESHOLDS: List[int] = [1, 3, 7]


class Command(BaseCommand):
    help = 'Send deduplicated expiry alerts for inventory items nearing their expiry date.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--thresholds',
            type=str,
            default=','.join(map(str, DEFAULT_THRESHOLDS)),
            help=(
                'Comma-separated days-to-expiry thresholds that trigger alerts. '
                f'Default: {DEFAULT_THRESHOLDS}'
            ),
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            default=False,
            help='Print alerts without writing ExpiryAlert records or sending emails.',
        )
        parser.add_argument(
            '--category',
            type=str,
            default='',
            help='Limit alerts to a specific category (optional).',
        )

    def handle(self, *args, **options):
        dry_run: bool = options['dry_run']
        category_filter: str = options['category'].strip().lower()

        # Parse and validate threshold list
        try:
            thresholds = sorted(
                {int(t.strip()) for t in options['thresholds'].split(',') if t.strip()},
                reverse=True,  # highest first so worst-case label wins
            )
        except ValueError:
            raise CommandError('--thresholds must be a comma-separated list of integers.')

        if not thresholds:
            raise CommandError('No valid thresholds provided.')

        today = date.today()
        max_threshold = max(thresholds)

        # Fetch items expiring within the widest threshold window
        qs = InventoryItem.objects.filter(
            expiry_date__gte=today,
            expiry_date__lte=today + timedelta(days=max_threshold),
        ).select_related('business')

        if category_filter:
            qs = qs.filter(category__iexact=category_filter)

        total_sent = 0
        total_skipped = 0

        for item in qs:
            days_left = (item.expiry_date - today).days

            # Find the tightest threshold this item crosses
            triggered = [t for t in thresholds if days_left <= t]
            if not triggered:
                continue
            threshold = min(triggered)   # tightest applicable threshold

            # Deduplication: skip if this alert was already sent today
            already_sent = ExpiryAlert.objects.filter(
                item=item,
                threshold_days=threshold,
                alert_date=today,
            ).exists()

            if already_sent:
                total_skipped += 1
                continue

            # Build alert message
            urgency = self._urgency_label(days_left)
            owner = item.business.username if item.business else 'unassigned'
            msg = (
                f'[{urgency}] "{item.name}" ({item.category}) — '
                f'{item.quantity} {item.unit} — '
                f'expires {item.expiry_date} ({days_left}d left) — '
                f'owner: {owner}'
            )

            # Emit alert (console for now; extend here for email/webhook)
            self.stdout.write(self.style.WARNING(msg))

            # Record deduplication row (skip in dry-run)
            if not dry_run:
                with transaction.atomic():
                    ExpiryAlert.objects.get_or_create(
                        item=item,
                        threshold_days=threshold,
                        alert_date=today,
                    )

            total_sent += 1

        suffix = ' (dry-run — no records written)' if dry_run else ''
        self.stdout.write(
            self.style.SUCCESS(
                f'\nDone{suffix}: {total_sent} alert(s) sent, {total_skipped} skipped (already alerted today).'
            )
        )

    @staticmethod
    def _urgency_label(days_left: int) -> str:
        if days_left <= 1:
            return 'CRITICAL'
        if days_left <= 3:
            return 'URGENT'
        if days_left <= 7:
            return 'WARNING'
        return 'NOTICE'
