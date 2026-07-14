"""Tests for practice pages."""

from django.test import TestCase
from django.urls import reverse

from mandarin_tone_recorder.accounts.models import User
from mandarin_tone_recorder.practice.models import PracticeDeck, PracticeSession


class PracticeViewTests(TestCase):
    def setUp(self) -> None:
        self.user = User.objects.create_user(
            username="reader",
            email="reader@example.com",
            password="correct-horse-battery-staple",
        )

    def test_landing_page_requires_login(self) -> None:
        response = self.client.get(reverse("practice:landing"))

        self.assertRedirects(
            response,
            f"{reverse('accounts:login')}?next={reverse('practice:landing')}",
        )

    def test_landing_page_renders_deck_form_for_logged_in_user(self) -> None:
        self.client.force_login(self.user)

        response = self.client.get(reverse("practice:landing"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Practice")
        self.assertContains(response, "Sentences")
        self.assertContains(response, "Create deck")

    def test_post_creates_deck_items_and_session_from_sentences(self) -> None:
        self.client.force_login(self.user)

        response = self.client.post(
            reverse("practice:landing"),
            {
                "title": "Tea",
                "source_text": "我喜欢喝茶。\n你喜欢咖啡。",
                "is_shared": "on",
            },
            follow=True,
        )

        deck = PracticeDeck.objects.get(title="Tea")
        session = PracticeSession.objects.get(deck=deck, user=self.user)
        self.assertRedirects(
            response,
            reverse("practice:session", args=(session.pk,)),
        )
        self.assertEqual(deck.user, self.user)
        self.assertTrue(deck.is_shared)
        self.assertEqual(deck.items.count(), 2)
        self.assertEqual(deck.items.first().pinyin_text, "wo3 xi3 huan1 he1 cha2 。")
        self.assertContains(response, "Tea")
        self.assertContains(response, "我喜欢喝茶。")

    def test_session_page_is_limited_to_owning_user(self) -> None:
        other_user = User.objects.create_user(
            username="other-reader",
            email="other@example.com",
            password="correct-horse-battery-staple",
        )
        deck = PracticeDeck.objects.create(
            user=other_user,
            title="Private",
            source_text="你好。",
        )
        session = PracticeSession.objects.create(deck=deck, user=other_user)
        self.client.force_login(self.user)

        response = self.client.get(reverse("practice:session", args=(session.pk,)))

        self.assertEqual(response.status_code, 404)

    def test_post_requires_at_least_one_sentence(self) -> None:
        self.client.force_login(self.user)

        response = self.client.post(
            reverse("practice:landing"),
            {
                "title": "Empty",
                "source_text": "\n  \n",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Enter at least one sentence.")
        self.assertFalse(PracticeDeck.objects.exists())
