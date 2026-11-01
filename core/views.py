from django.contrib import messages
from django.contrib.auth import authenticate, login as auth_login, logout as auth_logout
from django.contrib.auth.models import User
from django.shortcuts import redirect, render

from .forms import UserLoginForm, UserRegistrationForm


def home(request):
    """
    Renders the responsive homepage for the Food Waste Management platform.
    Supplies login and registration forms for embedded homepage modals along with live platform stats.
    """
    from django.db.models import Sum
    from food_management.models import InventoryItem, SurplusListing, DonationRequest
    from core.models import UserProfile

    login_form = UserLoginForm()
    register_form = UserRegistrationForm()

    try:
        total_items = InventoryItem.objects.count()
        active_surplus = SurplusListing.objects.filter(status='available').count()
        recovered_kg = DonationRequest.objects.filter(status='collected').aggregate(total=Sum('requested_quantity'))['total'] or 0
        total_ngos = UserProfile.objects.filter(role='ngo').count()
        featured_surplus = SurplusListing.objects.filter(status='available').order_by('-created_at')[:3]
    except Exception:
        total_items = 0
        active_surplus = 0
        recovered_kg = 0
        total_ngos = 0
        featured_surplus = []

    return render(request, 'core/home.html', {
        'login_form': login_form,
        'register_form': register_form,
        'total_items': total_items,
        'active_surplus': active_surplus,
        'recovered_kg': float(recovered_kg),
        'total_ngos': total_ngos,
        'featured_surplus': featured_surplus,
    })


def register_view(request):
    """
    Handles user registration with role assignment (Food Provider or NGO).
    """
    if request.user.is_authenticated:
        return redirect('dashboard')

    if request.method == 'POST':
        form = UserRegistrationForm(request.POST)
        if form.is_valid():
            user = form.save()
            auth_login(request, user)
            role_title = user.profile.get_role_display() if hasattr(user, 'profile') else 'User'
            messages.success(request, f"Welcome to the platform, {user.username}! Your account ({role_title}) has been registered successfully.")
            return redirect('dashboard')
        else:
            messages.error(request, "Please correct the errors in the registration form.")
    else:
        form = UserRegistrationForm()

    return render(request, 'core/register.html', {'form': form})


def login_view(request):
    """
    Handles user authentication by username or email.
    """
    if request.user.is_authenticated:
        return redirect('dashboard')

    if request.method == 'POST':
        form = UserLoginForm(request.POST)
        if form.is_valid():
            username_or_email = form.cleaned_data['username']
            password = form.cleaned_data['password']

            user = authenticate(request, username=username_or_email, password=password)
            if user is None:
                try:
                    user_obj = User.objects.get(email__iexact=username_or_email)
                    user = authenticate(request, username=user_obj.username, password=password)
                except User.DoesNotExist:
                    user = None

            if user is not None:
                auth_login(request, user)
                messages.success(request, f"Welcome back, {user.username}!")
                next_url = request.GET.get('next') or request.POST.get('next') or '/'
                return redirect(next_url)
            else:
                messages.error(request, "Invalid username/email or password.")
        else:
            messages.error(request, "Please fill in all required login fields.")
    else:
        form = UserLoginForm()

    return render(request, 'core/login.html', {'form': form})


def logout_view(request):
    """
    Logs out the current authenticated user.
    """
    auth_logout(request)
    messages.info(request, "You have been logged out successfully.")
    return redirect('core:home')
