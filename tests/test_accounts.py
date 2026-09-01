"""Smoke tests for the initial account and application shell."""

from django.test import TestCase
from django.urls import reverse

from mandarin_tone_recorder.accounts.models import User


class AuthenticationFlowTests(TestCase):
    def test_home_page_offers_login_to_anonymous_users(self) -> None:
        response = self.client.get(reverse("home"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Mandarin Pronunciation Study")
        self.assertContains(response, reverse("participants:consent"), count=1)
        self.assertContains(response, reverse("practice:landing"), count=1)
        self.assertContains(response, reverse("accounts:login"), count=1)
        self.assertContains(response, reverse("accounts:signup"), count=1)
        self.assertContains(response, "Hugging Face")
        self.assertContains(response, "self-hosted")
        self.assertContains(response, "Log in")
        self.assertContains(response, "Sign up")

    def test_signup_creates_user_and_logs_them_in(self) -> None:
        response = self.client.post(
            reverse("accounts:signup"),
            {
                "username": "new-user",
                "email": "new@example.com",
                "password1": "correct-horse-battery-staple",
                "password2": "correct-horse-battery-staple",
            },
            follow=True,
        )

        self.assertRedirects(response, reverse("home"))
        user = User.objects.get(username="new-user")
        self.assertEqual(user.email, "new@example.com")
        self.assertContains(response, "Mandarin Pronunciation Study")
        self.assertContains(response, reverse("participants:consent"), count=1)
        self.assertContains(response, reverse("practice:landing"), count=1)

    def test_signup_rejects_duplicate_email(self) -> None:
        User.objects.create_user(
            username="existing-user",
            email="taken@example.com",
            password="correct-horse-battery-staple",
        )

        response = self.client.post(
            reverse("accounts:signup"),
            {
                "username": "new-user",
                "email": "taken@example.com",
                "password1": "correct-horse-battery-staple",
                "password2": "correct-horse-battery-staple",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "User with this Email already exists")
        self.assertFalse(User.objects.filter(username="new-user").exists())

    def test_user_can_log_in_and_reach_authenticated_home(self) -> None:
        User.objects.create_user(
            username="test-user",
            email="test@example.com",
            password="correct-horse-battery-staple",
        )

        response = self.client.post(
            reverse("accounts:login"),
            {
                "username": "test-user",
                "password": "correct-horse-battery-staple",
            },
            follow=True,
        )

        self.assertRedirects(response, reverse("home"))
        self.assertContains(response, "Mandarin Pronunciation Study")
        self.assertContains(response, reverse("participants:consent"), count=1)
        self.assertContains(response, reverse("practice:landing"), count=1)
