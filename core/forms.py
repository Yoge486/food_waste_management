from django import forms
from django.contrib.auth.models import User
from django.contrib.auth.password_validation import validate_password
from .models import UserProfile


class UserRegistrationForm(forms.ModelForm):
    ROLE_CHOICES = [
        ('business', 'Food Provider / Retailer / Restaurant'),
        ('ngo', 'NGO / Community Kitchen / Charity'),
    ]

    username = forms.CharField(
        max_length=150,
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'e.g. greenkitchen'})
    )
    email = forms.EmailField(
        required=True,
        widget=forms.EmailInput(attrs={'class': 'form-control', 'placeholder': 'name@example.com'})
    )
    password = forms.CharField(
        widget=forms.PasswordInput(attrs={
            'class': 'form-control password-strength-input',
            'placeholder': 'Create a strong password',
            'autocomplete': 'new-password',
        }),
        min_length=10,
        help_text='Use at least 10 characters with upper/lowercase letters, a number, and a symbol.',
    )
    confirm_password = forms.CharField(
        widget=forms.PasswordInput(attrs={
            'class': 'form-control',
            'placeholder': 'Confirm your password',
            'autocomplete': 'new-password',
        }),
        min_length=10,
    )
    role = forms.ChoiceField(
        choices=ROLE_CHOICES,
        widget=forms.Select(attrs={'class': 'form-select'})
    )
    organization_name = forms.CharField(
        max_length=200,
        required=True,
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Organization or Business Name'})
    )
    phone_number = forms.CharField(
        max_length=30,
        required=False,
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': '+1 (555) 000-0000'})
    )

    class Meta:
        model = User
        fields = ['username', 'email']

    def clean_username(self):
        username = self.cleaned_data.get('username')
        if User.objects.filter(username__iexact=username).exists():
            raise forms.ValidationError("This username is already taken. Please choose another.")
        return username

    def clean_password(self):
        password = self.cleaned_data.get('password')
        if password:
            validate_password(password, User(username=self.data.get('username', '')))
            requirements = {
                'an uppercase letter': any(char.isupper() for char in password),
                'a lowercase letter': any(char.islower() for char in password),
                'a number': any(char.isdigit() for char in password),
                'a symbol': any(not char.isalnum() for char in password),
            }
            missing = [label for label, present in requirements.items() if not present]
            if missing:
                joined = ', '.join(missing[:-1])
                if len(missing) > 1:
                    joined += ' and '
                joined += missing[-1]
                raise forms.ValidationError(f'Password must include {joined}.')
        return password

    def clean_email(self):
        email = self.cleaned_data.get('email')
        if User.objects.filter(email__iexact=email).exists():
            raise forms.ValidationError("An account with this email address already exists.")
        return email

    def clean(self):
        cleaned_data = super().clean()
        p1 = cleaned_data.get('password')
        p2 = cleaned_data.get('confirm_password')
        if p1 and p2 and p1 != p2:
            self.add_error('confirm_password', "Passwords do not match.")
        return cleaned_data

    def save(self, commit=True):
        user = super().save(commit=False)
        user.set_password(self.cleaned_data['password'])
        if commit:
            user.save()
            UserProfile.objects.create(
                user=user,
                role=self.cleaned_data['role'],
                organization_name=self.cleaned_data['organization_name'],
                phone_number=self.cleaned_data.get('phone_number', '')
            )
        return user


class UserLoginForm(forms.Form):
    username = forms.CharField(
        max_length=150,
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Username or Email'})
    )
    password = forms.CharField(
        widget=forms.PasswordInput(attrs={
            'class': 'form-control',
            'placeholder': 'Enter your password',
            'autocomplete': 'current-password',
        })
    )
