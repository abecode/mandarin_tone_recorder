"""Forms for the participant consent and routing workflow."""

from django import forms

from mandarin_tone_recorder.participants.models import (
    NATIVE_LANGUAGE_CHOICES,
    ParticipantLanguage,
    ParticipantProfile,
)


class ConsentForm(forms.Form):
    """Capture an explicit choice to participate."""

    consent = forms.BooleanField(
        label="I agree to participate in this experiment.",
        required=True,
    )


class MandarinKnowledgeForm(forms.Form):
    """Capture native languages and whether the participant knows Mandarin."""

    native_languages = forms.MultipleChoiceField(
        choices=NATIVE_LANGUAGE_CHOICES,
        label="Native or first language(s)",
        widget=forms.CheckboxSelectMultiple,
    )
    other_language_name = forms.CharField(
        label="If other, please specify",
        max_length=120,
        required=False,
        strip=True,
    )

    knows_mandarin = forms.TypedChoiceField(
        choices=((True, "Yes"), (False, "No")),
        coerce=lambda value: value == "True",
        empty_value=None,
        label="Do you know any Mandarin Chinese?",
        widget=forms.RadioSelect,
    )

    def clean(self) -> dict[str, object]:
        cleaned_data = super().clean()
        native_languages = cleaned_data.get("native_languages", [])
        other_language_name = cleaned_data.get("other_language_name", "")
        if "other" in native_languages and not other_language_name:
            self.add_error(
                "other_language_name",
                "Please specify the other native or first language.",
            )
        return cleaned_data

    def save_native_languages(self, profile: ParticipantProfile) -> None:
        """Replace this profile's native language inventory from form data."""
        native_languages = self.cleaned_data["native_languages"]
        other_language_name = self.cleaned_data.get("other_language_name", "")
        profile.languages.filter(
            relationship=ParticipantLanguage.Relationship.NATIVE
        ).delete()
        for sort_order, language_tag in enumerate(native_languages):
            ParticipantLanguage.objects.create(
                profile=profile,
                language_tag=language_tag,
                relationship=ParticipantLanguage.Relationship.NATIVE,
                proficiency=ParticipantLanguage.Proficiency.NATIVE_LIKE,
                other_language_name=(
                    other_language_name if language_tag == "other" else ""
                ),
                sort_order=sort_order,
            )


class SpeakerBackgroundForm(forms.Form):
    """Capture the participant's relationship to Mandarin."""

    speaker_background = forms.ChoiceField(
        choices=ParticipantProfile.SpeakerBackground,
        label="Which description best matches your Mandarin background?",
        widget=forms.RadioSelect,
    )


class MandarinLevelForm(forms.Form):
    """Capture a broad self-assessment of Mandarin proficiency."""

    mandarin_level = forms.ChoiceField(
        choices=ParticipantProfile.MandarinLevel,
        label="How would you describe your overall Mandarin level?",
        widget=forms.RadioSelect,
    )
