import csv
import json
from pathlib import Path
from tempfile import NamedTemporaryFile

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.contrib.auth import get_user_model
from django.utils import timezone
from django.utils.dateparse import parse_date

from food_management.models import Transaction


class Command(BaseCommand):
    help = 'Export Django transaction history for the ML service.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--output',
            default=str(settings.BASE_DIR / 'ml-service' / 'data' / 'live_transactions.csv'),
        )
        parser.add_argument('--business-id', default='')
        parser.add_argument('--since', default='')
        parser.add_argument(
            '--status-file',
            default='',
            help='Optional JSON file updated only after a successful export.',
        )

    def handle(self, *args, **options):
        output = Path(options['output'])
        output.parent.mkdir(parents=True, exist_ok=True)
        business_id = options['business_id'].strip()
        since = parse_date(options['since']) if options['since'].strip() else None
        if options['since'].strip() and since is None:
            raise CommandError('--since must be an ISO date (YYYY-MM-DD).')
        fields = [
            'date', 'business_id', 'category', 'sales_qty',
            'purchase_qty', 'waste_qty', 'donation_qty', 'unit',
        ]
        queryset = Transaction.objects.select_related('business').order_by(
            'date', 'business_id', 'category',
        )
        if business_id:
            try:
                business = get_user_model().objects.get(username=business_id)
            except get_user_model().DoesNotExist:
                raise CommandError(f'Business username not found: {business_id}')
            queryset = queryset.filter(business=business)
        if since:
            queryset = queryset.filter(date__gte=since)

        with NamedTemporaryFile(
            mode='w',
            newline='',
            encoding='utf-8',
            dir=output.parent,
            delete=False,
        ) as stream:
            writer = csv.DictWriter(stream, fieldnames=fields)
            writer.writeheader()
            row_count = 0
            for tx in queryset:
                writer.writerow({
                    'date': tx.date,
                    'business_id': f'biz_{tx.business_id:03d}',
                    'category': tx.category,
                    'sales_qty': tx.sales_qty,
                    'purchase_qty': tx.purchase_qty,
                    'waste_qty': tx.waste_qty,
                    'donation_qty': tx.donation_qty,
                    'unit': tx.unit,
                })
                row_count += 1
            temp_name = stream.name
        Path(temp_name).replace(output)
        status_file = options['status_file'].strip()
        if status_file:
            status_path = Path(status_file)
            status_path.parent.mkdir(parents=True, exist_ok=True)
            status_payload = {
                'status': 'success',
                'completed_at': timezone.now().isoformat(),
                'rows': row_count,
                'output': str(output),
                'business_id': business_id or None,
                'since': since.isoformat() if since else None,
            }
            with NamedTemporaryFile(
                mode='w',
                encoding='utf-8',
                dir=status_path.parent,
                delete=False,
            ) as status_stream:
                json.dump(status_payload, status_stream, indent=2)
                status_stream.write('\n')
                status_temp_name = status_stream.name
            Path(status_temp_name).replace(status_path)
        self.stdout.write(self.style.SUCCESS(
            f'Exported {row_count} transaction rows to {output}'
        ))
