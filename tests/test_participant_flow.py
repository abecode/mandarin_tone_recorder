"""Tests for anonymous consent and experiment routing."""

from django.test import TestCase
from django.urls import reverse

from mandarin_tone_recorder.experiments.models import Enrollment, Experiment
from mandarin_tone_recorder.participants.models import (
    Consent,
    Participant,
    ParticipantLanguage,
    ParticipantProfile,
)
from mandarin_tone_recorder.participants.services import PARTICIPANT_SESSION_KEY
from mandarin_tone_recorder.participants.views import CONSENT_VERSION


class ParticipantFlowTests(TestCase):
    def mandarin_knowledge_payload(
        self,
        *,
        knows_mandarin: str,
        native_languages: list[str] | None = None,
        other_language_name: str = "",
    ) -> dict[str, object]:
        return {
            "native_languages": native_languages or ["en-US"],
            "other_language_name": other_language_name,
            "knows_mandarin": knows_mandarin,
        }

    def consent(self) -> Participant:
        response = self.client.post(
            reverse("participants:consent"),
            {"consent": "on"},
        )

        self.assertRedirects(response, reverse("participants:mandarin-knowledge"))
        public_id = self.client.session[PARTICIPANT_SESSION_KEY]
        return Participant.objects.get(public_id=public_id)

    def test_consent_requires_affirmative_choice(self) -> None:
        response = self.client.post(reverse("participants:consent"), {})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "This field is required")
        self.assertFalse(Participant.objects.exists())
        self.assertFalse(Consent.objects.exists())

    def test_consent_creates_anonymous_participant_and_profile(self) -> None:
        participant = self.consent()

        self.assertIsNone(participant.user)
        self.assertTrue(
            Consent.objects.filter(
                participant=participant,
                version=CONSENT_VERSION,
            ).exists()
        )
        self.assertTrue(
            ParticipantProfile.objects.filter(participant=participant).exists()
        )

    def test_participant_without_mandarin_is_routed_to_non_tone_experiment(
        self,
    ) -> None:
        participant = self.consent()

        response = self.client.post(
            reverse("participants:mandarin-knowledge"),
            self.mandarin_knowledge_payload(knows_mandarin="False"),
            follow=True,
        )

        enrollment = Enrollment.objects.get(participant=participant)
        self.assertEqual(enrollment.experiment.track, Experiment.Track.NON_TONE)
        self.assertContains(response, "Mandarin non-tone reading experiment")
        participant.profile.refresh_from_db()
        self.assertIs(participant.profile.knows_mandarin, False)
        native_language = ParticipantLanguage.objects.get(
            profile=participant.profile,
            relationship=ParticipantLanguage.Relationship.NATIVE,
        )
        self.assertEqual(native_language.language_tag, "en-US")
        self.assertEqual(
            native_language.proficiency,
            ParticipantLanguage.Proficiency.NATIVE_LIKE,
        )

    def test_mandarin_speaker_completes_background_and_level_before_routing(
        self,
    ) -> None:
        participant = self.consent()

        response = self.client.post(
            reverse("participants:mandarin-knowledge"),
            self.mandarin_knowledge_payload(
                knows_mandarin="True",
                native_languages=["cmn-Hant-TW", "x-mmok1234"],
            ),
        )
        self.assertRedirects(
            response,
            reverse("participants:speaker-background"),
        )
        self.assertFalse(Enrollment.objects.filter(participant=participant).exists())
        self.assertEqual(
            list(
                participant.profile.languages.values_list(
                    "language_tag",
                    flat=True,
                )
            ),
            ["cmn-Hant-TW", "x-mmok1234"],
        )

        response = self.client.post(
            reverse("participants:speaker-background"),
            {"speaker_background": ParticipantProfile.SpeakerBackground.LEARNER},
        )
        self.assertRedirects(response, reverse("participants:mandarin-level"))

        response = self.client.post(
            reverse("participants:mandarin-level"),
            {"mandarin_level": ParticipantProfile.MandarinLevel.INTERMEDIATE},
            follow=True,
        )

        enrollment = Enrollment.objects.get(participant=participant)
        self.assertEqual(enrollment.experiment.track, Experiment.Track.TONE)
        self.assertContains(response, "Mandarin tone reading experiment")
        participant.profile.refresh_from_db()
        self.assertEqual(
            participant.profile.speaker_background,
            ParticipantProfile.SpeakerBackground.LEARNER,
        )
        self.assertEqual(
            participant.profile.mandarin_level,
            ParticipantProfile.MandarinLevel.INTERMEDIATE,
        )

    def test_later_steps_cannot_be_opened_without_consent_or_prerequisites(
        self,
    ) -> None:
        response = self.client.get(reverse("participants:speaker-background"))
        self.assertRedirects(response, reverse("participants:consent"))

        self.consent()
        response = self.client.get(reverse("participants:mandarin-level"))
        self.assertRedirects(response, reverse("participants:mandarin-knowledge"))

    def test_native_language_is_required_with_mandarin_knowledge(self) -> None:
        participant = self.consent()

        response = self.client.post(
            reverse("participants:mandarin-knowledge"),
            {"knows_mandarin": "False"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "This field is required")
        self.assertFalse(participant.profile.languages.exists())
        self.assertFalse(Enrollment.objects.filter(participant=participant).exists())

    def test_other_native_language_requires_text(self) -> None:
        participant = self.consent()

        response = self.client.post(
            reverse("participants:mandarin-knowledge"),
            self.mandarin_knowledge_payload(
                knows_mandarin="False",
                native_languages=["other"],
            ),
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response,
            "Please specify the other native or first language.",
        )
        self.assertFalse(participant.profile.languages.exists())

    def test_other_native_language_text_is_stored(self) -> None:
        participant = self.consent()

        self.client.post(
            reverse("participants:mandarin-knowledge"),
            self.mandarin_knowledge_payload(
                knows_mandarin="False",
                native_languages=["other"],
                other_language_name="Klingon",
            ),
        )

        native_language = participant.profile.languages.get()
        self.assertEqual(native_language.language_tag, "other")
        self.assertEqual(native_language.other_language_name, "Klingon")

    def test_changing_route_replaces_an_unstarted_enrollment(self) -> None:
        participant = self.consent()
        self.client.post(
            reverse("participants:mandarin-knowledge"),
            self.mandarin_knowledge_payload(knows_mandarin="False"),
        )

        self.client.post(
            reverse("participants:mandarin-knowledge"),
            self.mandarin_knowledge_payload(
                knows_mandarin="True",
                native_languages=["en-GB"],
            ),
        )
        self.client.post(
            reverse("participants:speaker-background"),
            {"speaker_background": ParticipantProfile.SpeakerBackground.NATIVE},
        )
        self.client.post(
            reverse("participants:mandarin-level"),
            {"mandarin_level": ParticipantProfile.MandarinLevel.ADVANCED},
        )

        enrollments = Enrollment.objects.filter(participant=participant)
        self.assertEqual(enrollments.count(), 1)
        self.assertEqual(enrollments.get().experiment.track, Experiment.Track.TONE)
