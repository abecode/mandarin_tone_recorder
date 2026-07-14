"""Forms for creating practice decks."""

from django import forms

from mandarin_tone_recorder.practice.services import (
    create_practice_deck,
    split_practice_lines,
)


class PracticeDeckForm(forms.Form):
    """Capture newline-delimited sentences for a new practice deck."""

    title = forms.CharField(max_length=200)
    source_text = forms.CharField(
        label="Sentences",
        error_messages={"required": "Enter at least one sentence."},
        help_text="Enter one sentence per line.",
        widget=forms.Textarea(attrs={"rows": 8}),
    )
    is_shared = forms.BooleanField(
        label="Share this deck with other users",
        required=False,
    )

    def clean_source_text(self) -> str:
        source_text = self.cleaned_data["source_text"]
        if not split_practice_lines(source_text):
            raise forms.ValidationError("Enter at least one sentence.")
        return source_text

    def save(self, *, user):
        """Create a deck and derived pinyin-bearing practice items."""
        return create_practice_deck(
            user=user,
            title=self.cleaned_data["title"],
            source_text=self.cleaned_data["source_text"],
            is_shared=self.cleaned_data["is_shared"],
        )
