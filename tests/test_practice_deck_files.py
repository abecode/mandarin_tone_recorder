"""Tests for repo-backed practice deck YAML files."""

from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase
import yaml

from mandarin_tone_recorder.accounts.models import User
from mandarin_tone_recorder.practice.deck_files import (
    PracticeDeckFileError,
    export_practice_deck,
    import_practice_deck_file,
    parse_practice_deck_yaml,
)
from mandarin_tone_recorder.practice.models import PracticeDeck, PracticeSession


VALID_DECK_YAML = """
slug: django_basics
version: 1
title: Django Basics
activity_type: reading_speaking
response:
  type: audio
items:
  - prompts:
      hanzi: "模型"
    hints:
      pinyin: "mo2 xing2"
      english: "model"
  - prompts:
      hanzi: "视图"
    hints:
      english: "view"
"""


class PracticeDeckYamlTests(TestCase):
    def test_parse_practice_deck_yaml_validates_and_generates_missing_pinyin(self) -> None:
        parsed = parse_practice_deck_yaml(VALID_DECK_YAML)

        self.assertEqual(parsed.slug, "django_basics")
        self.assertEqual(parsed.version, 1)
        self.assertEqual(parsed.response_type, "audio")
        self.assertEqual(parsed.items[0].hint_pinyin, "mo2 xing2")
        self.assertEqual(parsed.items[1].hint_pinyin, "shi4 tu2")

    def test_parse_practice_deck_yaml_rejects_non_snake_case_slug(self) -> None:
        with self.assertRaisesRegex(PracticeDeckFileError, "lowercase"):
            parse_practice_deck_yaml(
                VALID_DECK_YAML.replace("django_basics", "django-basics")
            )

    def test_import_practice_deck_file_creates_builtin_shared_deck(self) -> None:
        with TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "django_basics.yaml"
            path.write_text(VALID_DECK_YAML, encoding="utf-8")

            result = import_practice_deck_file(path, base_dir=tmpdir)

        deck = result.deck
        self.assertTrue(result.created)
        self.assertEqual(deck.slug, "django_basics")
        self.assertEqual(deck.version, 1)
        self.assertIsNone(deck.user)
        self.assertTrue(deck.is_shared)
        self.assertTrue(deck.is_builtin)
        self.assertEqual(deck.source_path, "django_basics.yaml")
        self.assertEqual(
            list(deck.items.values_list("sort_order", "prompt_text", "pinyin_text")),
            [(1, "模型", "mo2 xing2"), (2, "视图", "shi4 tu2")],
        )

    def test_import_practice_deck_file_replaces_items_when_no_sessions_exist(self) -> None:
        with TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "django_basics.yaml"
            path.write_text(VALID_DECK_YAML, encoding="utf-8")
            import_practice_deck_file(path, base_dir=tmpdir)

            path.write_text(
                VALID_DECK_YAML.replace("视图", "模板").replace("view", "template"),
                encoding="utf-8",
            )
            result = import_practice_deck_file(path, base_dir=tmpdir)

        self.assertFalse(result.created)
        self.assertEqual(
            list(result.deck.items.values_list("prompt_text", flat=True)),
            ["模型", "模板"],
        )

    def test_import_practice_deck_file_requires_new_version_after_sessions(self) -> None:
        user = User.objects.create_user(username="reader", password="password")
        with TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "django_basics.yaml"
            path.write_text(VALID_DECK_YAML, encoding="utf-8")
            deck = import_practice_deck_file(path, base_dir=tmpdir).deck
            PracticeSession.objects.create(deck=deck, user=user)

            path.write_text(
                VALID_DECK_YAML.replace("视图", "模板").replace("view", "template"),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(PracticeDeckFileError, "change the YAML version"):
                import_practice_deck_file(path, base_dir=tmpdir)

    def test_export_practice_deck_writes_current_prompt_and_pinyin(self) -> None:
        deck = PracticeDeck.objects.create(
            slug="django_basics",
            version=1,
            title="Django Basics",
            source_text="模型",
        )
        deck.items.create(prompt_text="模型", pinyin_text="mo2 xing2", sort_order=1)

        with TemporaryDirectory() as tmpdir:
            output = export_practice_deck(deck, Path(tmpdir) / "deck.yaml")
            data = yaml.safe_load(output.read_text(encoding="utf-8"))

        self.assertEqual(data["slug"], "django_basics")
        self.assertEqual(data["response"]["type"], "audio")
        self.assertEqual(data["items"][0]["prompts"]["hanzi"], "模型")
        self.assertEqual(data["items"][0]["hints"]["pinyin"], "mo2 xing2")


class PracticeDeckCommandTests(TestCase):
    def test_import_practice_decks_command_imports_directory(self) -> None:
        with TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "django_basics.yaml"
            path.write_text(VALID_DECK_YAML, encoding="utf-8")
            stdout = StringIO()

            call_command("import_practice_decks", directory=Path(tmpdir), stdout=stdout)

        self.assertTrue(PracticeDeck.objects.filter(slug="django_basics").exists())
        self.assertIn("Imported 1 practice deck(s).", stdout.getvalue())

    def test_export_practice_deck_command_requires_version_when_slug_is_ambiguous(self) -> None:
        PracticeDeck.objects.create(
            slug="django_basics",
            version=1,
            title="Django Basics v1",
            source_text="模型",
        )
        PracticeDeck.objects.create(
            slug="django_basics",
            version=2,
            title="Django Basics v2",
            source_text="视图",
        )

        with self.assertRaisesRegex(CommandError, "Multiple versions"):
            call_command("export_practice_deck", "django_basics", stdout=StringIO())
