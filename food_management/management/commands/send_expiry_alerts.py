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
from django.core.mail import mail_admins

from food_management.models import ExpiryAlert, InventoryItem, NotificationPreference
from food_management.services import get_category_thresholds, notify_user


# Default configurable thresholds (days before expiry that trigger an alert)
DEFAULT_THRESHOLDS: List[int] = [1, 3, 7]


class Command(BaseCommand):
    help = 'Send deduplicated expiry alerts for inventory items nearing their expiry date.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--thresholds',
            type=str,
            default='',
            help=(
                'Optional comma-separated days-to-expiry thresholds. '
                'When omitted, category configuration thresholds are used.'
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
        thresholds = None
        if options['thresholds'].strip():
            try:
                thresholds = sorted(
                    {int(t.strip()) for t in options['thresholds'].split(',') if t.strip()},
                    reverse=True,
                )
            except ValueError:
                raise CommandError('--thresholds must be a comma-separated list of integers.')
            if not thresholds or any(value < 0 for value in thresholds):
                raise CommandError('--thresholds must contain non-negative integers.')

        today = date.today()
        max_threshold = max(thresholds or DEFAULT_THRESHOLDS)

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
            item_thresholds = thresholds
            if item_thresholds is None:
                critical_days, high_days, medium_days = get_category_thresholds(item.category)
                item_thresholds = sorted(
                    {critical_days, high_days, medium_days},
                    reverse=True,
                )

            # Find the tightest threshold this item crosses
            triggered = [t for t in item_thresholds if days_left <= t]
            if not triggered:
                continue
            threshold = min(triggered)   # tightest applicable threshold

            if not item.business:
                total_skipped += 1
                continue

            if dry_run:
                preferences = NotificationPreference(
                    receive_expiry_alerts=True,
                    receive_expiry_emails=True,
                )
            else:
                preferences, _ = NotificationPreference.objects.get_or_create(
                    user=item.business,
                )
            if not preferences.receive_expiry_alerts:
                total_skipped += 1
                continue

            if dry_run:
                claimed = True
            else:
                with transaction.atomic():
                    _, claimed = ExpiryAlert.objects.get_or_create(
                        item=item,
                        threshold_days=threshold,
                        alert_date=today,
                    )
            if not claimed:
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

            self.stdout.write(self.style.WARNING(msg))
            if not dry_run:
                notify_user(
                    item.business,
                    f'Expiry alert: {item.name}',
                    msg,
                    '/inventory/',
                    'expiry',
                )
                if preferences.receive_expiry_emails:
                    mail_admins(f'Food expiry alert: {item.name}', msg, fail_silently=False)

            total_sent += 1

        suffix = ' (dry-run — no records written)' if dry_run else ''
        action = 'previewed' if dry_run else 'sent'
        self.stdout.write(
            self.style.SUCCESS(
                f'\nDone{suffix}: {total_sent} alert(s) {action}, '
                f'{total_skipped} skipped (already alerted today).'
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
