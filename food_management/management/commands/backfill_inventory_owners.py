from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError

from food_management.models import InventoryItem


class Command(BaseCommand):
    help = 'Assign legacy unowned inventory records to an explicitly selected business user.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--business-id',
            required=True,
            help='Username of the business account that will own unassigned records.',
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Show the records that would be assigned without changing the database.',
        )

    def handle(self, *args, **options):
        username = options['business_id'].strip()
        user_model = get_user_model()
        try:
            owner = user_model.objects.get(username=username)
        except user_model.DoesNotExist as exc:
            raise CommandError(f'Business username not found: {username}') from exc

        unowned = InventoryItem.objects.filter(business__isnull=True)
        count = unowned.count()
        if options['dry_run']:
            self.stdout.write(f'{count} unowned inventory record(s) would be assigned to {username}.')
            return

        updated = unowned.update(business=owner)
        self.stdout.write(self.style.SUCCESS(
            f'Assigned {updated} unowned inventory record(s) to {username}.'
        ))
