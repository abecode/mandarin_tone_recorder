from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from mandarin_tone_recorder.accounts.models import User


@admin.register(User)
class RecorderUserAdmin(UserAdmin):
    """Admin configuration for application users."""

    pass
