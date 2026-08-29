"""Tests for practice deck creation and event constraints."""

from django.db import IntegrityError
from django.test import TestCase

from mandarin_tone_recorder.accounts.models import User
from mandarin_tone_recorder.experiments.models import AssessmentCycle
from mandarin_tone_recorder.participants.models import (
    Participant,
    ParticipantLanguage,
    ParticipantProfile,
    ParticipantProfileSnapshot,
)
from mandarin_tone_recorder.practice.models import (
    PracticeAttempt,
    PracticeDeck,
    PracticeHintEvent,
    PracticeSession,
)
from mandarin_tone_recorder.practice.services import (
    create_practice_deck,
    create_practice_session,
    generate_character_pinyin,
    generate_pinyin_text,
    prompt_character_hints,
    record_character_pinyin_hint,
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

    def test_generate_character_pinyin_uses_numbered_tones(self) -> None:
        self.assertEqual(generate_character_pinyin("喝"), "he1")

    def test_prompt_character_hints_marks_revealed_chinese_characters(self) -> None:
        self.assertEqual(
            prompt_character_hints(prompt_text="我。", revealed_indexes={0}),
            [
                {
                    "character": "我",
                    "index": 0,
                    "is_hintable": True,
                    "pinyin": "wo3",
                    "is_revealed": True,
                },
                {
                    "character": "。",
                    "index": 1,
                    "is_hintable": False,
                    "pinyin": "",
                    "is_revealed": False,
                },
            ],
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

    def test_create_practice_session_without_participant_has_no_snapshot(self) -> None:
        deck = create_practice_deck(
            user=self.user,
            title="Starter",
            source_text="你好。",
        )

        session = create_practice_session(user=self.user, deck=deck)

        self.assertIsNone(session.profile_snapshot)

    def test_create_practice_session_snapshots_linked_participant_profile(self) -> None:
        participant = Participant.objects.create(user=self.user)
        profile = ParticipantProfile.objects.create(
            participant=participant,
            knows_mandarin=True,
            speaker_background=ParticipantProfile.SpeakerBackground.LEARNER,
            mandarin_level=ParticipantProfile.MandarinLevel.BEGINNER,
        )
        ParticipantLanguage.objects.create(
            profile=profile,
            language_tag="en-US",
            relationship=ParticipantLanguage.Relationship.NATIVE,
            proficiency=ParticipantLanguage.Proficiency.NATIVE_LIKE,
        )
        deck = create_practice_deck(
            user=self.user,
            title="Starter",
            source_text="你好。",
        )

        session = create_practice_session(user=self.user, deck=deck)

        self.assertIsNotNone(session.profile_snapshot)
        self.assertIsNotNone(session.assessment_cycle)
        self.assertEqual(session.assessment_cycle.status, AssessmentCycle.Status.ACTIVE)
        self.assertEqual(
            session.assessment_cycle.profile_snapshot.source,
            ParticipantProfileSnapshot.Source.ASSESSMENT_CYCLE_START,
        )
        self.assertEqual(
            session.profile_snapshot.source,
            ParticipantProfileSnapshot.Source.PRACTICE_START,
        )
        self.assertIs(session.profile_snapshot.knows_mandarin, True)
        self.assertEqual(
            session.profile_snapshot.languages[0]["language_tag"],
            "en-US",
        )

    def test_create_practice_session_reuses_existing_active_cycle(self) -> None:
        participant = Participant.objects.create(user=self.user)
        profile = ParticipantProfile.objects.create(
            participant=participant,
            knows_mandarin=False,
        )
        first_snapshot = ParticipantProfileSnapshot.objects.create(
            participant=participant,
            source=ParticipantProfileSnapshot.Source.ASSESSMENT_CYCLE_START,
            knows_mandarin=False,
        )
        cycle = AssessmentCycle.objects.create(
            participant=participant,
            profile_snapshot=first_snapshot,
            label="Existing cycle",
        )
        deck = create_practice_deck(
            user=self.user,
            title="Starter",
            source_text="你好。",
        )

        session = create_practice_session(user=self.user, deck=deck)

        self.assertEqual(session.assessment_cycle, cycle)
        self.assertNotEqual(session.profile_snapshot, first_snapshot)
        self.assertEqual(participant.profile_snapshots.count(), 2)


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

    def test_record_character_pinyin_hint_is_unique_per_character_index(self) -> None:
        first_hint = record_character_pinyin_hint(
            attempt=self.attempt,
            character_index=0,
            revealed_at_ms=500,
        )
        second_hint = record_character_pinyin_hint(
            attempt=self.attempt,
            character_index=0,
            revealed_at_ms=900,
        )

        self.assertEqual(first_hint, second_hint)
        self.assertEqual(self.attempt.hint_events.count(), 1)
        self.assertEqual(first_hint.character, "我")
        self.assertEqual(first_hint.revealed_at_ms, 500)

    def test_record_character_pinyin_hint_rejects_non_chinese_character(self) -> None:
        with self.assertRaisesRegex(ValueError, "Chinese character"):
            record_character_pinyin_hint(
                attempt=self.attempt,
                character_index=5,
                revealed_at_ms=500,
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

    def test_create_practice_session_requires_visible_deck(self) -> None:
        other_user = User.objects.create_user(
            username="other-reader",
            email="other@example.com",
            password="correct-horse-battery-staple",
        )
        private_other_deck = PracticeDeck.objects.create(
            user=other_user,
            title="Private deck",
            source_text="再见。",
        )

        with self.assertRaisesRegex(ValueError, "not visible"):
            create_practice_session(user=self.user, deck=private_other_deck)

    def test_create_practice_session_starts_session_for_visible_deck(self) -> None:
        session = create_practice_session(user=self.user, deck=self.deck)

        self.assertEqual(session.user, self.user)
        self.assertEqual(session.deck, self.deck)
        self.assertEqual(session.attempts.count(), 1)
        self.assertEqual(session.attempts.get().item, self.deck.items.get())
