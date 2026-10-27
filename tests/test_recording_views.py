"""Request-level tests for the participant recording workflow."""

import json
import shutil
import tempfile
from pathlib import Path

from django.contrib.auth.models import Permission
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from mandarin_tone_recorder.accounts.models import User
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

    def create_audio_attempt(self, *, with_wav: bool = False) -> RecordingAttempt:
        session = self.start_session()
        return RecordingAttempt.objects.create(
            session=session,
            stimulus=session.current_stimulus,
            stimulus_index=1,
            status=RecordingAttempt.Status.ACCEPTED,
            raw_audio=SimpleUploadedFile("prompt.webm", b"raw audio"),
            wav_audio=(
                SimpleUploadedFile("prompt.wav", b"wav audio") if with_wav else ""
            ),
        )

    def test_audio_download_requires_staff_with_view_permission(self) -> None:
        attempt = self.create_audio_attempt(with_wav=True)
        raw_url = reverse("recordings:download-audio", args=(attempt.recording_id, "raw"))
        wav_url = reverse("recordings:download-audio", args=(attempt.recording_id, "wav"))

        response = self.client.get(raw_url)
        self.assertRedirects(
            response,
            f"{reverse('accounts:login')}?next={raw_url}",
            fetch_redirect_response=False,
        )

        user = User.objects.create_user(
            username="reader", email="reader@example.com", password="password"
        )
        self.client.force_login(user)
        self.assertEqual(self.client.get(raw_url).status_code, 403)

        user.is_staff = True
        user.save(update_fields=("is_staff",))
        self.assertEqual(self.client.get(raw_url).status_code, 403)

        user.user_permissions.add(
            Permission.objects.get(
                content_type__app_label="recordings",
                codename="view_recordingattempt",
            )
        )
        self.client.force_login(user)
        for url, expected in ((raw_url, b"raw audio"), (wav_url, b"wav audio")):
            response = self.client.get(url)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(b"".join(response.streaming_content), expected)
            self.assertIn("attachment", response["Content-Disposition"])
            response.close()

    def test_audio_download_hides_missing_attempt_format_and_file(self) -> None:
        attempt = self.create_audio_attempt()
        staff = User.objects.create_superuser(
            username="admin", email="admin@example.com", password="password"
        )
        self.client.force_login(staff)

        for kind in ("wav", "other"):
            url = reverse("recordings:download-audio", args=(attempt.recording_id, kind))
            self.assertEqual(self.client.get(url).status_code, 404)

        attempt.raw_audio.delete(save=False)
        raw_url = reverse("recordings:download-audio", args=(attempt.recording_id, "raw"))
        self.assertEqual(self.client.get(raw_url).status_code, 404)

    def test_admin_audio_links_use_protected_endpoint(self) -> None:
        attempt = self.create_audio_attempt(with_wav=True)
        staff = User.objects.create_superuser(
            username="admin", email="admin@example.com", password="password"
        )
        self.client.force_login(staff)

        response = self.client.get(
            reverse("admin:recordings_recordingattempt_change", args=(attempt.pk,))
        )

        self.assertEqual(response.status_code, 200)
        for kind in ("raw", "wav"):
            self.assertContains(
                response,
                reverse("recordings:download-audio", args=(attempt.recording_id, kind)),
            )
        self.assertNotContains(response, "/media/recordings/")

    def test_media_url_is_not_publicly_routed(self) -> None:
        attempt = self.create_audio_attempt()
        self.assertEqual(
            self.client.get(f"/media/{attempt.raw_audio.name}").status_code,
            404,
        )

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
        self.assertContains(response, "Session target")
        self.assertContains(response, "Base syllables")
        self.assertContains(response, "Syllable-tone items")
        self.assertEqual(
            response.context["recorder_config"]["target_duration_seconds"],
            session.target_duration_seconds,
        )
        self.assertEqual(
            response.context["recorder_config"]["started_at"],
            session.started_at.isoformat(),
        )
        self.assertEqual(
            response.context["recorder_config"]["progress"],
            {
                "base_covered": 0,
                "base_total": 1,
                "tone_covered": 0,
                "tone_total": 2,
                "show_tone_progress": True,
            },
        )
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
        self.assertEqual(
            response.json()["progress"],
            {
                "base_covered": 1,
                "base_total": 1,
                "tone_covered": 1,
                "tone_total": 2,
                "show_tone_progress": True,
            },
        )
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

        response = self.client.post(
            reverse("recordings:start", args=(abort_enrollment.pk,))
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(
            abort_enrollment.recording_sessions.filter(
                status=RecordingSession.Status.ACTIVE
            ).count(),
            1,
        )
        self.assertEqual(abort_enrollment.recording_sessions.count(), 2)
