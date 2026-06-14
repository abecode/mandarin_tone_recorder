"""Request-level tests for the participant recording workflow."""

import json
import shutil
import tempfile
from pathlib import Path

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from mandarin_tone_recorder.experiments.models import (
    BaseSyllable,
    Enrollment,
    Experiment,
    ExperimentStimulus,
    Stimulus,
)
from mandarin_tone_recorder.participants.models import Consent, Participant
from mandarin_tone_recorder.participants.services import PARTICIPANT_SESSION_KEY
from mandarin_tone_recorder.participants.views import CONSENT_VERSION
from mandarin_tone_recorder.recordings.models import (
    RecordingAttempt,
    RecordingSession,
)


class RecordingViewTests(TestCase):
    @classmethod
    def setUpTestData(cls) -> None:
        cls.experiment = Experiment.objects.get(slug="mandarin-tone-reading")
        cls.base = BaseSyllable.objects.create(
            ascii="ma",
            pinyin_base="ma",
            onset="m",
            nucleus="a",
            ipa_base="ma",
        )
        cls.stimuli = []
        for tone, display in ((1, "mā"), (2, "má")):
            stimulus = Stimulus.objects.create(
                stable_id=f"ma{tone}",
                base_syllable=cls.base,
                condition=Stimulus.Condition.TONE_BEARING,
                target_tone=tone,
                display_text=display,
            )
            ExperimentStimulus.objects.create(
                experiment=cls.experiment,
                stimulus=stimulus,
            )
            cls.stimuli.append(stimulus)

    def setUp(self) -> None:
        self.media_root = Path(tempfile.mkdtemp())
        self.override = override_settings(MEDIA_ROOT=self.media_root)
        self.override.enable()
        self.addCleanup(self.override.disable)
        self.addCleanup(shutil.rmtree, self.media_root, True)

        self.participant = Participant.objects.create()
        Consent.objects.create(
            participant=self.participant,
            version=CONSENT_VERSION,
        )
        self.enrollment = Enrollment.objects.create(
            participant=self.participant,
            experiment=self.experiment,
            routing_reason="View test.",
        )
        browser_session = self.client.session
        browser_session[PARTICIPANT_SESSION_KEY] = str(self.participant.public_id)
        browser_session.save()

    def start_session(self) -> RecordingSession:
        response = self.client.post(
            reverse("recordings:start", args=(self.enrollment.pk,))
        )
        session = RecordingSession.objects.get(enrollment=self.enrollment)
        self.assertRedirects(
            response,
            reverse("recordings:session", args=(session.public_id,)),
        )
        return session

    def test_start_and_session_page_render_current_stimulus(self) -> None:
        session = self.start_session()

        response = self.client.get(
            reverse("recordings:session", args=(session.public_id,))
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Start recording")
        self.assertEqual(
            response.context["recorder_config"]["stimulus"]["display_text"],
            session.current_stimulus.display_text,
        )
        self.assertContains(response, session.current_stimulus.stable_id)
        self.assertContains(response, "recorder-config")
        self.assertContains(response, "recorder.js?v=20260614-2")
        self.assertIn("csrftoken", response.cookies)

    def test_anonymous_recorder_posts_with_page_csrf_cookie(self) -> None:
        session = self.start_session()
        csrf_client = self.client_class(enforce_csrf_checks=True)
        browser_session = csrf_client.session
        browser_session[PARTICIPANT_SESSION_KEY] = str(self.participant.public_id)
        browser_session.save()
        page = csrf_client.get(
            reverse("recordings:session", args=(session.public_id,))
        )
        token = page.cookies["csrftoken"].value

        response = csrf_client.post(
            reverse("recordings:retry-attempt", args=(session.public_id,)),
            data=json.dumps(
                {
                    "stimulus_id": session.current_stimulus.stable_id,
                    "status": RecordingAttempt.Status.TIMED_OUT,
                    "duration_seconds": 7,
                }
            ),
            content_type="application/json",
            HTTP_X_CSRFTOKEN=token,
        )

        self.assertEqual(response.status_code, 200)

    def test_accepted_upload_advances_and_saves_audio(self) -> None:
        session = self.start_session()
        stimulus = session.current_stimulus
        now_ms = int(timezone.now().timestamp() * 1000)

        response = self.client.post(
            reverse("recordings:accepted-attempt", args=(session.public_id,)),
            {
                "audio": SimpleUploadedFile(
                    "prompt.webm",
                    b"audio bytes",
                    content_type="audio/webm",
                ),
                "stimulus_id": stimulus.stable_id,
                "duration_seconds": "1.25",
                "started_at_ms": str(now_ms - 1250),
                "ended_at_ms": str(now_ms),
                "mime_type": "audio/webm",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["ok"])
        attempt = RecordingAttempt.objects.get(session=session)
        self.assertEqual(attempt.status, RecordingAttempt.Status.ACCEPTED)
        self.assertTrue(attempt.raw_audio.name.endswith(".webm"))
        session.refresh_from_db()
        self.assertEqual(session.current_stimulus_index, 2)

    def test_retry_endpoint_keeps_the_same_stimulus(self) -> None:
        session = self.start_session()
        stimulus = session.current_stimulus

        response = self.client.post(
            reverse("recordings:retry-attempt", args=(session.public_id,)),
            data=json.dumps(
                {
                    "stimulus_id": stimulus.stable_id,
                    "status": RecordingAttempt.Status.SPEAKER_REJECTED,
                    "duration_seconds": 0.5,
                }
            ),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["next_stimulus"]["stable_id"], stimulus.stable_id)
        session.refresh_from_db()
        self.assertEqual(session.current_stimulus, stimulus)
        self.assertEqual(session.current_stimulus_index, 1)

    def test_non_tone_retry_returns_a_tone_unspecified_stimulus(self) -> None:
        non_tone_experiment = Experiment.objects.get(
            slug="mandarin-non-tone-reading"
        )
        unspecified = Stimulus.objects.create(
            stable_id="ma_unspecified",
            base_syllable=self.base,
            condition=Stimulus.Condition.TONE_UNSPECIFIED,
            target_tone=None,
            display_text="ma",
        )
        ExperimentStimulus.objects.create(
            experiment=non_tone_experiment,
            stimulus=unspecified,
        )
        non_tone_participant = Participant.objects.create()
        Consent.objects.create(
            participant=non_tone_participant,
            version=CONSENT_VERSION,
        )
        enrollment = Enrollment.objects.create(
            participant=non_tone_participant,
            experiment=non_tone_experiment,
            routing_reason="Non-tone retry test.",
        )
        browser_session = self.client.session
        browser_session[PARTICIPANT_SESSION_KEY] = str(
            non_tone_participant.public_id
        )
        browser_session.save()
        self.client.post(reverse("recordings:start", args=(enrollment.pk,)))
        session = RecordingSession.objects.get(enrollment=enrollment)

        response = self.client.post(
            reverse("recordings:retry-attempt", args=(session.public_id,)),
            data=json.dumps(
                {
                    "stimulus_id": unspecified.stable_id,
                    "status": RecordingAttempt.Status.SPEAKER_REJECTED,
                    "duration_seconds": 0.5,
                }
            ),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["next_stimulus"]["display_text"], "ma")
        self.assertIsNone(response.json()["next_stimulus"]["target_tone"])

    def test_session_endpoints_are_scoped_to_browser_participant(self) -> None:
        session = self.start_session()
        other_participant = Participant.objects.create()
        other_browser = self.client_class()
        other_session = other_browser.session
        other_session[PARTICIPANT_SESSION_KEY] = str(other_participant.public_id)
        other_session.save()

        response = other_browser.post(
            reverse("recordings:abort", args=(session.public_id,))
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse("participants:consent"))
        session.refresh_from_db()
        self.assertEqual(session.status, RecordingSession.Status.ACTIVE)

    def test_continue_finish_and_abort_actions(self) -> None:
        continue_session = self.start_session()
        continue_session.target_reached_at = timezone.now()
        continue_session.save(update_fields=("target_reached_at",))

        response = self.client.post(
            reverse("recordings:continue", args=(continue_session.public_id,))
        )
        self.assertEqual(response.status_code, 200)
        continue_session.refresh_from_db()
        self.assertTrue(continue_session.continued_after_target)

        response = self.client.post(
            reverse("recordings:finish", args=(continue_session.public_id,))
        )
        self.assertEqual(response.status_code, 200)
        continue_session.refresh_from_db()
        self.assertEqual(continue_session.status, RecordingSession.Status.FINISHED)

        abort_participant = Participant.objects.create()
        Consent.objects.create(
            participant=abort_participant,
            version=CONSENT_VERSION,
        )
        abort_enrollment = Enrollment.objects.create(
            participant=abort_participant,
            experiment=self.experiment,
            routing_reason="Abort test.",
        )
        browser_session = self.client.session
        browser_session[PARTICIPANT_SESSION_KEY] = str(abort_participant.public_id)
        browser_session.save()
        response = self.client.post(
            reverse("recordings:start", args=(abort_enrollment.pk,))
        )
        abort_session = RecordingSession.objects.get(enrollment=abort_enrollment)
        self.assertEqual(response.status_code, 302)

        response = self.client.post(
            reverse("recordings:abort", args=(abort_session.public_id,))
        )
        self.assertEqual(response.status_code, 200)
        abort_session.refresh_from_db()
        self.assertEqual(abort_session.status, RecordingSession.Status.ABORTED)
