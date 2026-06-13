"""Tests for anonymous consent and experiment routing."""

from django.test import TestCase
from django.urls import reverse

from mandarin_tone_recorder.experiments.models import Enrollment, Experiment
from mandarin_tone_recorder.participants.models import (
    Consent,
    Participant,
    ParticipantProfile,
)
from mandarin_tone_recorder.participants.services import PARTICIPANT_SESSION_KEY
from mandarin_tone_recorder.participants.views import CONSENT_VERSION


class ParticipantFlowTests(TestCase):
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
            {"knows_mandarin": "False"},
            follow=True,
        )

        enrollment = Enrollment.objects.get(participant=participant)
        self.assertEqual(enrollment.experiment.track, Experiment.Track.NON_TONE)
        self.assertContains(response, "Mandarin non-tone reading experiment")
        participant.profile.refresh_from_db()
        self.assertIs(participant.profile.knows_mandarin, False)

    def test_mandarin_speaker_completes_background_and_level_before_routing(
        self,
    ) -> None:
        participant = self.consent()

        response = self.client.post(
            reverse("participants:mandarin-knowledge"),
            {"knows_mandarin": "True"},
        )
        self.assertRedirects(
            response,
            reverse("participants:speaker-background"),
        )
        self.assertFalse(Enrollment.objects.filter(participant=participant).exists())

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

    def test_changing_route_replaces_an_unstarted_enrollment(self) -> None:
        participant = self.consent()
        self.client.post(
            reverse("participants:mandarin-knowledge"),
            {"knows_mandarin": "False"},
        )

        self.client.post(
            reverse("participants:mandarin-knowledge"),
            {"knows_mandarin": "True"},
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
