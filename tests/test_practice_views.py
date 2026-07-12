"""Tests for practice pages."""

from django.test import TestCase
from django.urls import reverse


class PracticeViewTests(TestCase):
    def test_landing_page_renders(self) -> None:
        response = self.client.get(reverse("practice:landing"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Practice")
