"""Forms for account creation."""

from django.contrib.auth.forms import UserCreationForm

from mandarin_tone_recorder.accounts.models import User


class SignUpForm(UserCreationForm):
    """Create an application user with a required email address."""

    class Meta(UserCreationForm.Meta):
        model = User
        fields = ("username", "email")
