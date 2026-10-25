from datetime import timedelta

from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import UserCreationForm
from django.utils import timezone

from core.models import UserProfile

from .models import DonationRequest, InventoryItem, SurplusListing


class InventoryForm(forms.ModelForm):
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
        ]
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control'}),
            'category': forms.TextInput(attrs={'class': 'form-control'}),
            'quantity': forms.NumberInput(attrs={'class': 'form-control'}),
            'unit': forms.TextInput(attrs={'class': 'form-control'}),
            'purchase_date': forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}),
            'expiry_date': forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}),
            'storage_location': forms.TextInput(attrs={'class': 'form-control'}),
            'risk_level': forms.Select(attrs={'class': 'form-select'}),
            'notes': forms.Textarea(attrs={'rows': 3, 'class': 'form-control'}),
        }

    def clean(self):
        cleaned_data = super().clean()
        expiry_date = cleaned_data.get('expiry_date')
        purchase_date = cleaned_data.get('purchase_date')
        quantity = cleaned_data.get('quantity')

        if purchase_date and expiry_date and expiry_date < purchase_date:
            raise forms.ValidationError('Expiry date cannot be before the purchase date.')

        if quantity is not None and quantity <= 0:
            raise forms.ValidationError('Inventory quantity must be greater than zero.')

        if expiry_date:
            today = timezone.localdate()
            if expiry_date <= today + timedelta(days=3):
                cleaned_data['risk_level'] = 'critical'
            elif expiry_date <= today + timedelta(days=7):
                cleaned_data['risk_level'] = 'high'
            elif expiry_date <= today + timedelta(days=30):
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


class DonationRequestForm(forms.ModelForm):
    class Meta:
        model = DonationRequest
        fields = ['listing', 'ngo_name', 'requested_quantity', 'pickup_date', 'status', 'notes']
        widgets = {
            'listing': forms.Select(attrs={'class': 'form-select'}),
            'ngo_name': forms.TextInput(attrs={'class': 'form-control'}),
            'requested_quantity': forms.NumberInput(attrs={'class': 'form-control'}),
            'pickup_date': forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}),
            'status': forms.Select(attrs={'class': 'form-select'}),
            'notes': forms.Textarea(attrs={'rows': 3, 'class': 'form-control'}),
        }

    def clean(self):
        cleaned_data = super().clean()
        listing = cleaned_data.get('listing')
        requested_quantity = cleaned_data.get('requested_quantity')
        if listing and requested_quantity is not None and requested_quantity > listing.quantity:
            raise forms.ValidationError('Requested quantity cannot exceed the available surplus quantity.')
        if requested_quantity is not None and requested_quantity <= 0:
            raise forms.ValidationError('Requested quantity must be greater than zero.')
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
        fields = ['role', 'organization_name']
        widgets = {
            'role': forms.Select(attrs={'class': 'form-select'}),
            'organization_name': forms.TextInput(attrs={'class': 'form-control'}),
        }


class CSVImportForm(forms.Form):
    csv_file = forms.FileField(label='CSV file', help_text='Expected columns: name, category, quantity, unit, purchase_date, expiry_date, storage_location, notes')

    def clean_csv_file(self):
        csv_file = self.cleaned_data['csv_file']
        if not csv_file.name.lower().endswith('.csv'):
            raise forms.ValidationError('Upload a .csv file.')
        if csv_file.size > 5 * 1024 * 1024:
            raise forms.ValidationError('CSV files must be 5 MB or smaller.')
        return csv_file
