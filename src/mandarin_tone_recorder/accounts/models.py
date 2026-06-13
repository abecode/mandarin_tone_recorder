"""Authentication models."""

from django.contrib.auth.models import AbstractUser
from django.db import models


class User(AbstractUser):
    """Application user with a required, unique email address."""

    email = models.EmailField(unique=True)

    REQUIRED_FIELDS = ["email"]
