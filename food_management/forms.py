from datetime import timedelta

from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import UserCreationForm
from django.utils import timezone

from core.models import UserProfile

from .models import CategoryConfig, DonationRequest, InventoryItem, SurplusListing


class InventoryForm(forms.ModelForm):
    def __init__(self, *args, **kwargs):
        self.business = kwargs.pop('business', None)
        super().__init__(*args, **kwargs)
        self.category_suggestions = list(
            CategoryConfig.objects.filter(is_active=True)
            .order_by('category')
            .values_list('category', flat=True)
        )

    class Meta:
        model = InventoryItem
        fields = [
            'name',
            'category',
            'quantity',
            'unit',
            'purchase_date',
            'expiry_date',
            'storage_location',
            'risk_level',
            'notes',
            'barcode',
        ]
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control'}),
            'category': forms.TextInput(attrs={'class': 'form-control', 'list': 'category-suggestions'}),
            'quantity': forms.NumberInput(attrs={'class': 'form-control'}),
            'unit': forms.TextInput(attrs={'class': 'form-control'}),
            'purchase_date': forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}),
            'expiry_date': forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}),
            'storage_location': forms.TextInput(attrs={'class': 'form-control'}),
            'risk_level': forms.Select(attrs={'class': 'form-select'}),
            'notes': forms.Textarea(attrs={'rows': 3, 'class': 'form-control'}),
            'barcode': forms.TextInput(attrs={'class': 'form-control', 'autocomplete': 'off'}),
        }

    def clean(self):
        cleaned_data = super().clean()
        expiry_date = cleaned_data.get('expiry_date')
        purchase_date = cleaned_data.get('purchase_date')
        quantity = cleaned_data.get('quantity')
        barcode = (cleaned_data.get('barcode') or '').strip()

        if purchase_date and expiry_date and expiry_date < purchase_date:
            raise forms.ValidationError('Expiry date cannot be before the purchase date.')

        if quantity is not None and quantity <= 0:
            raise forms.ValidationError('Inventory quantity must be greater than zero.')

        if barcode and self.business:
            duplicate = InventoryItem.objects.filter(
                business=self.business,
                barcode=barcode,
            ).exclude(pk=self.instance.pk)
            if duplicate.exists():
                self.add_error('barcode', 'This barcode is already assigned to another inventory item.')

        if expiry_date:
            today = timezone.localdate()
            category = (cleaned_data.get('category') or '').strip().lower()
            config = CategoryConfig.objects.filter(category__iexact=category, is_active=True).first()
            critical_days = config.critical_days if config else 3
            high_days = config.high_days if config else 7
            medium_days = config.medium_days if config else 30
            if expiry_date <= today + timedelta(days=critical_days):
                cleaned_data['risk_level'] = 'critical'
            elif expiry_date <= today + timedelta(days=high_days):
                cleaned_data['risk_level'] = 'high'
            elif expiry_date <= today + timedelta(days=medium_days):
                cleaned_data['risk_level'] = 'medium'
            else:
                cleaned_data['risk_level'] = 'low'
        return cleaned_data


class SurplusListingForm(forms.ModelForm):
    class Meta:
        model = SurplusListing
        fields = [
            'food_name',
            'category',
            'quantity',
            'unit',
            'expiry_date',
            'pickup_location',
            'availability_window',
            'status',
            'notes',
        ]
        widgets = {
            'food_name': forms.TextInput(attrs={'class': 'form-control'}),
            'category': forms.TextInput(attrs={'class': 'form-control'}),
            'quantity': forms.NumberInput(attrs={'class': 'form-control'}),
            'unit': forms.TextInput(attrs={'class': 'form-control'}),
            'expiry_date': forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}),
            'pickup_location': forms.TextInput(attrs={'class': 'form-control'}),
            'availability_window': forms.TextInput(attrs={'class': 'form-control'}),
            'status': forms.Select(attrs={'class': 'form-select'}),
            'notes': forms.Textarea(attrs={'rows': 3, 'class': 'form-control'}),
        }

    def clean(self):
        cleaned_data = super().clean()
        quantity = cleaned_data.get('quantity')
        expiry_date = cleaned_data.get('expiry_date')
        if quantity is not None and quantity <= 0:
            raise forms.ValidationError('Surplus quantity must be greater than zero.')
        if expiry_date and expiry_date < timezone.localdate():
            raise forms.ValidationError('Expired food cannot be listed for donation.')
        return cleaned_data


class DonationRequestForm(forms.ModelForm):
    class Meta:
        model = DonationRequest
        fields = ['listing', 'ngo_name', 'requested_quantity', 'pickup_date', 'notes']
        widgets = {
            'listing': forms.Select(attrs={'class': 'form-select'}),
            'ngo_name': forms.TextInput(attrs={'class': 'form-control'}),
            'requested_quantity': forms.NumberInput(attrs={'class': 'form-control'}),
            'pickup_date': forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}),
            'status': forms.Select(attrs={'class': 'form-select'}),
            'notes': forms.Textarea(attrs={'rows': 3, 'class': 'form-control'}),
        }

    def __init__(self, *args, **kwargs):
        selected_listing_id = kwargs.pop('selected_listing_id', None)
        super().__init__(*args, **kwargs)
        self.fields['listing'].queryset = SurplusListing.objects.filter(status='available').order_by('expiry_date')
        if selected_listing_id:
            try:
                self.fields['listing'].initial = int(selected_listing_id)
            except (TypeError, ValueError):
                pass

    def clean(self):
        cleaned_data = super().clean()
        listing = cleaned_data.get('listing')
        requested_quantity = cleaned_data.get('requested_quantity')

        if listing is None:
            raise forms.ValidationError('Please select a valid surplus listing.')
        if listing.status != 'available':
            raise forms.ValidationError('This food lot is no longer available for donation requests.')

        if requested_quantity is not None and requested_quantity <= 0:
            raise forms.ValidationError('Requested quantity must be greater than zero.')

        if listing and requested_quantity is not None:
            remaining = listing.remaining_quantity
            if requested_quantity > remaining:
                raise forms.ValidationError(
                    f'Requested quantity cannot exceed the remaining available quantity ({remaining} {listing.unit}).'
                )

        return cleaned_data


class UserRegistrationForm(UserCreationForm):
    email = forms.EmailField(required=True)
    role = forms.ChoiceField(choices=UserProfile.ROLE_CHOICES, initial='business')
    organization_name = forms.CharField(max_length=200, required=False)

    class Meta:
        model = get_user_model()
        fields = ['username', 'email', 'password1', 'password2', 'role', 'organization_name']

    def save(self, commit=True):
        user = super().save(commit=False)
        user.email = self.cleaned_data['email']
        if commit:
            user.save()
            UserProfile.objects.update_or_create(
                user=user,
                defaults={
                    'role': self.cleaned_data['role'],
                    'organization_name': self.cleaned_data.get('organization_name', ''),
                },
            )
        return user


class UserProfileForm(forms.ModelForm):
    class Meta:
        model = UserProfile
        fields = ['role', 'organization_name', 'address', 'latitude', 'longitude']
        widgets = {
            'role': forms.Select(attrs={'class': 'form-select'}),
            'organization_name': forms.TextInput(attrs={'class': 'form-control'}),
            'address': forms.Textarea(attrs={'class': 'form-control', 'rows': 2}),
            'latitude': forms.NumberInput(attrs={
                'class': 'form-control',
                'step': '0.000001',
                'placeholder': 'e.g. 13.0827',
            }),
            'longitude': forms.NumberInput(attrs={
                'class': 'form-control',
                'step': '0.000001',
                'placeholder': 'e.g. 80.2707',
            }),
        }

    def clean(self):
        cleaned_data = super().clean()
        latitude = cleaned_data.get('latitude')
        longitude = cleaned_data.get('longitude')
        if (latitude is None) != (longitude is None):
            raise forms.ValidationError('Enter both latitude and longitude, or leave both blank.')
        if latitude is not None and not (-90 <= latitude <= 90):
            self.add_error('latitude', 'Latitude must be between -90 and 90.')
        if longitude is not None and not (-180 <= longitude <= 180):
            self.add_error('longitude', 'Longitude must be between -180 and 180.')
        return cleaned_data


class CSVImportForm(forms.Form):
    csv_file = forms.FileField(label='CSV file', help_text='Expected columns: name, category, quantity, unit, purchase_date, expiry_date, storage_location, notes')

    def clean_csv_file(self):
        csv_file = self.cleaned_data['csv_file']
        if not csv_file.name.lower().endswith('.csv'):
            raise forms.ValidationError('Upload a .csv file.')
        if csv_file.size > 5 * 1024 * 1024:
            raise forms.ValidationError('CSV files must be 5 MB or smaller.')
        return csv_file
