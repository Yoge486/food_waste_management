from datetime import date, timedelta
import csv
import json
import os
from pathlib import Path
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase
from django.urls import reverse

from core.models import UserProfile

from .forms import DonationRequestForm, InventoryForm
from .models import (
    CategoryConfig,
    DonationRequest,
    ExpiryAlert,
    InAppNotification,
    InventoryItem,
    NotificationPreference,
    SurplusListing,
    Transaction,
    POSApiKey,
    POSIdempotencyKey,
)


class InventoryValidationTests(TestCase):
    def setUp(self):
        self.business = get_user_model().objects.create_user(
            username='business-owner',
            password='StrongPassword9!',
        )
        UserProfile.objects.create(user=self.business, role='business')
        self.other_business = get_user_model().objects.create_user(
            username='other-owner',
            password='StrongPassword9!',
        )
        UserProfile.objects.create(user=self.other_business, role='business')
        self.ngo = get_user_model().objects.create_user(
            username='ngo-owner',
            password='StrongPassword9!',
        )
        UserProfile.objects.create(user=self.ngo, role='ngo')

    def test_admin_dashboard_requires_admin_role(self):
        user = get_user_model().objects.create_user(username='normal', password='strongpass123')
        UserProfile.objects.create(user=user, role='business')
        self.client.login(username='normal', password='strongpass123')

        response = self.client.get('/admin-panel/', follow=True)

        self.assertRedirects(response, '/dashboard/', fetch_redirect_response=False)

    def test_admin_can_remove_any_stakeholder_for_malpractice(self):
        admin = get_user_model().objects.create_user(
            username='platform-admin',
            password='StrongPassword9!',
        )
        UserProfile.objects.create(user=admin, role='admin')
        target = get_user_model().objects.create_user(
            username='malpractice-user',
            password='StrongPassword9!',
        )
        UserProfile.objects.create(user=target, role='ngo')
        self.client.login(username='platform-admin', password='StrongPassword9!')

        response = self.client.post(reverse('admin_user_delete', args=[target.pk]))

        self.assertRedirects(response, '/admin-panel/', fetch_redirect_response=False)
        self.assertFalse(get_user_model().objects.filter(pk=target.pk).exists())

    def test_admin_cannot_remove_self_or_superuser(self):
        admin = get_user_model().objects.create_user(
            username='moderator-admin',
            password='StrongPassword9!',
        )
        UserProfile.objects.create(user=admin, role='admin')
        superuser = get_user_model().objects.create_superuser(
            username='root-admin',
            password='StrongPassword9!',
            email='root@example.com',
        )
        self.client.login(username='moderator-admin', password='StrongPassword9!')

        self.client.post(reverse('admin_user_delete', args=[admin.pk]))
        self.client.post(reverse('admin_user_delete', args=[superuser.pk]))

        self.assertTrue(get_user_model().objects.filter(pk=admin.pk).exists())
        self.assertTrue(get_user_model().objects.filter(pk=superuser.pk).exists())

    def test_inventory_form_sets_risk_level_for_near_expiry(self):
        form = InventoryForm(
            data={
                'name': 'Milk',
                'category': 'Dairy',
                'quantity': 15,
                'unit': 'litres',
                'purchase_date': date.today() - timedelta(days=2),
                'expiry_date': date.today() + timedelta(days=2),
                'storage_location': 'Fridge',
                'risk_level': 'low',
                'notes': 'Fresh delivery',
            }
        )
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data['risk_level'], 'critical')

    def test_inventory_form_uses_category_specific_thresholds(self):
        CategoryConfig.objects.create(
            category='dairy',
            critical_days=1,
            high_days=2,
            medium_days=5,
        )
        form = InventoryForm(data={
            'name': 'Milk',
            'category': 'dairy',
            'quantity': 1,
            'unit': 'litres',
            'purchase_date': date.today(),
            'expiry_date': date.today() + timedelta(days=2),
            'storage_location': 'Fridge',
            'risk_level': 'low',
            'notes': '',
        })
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data['risk_level'], 'high')

    def test_inventory_risk_score_uses_category_specific_thresholds(self):
        CategoryConfig.objects.create(
            category='dairy',
            critical_days=1,
            high_days=2,
            medium_days=5,
        )
        item = InventoryItem.objects.create(
            business=self.business,
            name='Configured milk',
            category='dairy',
            quantity=1,
            purchase_date=date.today(),
            expiry_date=date.today() + timedelta(days=2),
            risk_level='high',
        )
        self.assertEqual(item.calculate_waste_risk_score(), 65)

    def test_inventory_form_accepts_and_limits_barcode_value(self):
        form = InventoryForm(data={
            'name': 'Milk',
            'category': 'dairy',
            'quantity': 1,
            'unit': 'litres',
            'purchase_date': date.today(),
            'expiry_date': date.today() + timedelta(days=10),
            'storage_location': 'Fridge',
            'risk_level': 'low',
            'notes': '',
            'barcode': '0123456789012',
        })
        self.assertTrue(form.is_valid(), form.errors)
        item = form.save(commit=False)
        self.assertEqual(item.barcode, '0123456789012')

    def test_inventory_form_rejects_duplicate_barcode_for_same_business(self):
        InventoryItem.objects.create(
            business=self.business,
            name='Existing milk',
            category='dairy',
            quantity=1,
            purchase_date=date.today(),
            expiry_date=date.today() + timedelta(days=10),
            barcode='same-code',
        )
        form = InventoryForm(
            data={
                'name': 'New milk',
                'category': 'dairy',
                'quantity': 1,
                'unit': 'kg',
                'purchase_date': date.today(),
                'expiry_date': date.today() + timedelta(days=10),
                'storage_location': 'Fridge',
                'risk_level': 'low',
                'notes': '',
                'barcode': 'same-code',
            },
            business=self.business,
        )
        self.assertFalse(form.is_valid())
        self.assertIn('already assigned', str(form.errors))

    def test_inventory_barcode_lookup_is_tenant_scoped(self):
        InventoryItem.objects.create(
            business=self.other_business,
            name='Private barcode item',
            category='dairy',
            quantity=2,
            purchase_date=date.today(),
            expiry_date=date.today() + timedelta(days=10),
            barcode='private-code',
        )
        self.client.login(username='business-owner', password='StrongPassword9!')
        hidden = self.client.get(
            reverse('inventory_barcode_lookup'),
            {'barcode': 'private-code'},
        )
        self.assertEqual(hidden.status_code, 404)

        own_item = InventoryItem.objects.create(
            business=self.business,
            name='Own barcode item',
            category='produce',
            quantity=3,
            purchase_date=date.today(),
            expiry_date=date.today() + timedelta(days=5),
            barcode='own-code',
        )
        found = self.client.get(
            reverse('inventory_barcode_lookup'),
            {'barcode': own_item.barcode},
        )
        self.assertEqual(found.status_code, 200)
        self.assertEqual(found.json()['item_id'], own_item.pk)

    def test_donation_request_rejects_quantity_above_surplus(self):
        listing = SurplusListing.objects.create(
            food_name='Bread',
            category='Bakery',
            quantity=5,
            unit='loaves',
            expiry_date=date.today() + timedelta(days=4),
            pickup_location='Warehouse',
        )
        form = DonationRequestForm(
            data={
                'listing': listing.pk,
                'ngo_name': 'Green Food Bank',
                'requested_quantity': 10,
                'pickup_date': date.today() + timedelta(days=1),
                'status': 'requested',
                'notes': 'Urgent',
            }
        )
        self.assertFalse(form.is_valid())
        self.assertIn('Requested quantity cannot exceed', str(form.errors))

    def test_donation_request_rejects_quantity_exceeding_remaining_quantity(self):
        listing = SurplusListing.objects.create(
            food_name='Rice',
            category='Grains',
            quantity=10,
            unit='kg',
            expiry_date=date.today() + timedelta(days=3),
            pickup_location='Community Kitchen',
        )
        DonationRequest.objects.create(
            listing=listing,
            ngo_name='Food Bank A',
            requested_quantity=3,
            pickup_date=date.today() + timedelta(days=1),
            status='requested',
        )
        DonationRequest.objects.create(
            listing=listing,
            ngo_name='Food Bank B',
            requested_quantity=2,
            pickup_date=date.today() + timedelta(days=2),
            status='scheduled',
        )

        form = DonationRequestForm(
            data={
                'listing': listing.pk,
                'ngo_name': 'Green Food Bank',
                'requested_quantity': 6,
                'pickup_date': date.today() + timedelta(days=1),
                'status': 'requested',
                'notes': 'Urgent',
            }
        )
        self.assertFalse(form.is_valid())
        self.assertIn('remaining available quantity', str(form.errors))

    def test_dashboard_loads_with_summary_cards(self):
        InventoryItem.objects.create(
            name='Tomatoes',
            category='Produce',
            quantity=20,
            unit='kg',
            purchase_date=date.today() - timedelta(days=10),
            expiry_date=date.today() + timedelta(days=5),
        )
        response = self.client.get('/dashboard/')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Inventory Risk Split')
        self.assertContains(response, 'Zero-Waste Streak')

    def test_inventory_list_shows_smart_action_recommendation(self):
        InventoryItem.objects.create(
            business=self.business,
            name='Urgent tomatoes',
            category='produce',
            quantity=4,
            purchase_date=date.today(),
            expiry_date=date.today() + timedelta(days=2),
        )
        self.client.login(username='business-owner', password='StrongPassword9!')
        response = self.client.get('/inventory/')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Post to surplus marketplace now')

    def test_notification_badge_is_user_scoped(self):
        InAppNotification.objects.create(
            user=self.business,
            title='Expiry',
            message='Act now',
        )
        self.client.login(username='business-owner', password='StrongPassword9!')
        response = self.client.get('/dashboard/')
        self.assertEqual(response.context['unread_notification_count'], 1)

    def test_analytics_page_is_available_to_authenticated_users(self):
        self.client.login(username='business-owner', password='StrongPassword9!')
        response = self.client.get('/analytics/')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Impact analytics')

    def test_surplus_map_includes_configured_ngo_coordinates(self):
        UserProfile.objects.filter(user=self.ngo).update(
            organization_name='Mapped Food Bank',
            latitude='13.082700',
            longitude='80.270700',
        )
        response = self.client.get('/surplus/')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Mapped Food Bank')
        self.assertContains(response, '13.0827')

    def test_analytics_filters_date_range_and_calculates_diversion(self):
        Transaction.objects.create(
            business=self.business,
            date=date.today() - timedelta(days=10),
            category='dairy',
            waste_qty=4,
            donation_qty=6,
        )
        Transaction.objects.create(
            business=self.business,
            date=date.today(),
            category='dairy',
            waste_qty=2,
            donation_qty=2,
        )
        self.client.login(username='business-owner', password='StrongPassword9!')
        response = self.client.get('/analytics/', {
            'start_date': date.today().isoformat(),
            'end_date': date.today().isoformat(),
        })
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['totals']['waste'], 2.0)
        self.assertEqual(response.context['totals']['donated'], 2.0)
        self.assertEqual(response.context['diversion_percentage'], 50.0)

    def test_analytics_includes_category_and_recovery_chart_data(self):
        listing = SurplusListing.objects.create(
            business=self.business,
            food_name='Recovered rice',
            category='grains',
            quantity=5,
            unit='kg',
            expiry_date=date.today() + timedelta(days=2),
            pickup_location='Kitchen',
        )
        DonationRequest.objects.create(
            listing=listing,
            requested_by=self.ngo,
            ngo_name='Food bank',
            requested_quantity=4,
            pickup_date=date.today(),
            status='collected',
        )
        Transaction.objects.create(
            business=self.business,
            date=date.today(),
            category='grains',
            waste_qty=1,
            donation_qty=4,
        )
        self.client.login(username='business-owner', password='StrongPassword9!')
        response = self.client.get('/analytics/')
        self.assertEqual(response.status_code, 200)
        self.assertIn('grains', response.context['category_chart'])
        self.assertIn('recovered', response.context['recovery_chart'])

    def test_analytics_csv_export_is_date_filtered_and_tenant_safe(self):
        Transaction.objects.create(
            business=self.business,
            date=date.today(),
            category='dairy',
            waste_qty=2,
        )
        Transaction.objects.create(
            business=self.other_business,
            date=date.today(),
            category='produce',
            waste_qty=9,
        )
        self.client.login(username='business-owner', password='StrongPassword9!')
        response = self.client.get('/analytics/', {'format': 'csv'})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'text/csv')
        self.assertIn(b'dairy', response.content)
        self.assertNotIn(b'produce', response.content)

    def test_export_transactions_writes_ml_compatible_business_ids(self):
        Transaction.objects.create(
            business=self.business,
            date=date.today(),
            category='dairy',
            sales_qty=4,
            purchase_qty=8,
            waste_qty=1,
            donation_qty=2,
            unit='kg',
        )
        output = self._testMethodName + '.csv'
        try:
            call_command('export_transactions', output=output)
            with open(output, newline='', encoding='utf-8') as stream:
                rows = list(csv.DictReader(stream))
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]['business_id'], f'biz_{self.business.pk:03d}')
            self.assertEqual(rows[0]['category'], 'dairy')
        finally:
            if os.path.exists(output):
                os.remove(output)

    def test_export_transactions_writes_atomic_success_status(self):
        Transaction.objects.create(
            business=self.business,
            date=date.today(),
            category='produce',
            waste_qty=3,
        )
        output = Path(self._testMethodName + '.csv')
        status = Path(self._testMethodName + '.json')
        try:
            call_command(
                'export_transactions',
                output=str(output),
                status_file=str(status),
            )
            with status.open(encoding='utf-8') as stream:
                payload = json.load(stream)
            self.assertEqual(payload['status'], 'success')
            self.assertEqual(payload['rows'], 1)
            self.assertEqual(payload['output'], str(output))
            self.assertTrue(output.exists())
        finally:
            output.unlink(missing_ok=True)
            status.unlink(missing_ok=True)

    def test_export_transactions_rejects_unknown_business(self):
        with self.assertRaisesMessage(CommandError, 'Business username not found'):
            call_command(
                'export_transactions',
                output=self._testMethodName + '.csv',
                business_id='missing-business',
            )

    def test_pos_transaction_ingest_records_sale_and_waste(self):
        api_key = POSApiKey.objects.create(
            business=self.business,
            key='pos-test-key',
        )
        headers = {'HTTP_X_API_KEY': api_key.key}
        sale = self.client.post(
            reverse('pos_transaction_ingest'),
            data={
                'event_type': 'sale',
                'category': 'Dairy',
                'quantity': '2.5',
                'unit': 'kg',
            },
            content_type='application/json',
            **headers,
        )
        waste = self.client.post(
            reverse('pos_transaction_ingest'),
            data={
                'event_type': 'waste',
                'category': 'dairy',
                'quantity': '0.5',
                'unit': 'kg',
            },
            content_type='application/json',
            **headers,
        )
        self.assertEqual(sale.status_code, 201)
        self.assertEqual(waste.status_code, 201)
        transaction = Transaction.objects.get(
            business=self.business,
            date=date.today(),
            category='dairy',
        )
        self.assertEqual(transaction.sales_qty, 2.5)
        self.assertEqual(transaction.waste_qty, 0.5)

    def test_pos_transaction_ingest_is_idempotent(self):
        api_key = POSApiKey.objects.create(
            business=self.business,
            key='pos-idempotent-key',
        )
        response_data = {
            'event_type': 'waste',
            'category': 'produce',
            'quantity': 3,
        }
        first = self.client.post(
            reverse('pos_transaction_ingest'),
            data=response_data,
            content_type='application/json',
            HTTP_X_API_KEY=api_key.key,
            HTTP_IDEMPOTENCY_KEY='event-123',
        )
        second = self.client.post(
            reverse('pos_transaction_ingest'),
            data=response_data,
            content_type='application/json',
            HTTP_X_API_KEY=api_key.key,
            HTTP_IDEMPOTENCY_KEY='event-123',
        )
        self.assertEqual(first.status_code, 201)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(Transaction.objects.filter(business=self.business).count(), 1)
        self.assertEqual(
            Transaction.objects.get(business=self.business).waste_qty,
            3,
        )

    def test_pos_transaction_ingest_rejects_invalid_event(self):
        api_key = POSApiKey.objects.create(
            business=self.business,
            key='pos-invalid-key',
        )
        response = self.client.post(
            reverse('pos_transaction_ingest'),
            data={
                'event_type': 'purchase',
                'category': 'dairy',
                'quantity': 1,
            },
            content_type='application/json',
            HTTP_X_API_KEY=api_key.key,
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(Transaction.objects.filter(business=self.business).count(), 0)

    def test_seed_demo_data_creates_risk_scenarios(self):
        call_command('seed_demo_data')

        business = get_user_model().objects.get(username='demo_business')
        items = InventoryItem.objects.filter(business=business)
        self.assertEqual(items.count(), 3)
        expired = items.get(name='Expired Milk - Demo')
        self.assertEqual(expired.risk_level, 'critical')
        self.assertGreaterEqual(expired.calculate_waste_risk_score(), 70)
        self.assertGreaterEqual(
            items.get(name='Biryani Trays - Demo').calculate_waste_risk_score(),
            70,
        )
        self.assertLess(
            items.get(name='Fresh Rice Bags - Demo').calculate_waste_risk_score(),
            70,
        )
        self.assertTrue(
            SurplusListing.objects.filter(
                business=business,
                food_name='Biryani Trays - Demo',
                status='available',
            ).exists()
        )

    @patch('food_management.management.commands.send_expiry_alerts.mail_admins')
    def test_expiry_command_creates_one_notification_and_deduplicates(self, mail_admins):
        item = InventoryItem.objects.create(
            business=self.business,
            name='Expiring Milk',
            category='dairy',
            quantity=2,
            purchase_date=date.today(),
            expiry_date=date.today() + timedelta(days=1),
        )

        call_command('send_expiry_alerts')
        call_command('send_expiry_alerts')

        self.assertEqual(ExpiryAlert.objects.filter(item=item).count(), 1)
        self.assertEqual(InAppNotification.objects.filter(user=self.business).count(), 1)
        mail_admins.assert_called_once()

    @patch('food_management.management.commands.send_expiry_alerts.mail_admins')
    def test_expiry_dry_run_does_not_write_or_send(self, mail_admins):
        item = InventoryItem.objects.create(
            business=self.business,
            name='Dry Run Milk',
            category='dairy',
            quantity=2,
            purchase_date=date.today(),
            expiry_date=date.today() + timedelta(days=1),
        )

        call_command('send_expiry_alerts', dry_run=True)

        self.assertFalse(ExpiryAlert.objects.filter(item=item).exists())
        self.assertFalse(InAppNotification.objects.filter(user=self.business).exists())
        self.assertFalse(NotificationPreference.objects.filter(user=self.business).exists())
        mail_admins.assert_not_called()

    @patch('food_management.management.commands.send_expiry_alerts.mail_admins')
    def test_expiry_preferences_can_disable_alerts(self, mail_admins):
        item = InventoryItem.objects.create(
            business=self.business,
            name='Muted Milk',
            category='dairy',
            quantity=2,
            purchase_date=date.today(),
            expiry_date=date.today() + timedelta(days=1),
        )
        NotificationPreference.objects.create(
            user=self.business,
            receive_expiry_alerts=False,
        )

        call_command('send_expiry_alerts')

        self.assertFalse(ExpiryAlert.objects.filter(item=item).exists())
        self.assertFalse(InAppNotification.objects.filter(user=self.business).exists())
        mail_admins.assert_not_called()

    def test_business_cannot_edit_or_delete_another_business_inventory(self):
        item = InventoryItem.objects.create(
            business=self.other_business,
            name='Private stock',
            category='dairy',
            quantity=2,
            purchase_date=date.today(),
            expiry_date=date.today() + timedelta(days=10),
        )
        self.client.login(username='business-owner', password='StrongPassword9!')

        edit_response = self.client.get(f'/inventory/{item.pk}/edit/')
        delete_response = self.client.post(f'/inventory/{item.pk}/delete/')

        self.assertEqual(edit_response.status_code, 404)
        self.assertEqual(delete_response.status_code, 404)
        self.assertTrue(InventoryItem.objects.filter(pk=item.pk).exists())

    def test_donation_request_is_owned_by_authenticated_requester(self):
        listing = SurplusListing.objects.create(
            business=self.business,
            food_name='Bread',
            category='bakery',
            quantity=5,
            unit='kg',
            expiry_date=date.today() + timedelta(days=2),
            pickup_location='Kitchen',
        )
        self.client.login(username='ngo-owner', password='StrongPassword9!')

        response = self.client.post('/donations/request/', {
            'listing': listing.pk,
            'ngo_name': 'Community Kitchen',
            'requested_quantity': 2,
            'pickup_date': date.today() + timedelta(days=1),
            'notes': '',
        })

        self.assertEqual(response.status_code, 302)
        donation = DonationRequest.objects.get()
        self.assertEqual(donation.requested_by, self.ngo)
        self.assertEqual(self.client.get('/donations/').context['requests'].count(), 1)

    def test_only_listing_owner_can_confirm_and_collect_donation(self):
        listing = SurplusListing.objects.create(
            business=self.business,
            food_name='Rice',
            category='packaged',
            quantity=5,
            unit='kg',
            expiry_date=date.today() + timedelta(days=2),
            pickup_location='Kitchen',
        )
        donation = DonationRequest.objects.create(
            listing=listing,
            requested_by=self.ngo,
            ngo_name='Community Kitchen',
            requested_quantity=2,
            pickup_date=date.today() + timedelta(days=1),
        )
        self.client.login(username='ngo-owner', password='StrongPassword9!')

        denied = self.client.post(
            f'/donations/{donation.pk}/update/',
            {'status': 'scheduled'},
        )
        self.assertEqual(denied.status_code, 302)
        donation.refresh_from_db()
        self.assertEqual(donation.status, 'requested')

        self.client.login(username='business-owner', password='StrongPassword9!')
        self.client.post(f'/donations/{donation.pk}/update/', {'status': 'scheduled'})
        self.client.post(f'/donations/{donation.pk}/update/', {'status': 'collected'})

        donation.refresh_from_db()
        listing.refresh_from_db()
        self.assertEqual(donation.status, 'collected')
        self.assertEqual(listing.status, 'available')
        self.assertTrue(Transaction.objects.filter(
            business=self.business,
            category='packaged',
            donation_qty=2,
        ).exists())
