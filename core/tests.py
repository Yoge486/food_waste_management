from django.test import TestCase

from .forms import UserRegistrationForm
from food_management.forms import UserProfileForm

# Create your tests here.


class PasswordValidationTests(TestCase):
    def registration_form(self, password):
        return UserRegistrationForm(data={
            'username': 'test-user',
            'email': 'test@example.com',
            'password': password,
            'confirm_password': password,
            'role': 'business',
            'organization_name': 'Test Kitchen',
        })

    def test_weak_password_is_rejected(self):
        form = self.registration_form('alllowercasepassword1')

        self.assertFalse(form.is_valid())
        self.assertIn('uppercase letter', str(form.errors['password']))

    def test_strong_password_is_accepted(self):
        form = self.registration_form('StrongPassword9!')

        self.assertTrue(form.is_valid(), form.errors)

    def test_profile_coordinates_must_be_provided_together(self):
        form = UserProfileForm(data={
            'role': 'ngo',
            'organization_name': 'Community Kitchen',
            'address': 'Chennai',
            'latitude': '13.0827',
            'longitude': '',
        })

        self.assertFalse(form.is_valid())
        self.assertIn('both latitude and longitude', str(form.errors))

    def test_profile_coordinates_validate_ranges(self):
        form = UserProfileForm(data={
            'role': 'ngo',
            'organization_name': 'Community Kitchen',
            'address': 'Chennai',
            'latitude': '100',
            'longitude': '200',
        })

        self.assertFalse(form.is_valid())
        self.assertIn('Latitude must be between', str(form.errors))
        self.assertIn('Longitude must be between', str(form.errors))
