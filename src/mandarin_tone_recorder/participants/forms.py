"""Forms for the participant consent and routing workflow."""

from django import forms

from mandarin_tone_recorder.participants.models import ParticipantProfile


class ConsentForm(forms.Form):
    """Capture an explicit choice to participate."""

    consent = forms.BooleanField(
        label="I agree to participate in this experiment.",
        required=True,
    )


class MandarinKnowledgeForm(forms.Form):
    """Ask whether the participant knows any Mandarin Chinese."""

    knows_mandarin = forms.TypedChoiceField(
        choices=((True, "Yes"), (False, "No")),
        coerce=lambda value: value == "True",
        empty_value=None,
        label="Do you know any Mandarin Chinese?",
        widget=forms.RadioSelect,
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
