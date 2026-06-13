"""Smoke tests for the initial account and application shell."""

from django.test import TestCase
from django.urls import reverse

from mandarin_tone_recorder.accounts.models import User


class AuthenticationFlowTests(TestCase):
    def test_home_page_offers_login_to_anonymous_users(self) -> None:
        response = self.client.get(reverse("home"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Log in")

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
        self.assertContains(response, "Your experiments and practice sessions")
