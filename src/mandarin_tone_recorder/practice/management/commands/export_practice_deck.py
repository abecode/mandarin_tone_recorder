"""Export one practice deck to the repository YAML format."""

from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.utils.text import slugify

from mandarin_tone_recorder.practice.deck_files import (
    DEFAULT_PRACTICE_DECK_DIR,
    export_practice_deck,
)
from mandarin_tone_recorder.practice.models import PracticeDeck


class Command(BaseCommand):
    help = "Export one practice deck as YAML."

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "deck",
            help="PracticeDeck primary key or slug.",
        )
        parser.add_argument(
            "--deck-version",
            type=int,
            help="Deck version to use when selecting by slug.",
        )
        parser.add_argument(
            "--output",
            type=Path,
            help="Output YAML path. Defaults to content/practice_decks/<slug>.yaml.",
        )

    def handle(self, *args, **options) -> None:
        deck = self._get_deck(options["deck"], options.get("deck_version"))
        slug = deck.slug or slugify(deck.title).replace("-", "_")
        output = (
            options["output"]
            or settings.BASE_DIR / DEFAULT_PRACTICE_DECK_DIR / f"{slug}.yaml"
        )
        output = export_practice_deck(deck, output)
        self.stdout.write(self.style.SUCCESS(f"Exported {deck} to {output}."))

    def _get_deck(self, identifier: str, version: int | None) -> PracticeDeck:
        try:
            if identifier.isdigit():
                return PracticeDeck.objects.get(pk=int(identifier))

            decks = PracticeDeck.objects.filter(slug=identifier)
            if version is not None:
                decks = decks.filter(version=version)
            return decks.get()
        except PracticeDeck.DoesNotExist as exc:
            raise CommandError(f"Practice deck not found: {identifier}") from exc
        except PracticeDeck.MultipleObjectsReturned as exc:
            raise CommandError(
                f"Multiple versions found for {identifier}; pass --deck-version."
            ) from exc
