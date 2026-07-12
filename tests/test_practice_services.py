"""Tests for practice deck creation and event constraints."""

from django.db import IntegrityError
from django.test import TestCase

from mandarin_tone_recorder.accounts.models import User
from mandarin_tone_recorder.practice.models import (
    PracticeAttempt,
    PracticeDeck,
    PracticeHintEvent,
    PracticeSession,
)
from mandarin_tone_recorder.practice.services import (
    create_practice_deck,
    generate_pinyin_text,
    split_practice_lines,
    visible_practice_decks,
)


class PracticeServiceTests(TestCase):
    def setUp(self) -> None:
        self.user = User.objects.create_user(
            username="reader",
            email="reader@example.com",
            password="correct-horse-battery-staple",
        )

    def test_split_practice_lines_uses_non_empty_newlines(self) -> None:
        self.assertEqual(
            split_practice_lines("我喜欢喝茶。\n\n  你喜欢咖啡。  \n"),
            ["我喜欢喝茶。", "你喜欢咖啡。"],
        )

    def test_generate_pinyin_text_uses_numbered_tones(self) -> None:
        self.assertEqual(
            generate_pinyin_text("我喜欢喝茶。"),
            "wo3 xi3 huan1 he1 cha2 。",
        )

    def test_create_practice_deck_creates_ordered_items_with_pinyin(self) -> None:
        deck = create_practice_deck(
            user=self.user,
            title="Tea and coffee",
            source_text="我喜欢喝茶。\n你喜欢咖啡。",
            is_shared=True,
        )

        self.assertEqual(deck.user, self.user)
        self.assertTrue(deck.is_shared)
        self.assertEqual(deck.items.count(), 2)
        self.assertEqual(
            list(deck.items.values_list("sort_order", "prompt_text")),
            [(1, "我喜欢喝茶。"), (2, "你喜欢咖啡。")],
        )
        self.assertEqual(deck.items.first().pinyin_text, "wo3 xi3 huan1 he1 cha2 。")

    def test_create_practice_deck_requires_at_least_one_prompt(self) -> None:
        with self.assertRaisesRegex(ValueError, "at least one prompt"):
            create_practice_deck(
                user=self.user,
                title="Empty",
                source_text="\n  \n",
            )

    def test_deck_user_can_be_null_for_shared_or_system_decks(self) -> None:
        deck = create_practice_deck(
            user=None,
            title="Shared starter deck",
            source_text="你好。",
        )

        self.assertIsNone(deck.user)


class PracticeHintEventTests(TestCase):
    def setUp(self) -> None:
        self.user = User.objects.create_user(
            username="reader",
            email="reader@example.com",
            password="correct-horse-battery-staple",
        )
        self.deck = create_practice_deck(
            user=self.user,
            title="Starter",
            source_text="我喜欢喝茶。",
        )
        self.session = PracticeSession.objects.create(deck=self.deck, user=self.user)
        self.attempt = PracticeAttempt.objects.create(
            session=self.session,
            item=self.deck.items.get(),
        )

    def test_sentence_pinyin_hint_is_unique_per_attempt(self) -> None:
        PracticeHintEvent.objects.create(
            attempt=self.attempt,
            hint_type=PracticeHintEvent.HintType.SENTENCE_PINYIN,
            revealed_at_ms=1200,
        )

        with self.assertRaises(IntegrityError):
            PracticeHintEvent.objects.create(
                attempt=self.attempt,
                hint_type=PracticeHintEvent.HintType.SENTENCE_PINYIN,
                revealed_at_ms=1800,
            )

    def test_character_pinyin_hint_is_unique_per_character_index(self) -> None:
        PracticeHintEvent.objects.create(
            attempt=self.attempt,
            hint_type=PracticeHintEvent.HintType.CHARACTER_PINYIN,
            character="我",
            character_index=0,
            revealed_at_ms=500,
        )

        with self.assertRaises(IntegrityError):
            PracticeHintEvent.objects.create(
                attempt=self.attempt,
                hint_type=PracticeHintEvent.HintType.CHARACTER_PINYIN,
                character="我",
                character_index=0,
                revealed_at_ms=900,
            )

    def test_multiple_attempts_are_allowed_for_one_item_in_a_session(self) -> None:
        second_attempt = PracticeAttempt.objects.create(
            session=self.session,
            item=self.deck.items.get(),
            response_time_ms=2500,
            server_elapsed_ms=2600,
        )

        self.assertNotEqual(self.attempt, second_attempt)
        self.assertEqual(self.session.attempts.count(), 2)

    def test_visible_decks_include_null_user_shared_and_owned_decks(self) -> None:
        other_user = User.objects.create_user(
            username="other-reader",
            email="other@example.com",
            password="correct-horse-battery-staple",
        )
        null_user_deck = PracticeDeck.objects.create(
            user=None,
            title="System deck",
            source_text="你好。",
        )
        shared_deck = PracticeDeck.objects.create(
            user=other_user,
            title="Shared deck",
            source_text="谢谢。",
            is_shared=True,
        )
        private_other_deck = PracticeDeck.objects.create(
            user=other_user,
            title="Private deck",
            source_text="再见。",
        )

        visible = visible_practice_decks(self.user)

        self.assertIn(null_user_deck, visible)
        self.assertIn(shared_deck, visible)
        self.assertIn(self.deck, visible)
        self.assertNotIn(private_other_deck, visible)
