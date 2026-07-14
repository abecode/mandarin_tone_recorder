"""Tests for practice admin customizations."""

from django.contrib.messages import get_messages
from django.test import TestCase
from django.urls import reverse

from mandarin_tone_recorder.accounts.models import User
from mandarin_tone_recorder.practice.models import PracticeDeck


class PracticeItemAdminTests(TestCase):
    def setUp(self) -> None:
        self.admin_user = User.objects.create_superuser(
            username="admin",
            email="admin@example.com",
            password="correct-horse-battery-staple",
        )
        self.deck = PracticeDeck.objects.create(
            user=self.admin_user,
            title="Admin deck",
            source_text="我喜欢喝茶。",
        )
        self.item = self.deck.items.create(
            prompt_text="我喜欢喝茶。",
            pinyin_text="stale pinyin",
            sort_order=1,
        )
        self.client.force_login(self.admin_user)

    def test_regenerate_pinyin_admin_action_updates_selected_items(self) -> None:
        response = self.client.post(
            reverse("admin:practice_practiceitem_changelist"),
            {
                "action": "regenerate_pinyin",
                "_selected_action": [str(self.item.pk)],
            },
            follow=True,
        )

        self.item.refresh_from_db()
        self.assertEqual(self.item.pinyin_text, "wo3 xi3 huan1 he1 cha2 。")
        messages = [str(message) for message in get_messages(response.wsgi_request)]
        self.assertIn(
            "Regenerated pinyin for 1 practice item(s).",
            messages,
        )

    def test_admin_regenerates_pinyin_when_prompt_changes(self) -> None:
        response = self.client.post(
            reverse("admin:practice_practiceitem_change", args=(self.item.pk,)),
            {
                "deck": str(self.deck.pk),
                "prompt_text": "你喜欢咖啡。",
                "pinyin_text": "stale pinyin",
                "sort_order": "1",
            },
        )

        self.assertEqual(response.status_code, 302)
        self.item.refresh_from_db()
        self.assertEqual(self.item.pinyin_text, "ni3 xi3 huan1 ka1 fei1 。")

    def test_admin_keeps_manual_pinyin_when_pinyin_changes_too(self) -> None:
        response = self.client.post(
            reverse("admin:practice_practiceitem_change", args=(self.item.pk,)),
            {
                "deck": str(self.deck.pk),
                "prompt_text": "你喜欢咖啡。",
                "pinyin_text": "manual correction",
                "sort_order": "1",
            },
        )

        self.assertEqual(response.status_code, 302)
        self.item.refresh_from_db()
        self.assertEqual(self.item.pinyin_text, "manual correction")

    def test_admin_generates_pinyin_for_new_item_when_blank(self) -> None:
        response = self.client.post(
            reverse("admin:practice_practiceitem_add"),
            {
                "deck": str(self.deck.pk),
                "prompt_text": "你喜欢咖啡。",
                "pinyin_text": "",
                "sort_order": "2",
            },
        )

        self.assertEqual(response.status_code, 302)
        item = self.deck.items.get(sort_order=2)
        self.assertEqual(item.pinyin_text, "ni3 xi3 huan1 ka1 fei1 。")
