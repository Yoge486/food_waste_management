import csv
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation
from io import StringIO

from django.contrib import messages
from django.contrib.auth import login, logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import AuthenticationForm
from django.contrib.auth.models import User
from django.core.paginator import Paginator
from django.db.models import Q, Sum
from django.db.models.functions import TruncMonth
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from core.models import UserProfile

from .access import get_or_create_user_profile, role_required
from .forms import (
    CSVImportForm,
    DonationRequestForm,
    InventoryForm,
    SurplusListingForm,
    UserProfileForm,
    UserRegistrationForm,
)
from .models import DonationRequest, InventoryItem, SurplusListing
from .services import estimate_waste_risk, get_gamification_summary, get_leaderboard, record_transaction


def dashboard(request):
    if request.user.is_authenticated:
        get_or_create_user_profile(request.user)

    today = timezone.localdate()
    # Scope inventory to the logged-in user; admins see all records
    if request.user.is_authenticated and not request.user.is_superuser:
        inventory = InventoryItem.objects.filter(business=request.user).order_by('-created_at')
    else:
        inventory = InventoryItem.objects.all().order_by('-created_at')
    recent_inventory = inventory[:5]
    total_inventory = inventory.count()
    near_expiry = inventory.filter(expiry_date__lte=today + timedelta(days=7)).count()
    urgent_inventory = inventory.filter(expiry_date__lte=today + timedelta(days=3)).count()
    high_risk = inventory.filter(risk_level__in=['high', 'critical']).count()
    active_surplus = SurplusListing.objects.filter(status='available').count()
    donation_requests = DonationRequest.objects.count()
    collected_donations = DonationRequest.objects.filter(status='collected').count()
    recovered_quantity = DonationRequest.objects.filter(status='collected').aggregate(total=Sum('requested_quantity'))['total'] or 0
    prediction = estimate_waste_risk(inventory)
    gamification = get_gamification_summary(request.user)
    leaderboard = get_leaderboard(limit=5)
    expiry_alerts = inventory.filter(
        expiry_date__lte=today + timedelta(days=7),
    ).order_by('expiry_date', 'name')[:5]

    first_month = (today.replace(day=1) - timedelta(days=150)).replace(day=1)
    monthly_recovery = {
        entry['month'].date(): float(entry['total'] or 0)
        for entry in DonationRequest.objects.filter(
            status='collected',
            created_at__date__gte=first_month,
        ).annotate(month=TruncMonth('created_at')).values('month').annotate(
            total=Sum('requested_quantity'),
        )
    }
    recovery_months = []
    for offset in range(5, -1, -1):
        month = today.replace(day=1)
        for _ in range(offset):
            month = (month - timedelta(days=1)).replace(day=1)
        recovery_months.append(month)
    recovery_chart = {
        'labels': [month.strftime('%b %Y') for month in recovery_months],
        'data': [monthly_recovery.get(month, 0) for month in recovery_months],
    }
    expiry_chart = {
        'safe': inventory.filter(expiry_date__gt=today + timedelta(days=7)).count(),
        'watch': inventory.filter(
            expiry_date__gt=today + timedelta(days=3),
            expiry_date__lte=today + timedelta(days=7),
        ).count(),
        'urgent': urgent_inventory,
    }

    context = {
        'total_inventory': total_inventory,
        'near_expiry': near_expiry,
        'urgent_inventory': urgent_inventory,
        'high_risk': high_risk,
        'active_surplus': active_surplus,
        'donation_requests': donation_requests,
        'collected_donations': collected_donations,
        'recovered_quantity': recovered_quantity,
        'recent_inventory': recent_inventory,
        'expiry_alerts': expiry_alerts,
        'recovery_chart': recovery_chart,
        'expiry_chart': expiry_chart,
        'prediction': prediction,
        'gamification': gamification,
        'leaderboard': leaderboard,
    }
    return render(request, 'food_management/dashboard.html', context)


def dashboard_metrics(request):
    today = timezone.localdate()
    inventory = InventoryItem.objects.all()
    recovered_quantity = DonationRequest.objects.filter(status='collected').aggregate(
        total=Sum('requested_quantity'),
    )['total'] or 0
    response = JsonResponse({
        'total_inventory': inventory.count(),
        'near_expiry': inventory.filter(expiry_date__lte=today + timedelta(days=7)).count(),
        'urgent_inventory': inventory.filter(expiry_date__lte=today + timedelta(days=3)).count(),
        'active_surplus': SurplusListing.objects.filter(status='available').count(),
        'donation_requests': DonationRequest.objects.exclude(status='collected').count(),
        'recovered_quantity': float(recovered_quantity),
    })
    response['Cache-Control'] = 'no-store'
    return response


@role_required('admin')
def admin_dashboard(request):
    inventory = InventoryItem.objects.all()
    recent_requests = DonationRequest.objects.select_related('listing').order_by('-created_at')[:5]

    search_user = request.GET.get('search_user', '').strip()
    active_tab = request.GET.get('tab', 'restaurants')

    # Fetch food providers / restaurants and NGOs
    business_profiles = UserProfile.objects.filter(role='business').select_related('user').order_by('-created_at')
    ngo_profiles = UserProfile.objects.filter(role='ngo').select_related('user').order_by('-created_at')

    if search_user:
        business_profiles = business_profiles.filter(
            Q(user__username__icontains=search_user) |
            Q(organization_name__icontains=search_user) |
            Q(user__email__icontains=search_user) |
            Q(phone_number__icontains=search_user)
        )
        ngo_profiles = ngo_profiles.filter(
            Q(user__username__icontains=search_user) |
            Q(organization_name__icontains=search_user) |
            Q(user__email__icontains=search_user) |
            Q(phone_number__icontains=search_user)
        )

    total_businesses = UserProfile.objects.filter(role='business').count()
    total_ngos = UserProfile.objects.filter(role='ngo').count()
    total_users = User.objects.filter(is_superuser=False).count()
    suspended_users = User.objects.filter(is_active=False).count()

    summary = {
        'total_inventory': inventory.count(),
        'near_expiry': inventory.filter(expiry_date__lte=date.today() + timedelta(days=7)).count(),
        'high_risk': inventory.filter(risk_level__in=['high', 'critical']).count(),
        'active_surplus': SurplusListing.objects.filter(status='available').count(),
        'donation_requests': DonationRequest.objects.count(),
    }
    context = {
        'summary': summary,
        'inventory_count': summary['total_inventory'],
        'surplus_count': summary['active_surplus'],
        'donation_count': summary['donation_requests'],
        'recent_requests': recent_requests,
        'leaderboard': get_leaderboard(limit=5),
        'business_profiles': business_profiles,
        'ngo_profiles': ngo_profiles,
        'search_user': search_user,
        'active_tab': active_tab,
        'total_businesses': total_businesses,
        'total_ngos': total_ngos,
        'total_users': total_users,
        'suspended_users': suspended_users,
    }
    return render(request, 'food_management/admin_dashboard.html', context)


@role_required('admin')
def admin_user_toggle_status(request, user_id):
    if request.method == 'POST':
        target_user = get_object_or_404(User, pk=user_id)
        if target_user == request.user:
            messages.error(request, 'You cannot suspend your own administrative account.')
            return redirect('admin_dashboard')

        if target_user.is_superuser and not request.user.is_superuser:
            messages.error(request, 'Permission denied: Cannot modify a superuser account.')
            return redirect('admin_dashboard')

        target_user.is_active = not target_user.is_active
        target_user.save()

        status_text = "reactivated" if target_user.is_active else "suspended / deactivated due to malpractice"
        messages.success(request, f"User account '{target_user.username}' has been {status_text}.")
    return redirect('admin_dashboard')


@role_required('admin')
def admin_user_delete(request, user_id):
    if request.method == 'POST':
        target_user = get_object_or_404(User, pk=user_id)
        if target_user == request.user:
            messages.error(request, 'You cannot delete your own administrative account.')
            return redirect('admin_dashboard')

        if target_user.is_superuser and not request.user.is_superuser:
            messages.error(request, 'Permission denied: Cannot delete a superuser account.')
            return redirect('admin_dashboard')

        username = target_user.username
        target_user.delete()
        messages.success(request, f"User account '{username}' has been permanently removed due to malpractice / policy violation.")
    return redirect('admin_dashboard')


def inventory_list(request):
    # Scope to the logged-in user; admins see all
    if request.user.is_authenticated and not request.user.is_superuser:
        items = InventoryItem.objects.filter(business=request.user)
    else:
        items = InventoryItem.objects.all()
    query = request.GET.get('q', '').strip()
    risk = request.GET.get('risk', '').strip()
    category = request.GET.get('category', '').strip()
    location = request.GET.get('location', '').strip()
    expiry = request.GET.get('expiry', '').strip()
    sort = request.GET.get('sort', 'expiry')
    today = timezone.localdate()

    if query:
        items = items.filter(
            Q(name__icontains=query)
            | Q(category__icontains=query)
            | Q(storage_location__icontains=query)
            | Q(notes__icontains=query)
        )
    if risk in dict(InventoryItem.RISK_CHOICES):
        items = items.filter(risk_level=risk)
    if category:
        items = items.filter(category__iexact=category)
    if location:
        items = items.filter(storage_location__icontains=location)
    if expiry == 'expired':
        items = items.filter(expiry_date__lt=today)
    elif expiry in {'3', '7', '30'}:
        items = items.filter(expiry_date__gte=today, expiry_date__lte=today + timedelta(days=int(expiry)))

    ordering = {
        'expiry': ('expiry_date', 'name'),
        '-expiry': ('-expiry_date', 'name'),
        'name': ('name', 'expiry_date'),
        '-name': ('-name', 'expiry_date'),
        'quantity': ('quantity', 'name'),
        '-quantity': ('-quantity', 'name'),
    }
    if sort not in ordering:
        sort = 'expiry'
    items = items.order_by(*ordering[sort])

    paginator = Paginator(items, 25)
    page_obj = paginator.get_page(request.GET.get('page'))
    expiry_alerts = InventoryItem.objects.filter(
        expiry_date__lte=today + timedelta(days=3),
    ).order_by('expiry_date', 'name')[:1]

    return render(
        request,
        'food_management/inventory_list.html',
        {
            'items': page_obj.object_list,
            'page_obj': page_obj,
            'query': query,
            'risk': risk,
            'category': category,
            'categories': InventoryItem.objects.order_by('category').values_list(
                'category', flat=True,
            ).distinct(),
            'location': location,
            'expiry': expiry,
            'sort': sort,
            'expiry_alerts': expiry_alerts,
        },
    )


@role_required('business', 'admin')
def inventory_create(request):
    if request.method == 'POST':
        form = InventoryForm(request.POST)
        if form.is_valid():
            item = form.save(commit=False)
            item.business = request.user  # assign tenant owner
            item.save()
            # Record a purchase transaction for the ML data pipeline
            record_transaction(
                business=request.user,
                category=item.category,
                purchase_qty=float(item.quantity),
                unit=item.unit,
            )
            profile, _ = UserProfile.objects.get_or_create(user=request.user)
            profile.points += 10
            profile.level = max(1, profile.points // 100 + 1)
            profile.streak_days += 1
            profile.badges = list(profile.badges or [])
            if 'Inventory Keeper' not in profile.badges:
                profile.badges.append('Inventory Keeper')
            profile.save()
            return redirect('inventory_list')
    else:
        form = InventoryForm()
    return render(request, 'food_management/inventory_form.html', {'form': form})


@role_required('business', 'admin')
def inventory_update(request, item_id):
    item = get_object_or_404(InventoryItem, pk=item_id)
    if request.method == 'POST':
        form = InventoryForm(request.POST, instance=item)
        if form.is_valid():
            form.save()
            messages.success(request, 'Inventory item updated.')
            return redirect('inventory_list')
    else:
        form = InventoryForm(instance=item)
    return render(request, 'food_management/inventory_form.html', {'form': form, 'editing': True})


@role_required('business', 'admin')
def inventory_delete(request, item_id):
    item = get_object_or_404(InventoryItem, pk=item_id)
    if request.method == 'POST':
        item.delete()
        messages.success(request, 'Inventory item removed successfully.')
    return redirect('inventory_list')


@role_required('business', 'admin')
def inventory_import(request):
    if request.method == 'POST':
        form = CSVImportForm(request.POST, request.FILES)
        if form.is_valid():
            file = request.FILES['csv_file']
            try:
                text = file.read().decode('utf-8-sig')
                reader = csv.DictReader(StringIO(text), strict=True)
                rows = list(reader)
            except (UnicodeDecodeError, csv.Error) as error:
                form.add_error('csv_file', f'Unable to read this CSV file: {error}')
                return render(request, 'food_management/inventory_import.html', {'form': form})

            headers = {header.strip().lower() for header in (reader.fieldnames or []) if header}
            required_headers = {'name', 'category', 'quantity', 'purchase_date', 'expiry_date'}
            missing_headers = required_headers - headers
            if missing_headers:
                form.add_error(
                    'csv_file',
                    'Missing required column(s): ' + ', '.join(sorted(missing_headers)),
                )
                return render(request, 'food_management/inventory_import.html', {'form': form})

            imported_items = []
            rejected_rows = []
            today = timezone.localdate()
            for row in rows:
                line_number = reader.line_num
                if None in row:
                    rejected_rows.append(f'Row {line_number}: too many columns.')
                    continue
                values = {
                    str(key).strip().lower(): (value or '').strip()
                    for key, value in row.items()
                    if key is not None
                }
                name = values.get('name', '')
                category_value = values.get('category', '')
                try:
                    quantity = Decimal(values.get('quantity', ''))
                    purchase_date = date.fromisoformat(values.get('purchase_date', ''))
                    expiry_date_value = date.fromisoformat(values.get('expiry_date', ''))
                except (InvalidOperation, TypeError, ValueError):
                    rejected_rows.append(f'Row {line_number}: invalid quantity or date.')
                    continue
                if (
                    not name
                    or not category_value
                    or len(name) > 150
                    or len(category_value) > 100
                    or not quantity.is_finite()
                    or quantity <= 0
                    or quantity >= Decimal('100000000')
                    or max(0, -quantity.as_tuple().exponent) > 2
                    or expiry_date_value < purchase_date
                ):
                    rejected_rows.append(f'Row {line_number}: invalid name, category, quantity, or date range.')
                    continue

                days_until_expiry = (expiry_date_value - today).days
                risk_level = (
                    'critical' if days_until_expiry <= 3
                    else 'high' if days_until_expiry <= 7
                    else 'medium' if days_until_expiry <= 30
                    else 'low'
                )
                imported_items.append(InventoryItem(
                    business=request.user,  # tenant owner
                    name=name,
                    category=category_value,
                    quantity=quantity,
                    unit=values.get('unit') or 'kg',
                    purchase_date=purchase_date,
                    expiry_date=expiry_date_value,
                    storage_location=values.get('storage_location') or 'Main storage',
                    risk_level=risk_level,
                    notes=values.get('notes', ''),
                ))

            InventoryItem.objects.bulk_create(imported_items)
            # Record purchase transactions for imported items (aggregate by category)
            from collections import defaultdict
            cat_totals: dict = defaultdict(lambda: {'qty': 0.0, 'unit': 'kg'})
            for imp_item in imported_items:
                cat_totals[imp_item.category]['qty'] += float(imp_item.quantity)
                cat_totals[imp_item.category]['unit'] = imp_item.unit
            for cat, vals in cat_totals.items():
                record_transaction(
                    business=request.user,
                    category=cat,
                    purchase_qty=vals['qty'],
                    unit=vals['unit'],
                )
            if imported_items:
                messages.success(request, f'Imported {len(imported_items)} inventory item(s).')
            if rejected_rows:
                details = ' '.join(rejected_rows[:5])
                if len(rejected_rows) > 5:
                    details += f' And {len(rejected_rows) - 5} more row(s) were rejected.'
                messages.warning(request, f'Rejected {len(rejected_rows)} row(s): {details}')
            if not imported_items and not rejected_rows:
                messages.warning(request, 'The CSV did not contain any inventory rows.')
            return redirect('inventory_list')
    else:
        form = CSVImportForm()
    return render(request, 'food_management/inventory_import.html', {'form': form})


def surplus_list(request):
    listings = SurplusListing.objects.filter(status='available').order_by('expiry_date')
    return render(request, 'food_management/surplus_list.html', {'listings': listings})


@role_required('business', 'admin')
def surplus_listing_create(request):
    if request.method == 'POST':
        form = SurplusListingForm(request.POST)
        if form.is_valid():
            listing = form.save(commit=False)
            listing.business = request.user  # assign tenant owner
            listing.save()
            profile, _ = UserProfile.objects.get_or_create(user=request.user)
            profile.points += 20
            profile.level = max(1, profile.points // 100 + 1)
            profile.badges = list(profile.badges or [])
            if 'Food Rescuer' not in profile.badges:
                profile.badges.append('Food Rescuer')
            profile.save()
            return redirect('surplus_list')
    else:
        form = SurplusListingForm()
    return render(request, 'food_management/surplus_form.html', {'form': form})


def donation_requests(request):
    requests = DonationRequest.objects.select_related('listing').all().order_by('-created_at')
    status_filter = request.GET.get('status', '').strip()
    if status_filter:
        requests = requests.filter(status=status_filter)
    return render(request, 'food_management/donation_requests.html', {'requests': requests, 'status_filter': status_filter})


@role_required('ngo', 'business', 'admin')
def donation_request_create(request):
    if request.method == 'POST':
        form = DonationRequestForm(request.POST)
        if form.is_valid():
            form.save()
            return redirect('donation_requests')
    else:
        form = DonationRequestForm()
    return render(request, 'food_management/donation_form.html', {'form': form})


@role_required('ngo', 'business', 'admin')
def donation_status_update(request, request_id):
    donation = get_object_or_404(DonationRequest, pk=request_id)
    if request.method == 'POST':
        next_status = request.POST.get('status')
        if next_status in dict(DonationRequest.STATUS_CHOICES):
            donation.status = next_status
            donation.save()
            if next_status == 'collected':
                donation.listing.status = 'collected'
                donation.listing.save()
                # Record donation quantity in Transaction for ML pipeline
                record_transaction(
                    business=request.user,
                    category=donation.listing.category,
                    donation_qty=float(donation.requested_quantity),
                    unit=donation.listing.unit,
                )
                profile, _ = UserProfile.objects.get_or_create(user=request.user)
                profile.points += 25
                profile.level = max(1, profile.points // 100 + 1)
                profile.badges = list(profile.badges or [])
                if 'Impact Hero' not in profile.badges:
                    profile.badges.append('Impact Hero')
                profile.save()
            messages.success(request, f'Donation request marked as {next_status}.')
    return redirect('donation_requests')


def leaderboard(request):
    entries = get_leaderboard(limit=10)
    return render(request, 'food_management/leaderboard.html', {'leaderboard': entries})


def register(request):
    if request.method == 'POST':
        form = UserRegistrationForm(request.POST)
        if form.is_valid():
            user = form.save()
            get_or_create_user_profile(user)
            login(request, user)
            messages.success(request, 'Account created successfully.')
            return redirect('admin_dashboard' if get_or_create_user_profile(user).role == 'admin' else 'dashboard')
    else:
        form = UserRegistrationForm()
    return render(request, 'food_management/register.html', {'form': form})


def login_view(request):
    if request.method == 'POST':
        form = AuthenticationForm(request, data=request.POST)
        if form.is_valid():
            user = form.get_user()
            get_or_create_user_profile(user)
            login(request, user)
            messages.success(request, 'Welcome back!')
            default_target = 'admin_dashboard' if get_or_create_user_profile(user).role == 'admin' else 'dashboard'
            return redirect(request.GET.get('next') or default_target)
    else:
        form = AuthenticationForm()
    return render(request, 'food_management/login.html', {'form': form})


def logout_view(request):
    logout(request)
    messages.info(request, 'You have been logged out.')
    return redirect('dashboard')


@login_required
def profile(request):
    profile, _ = UserProfile.objects.get_or_create(user=request.user)
    if request.method == 'POST':
        form = UserProfileForm(request.POST, instance=profile)
        if form.is_valid():
            form.save()
            messages.success(request, 'Profile updated successfully.')
            return redirect('profile')
    else:
        form = UserProfileForm(instance=profile)
    return render(request, 'food_management/profile.html', {'form': form, 'profile': profile})
