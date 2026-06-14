"""Model tests for stimuli, recording sessions, and recording attempts."""

from datetime import UTC, datetime, timedelta

from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.utils import timezone

from mandarin_tone_recorder.experiments.models import (
    BaseSyllable,
    Enrollment,
    Experiment,
    ExperimentStimulus,
    Stimulus,
)
from mandarin_tone_recorder.participants.models import Participant
from mandarin_tone_recorder.recordings.models import (
    RecordingAttempt,
    RecordingSession,
    recording_upload_to,
)


class RecordingModelTests(TestCase):
    @classmethod
    def setUpTestData(cls) -> None:
        cls.participant = Participant.objects.create()
        cls.experiment = Experiment.objects.get(slug="mandarin-tone-reading")
        cls.enrollment = Enrollment.objects.create(
            participant=cls.participant,
            experiment=cls.experiment,
            routing_reason="Test enrollment.",
        )
        cls.base_syllable = BaseSyllable.objects.create(
            ascii="ma",
            pinyin_base="ma",
            onset="m",
            nucleus="a",
            ipa_base="ma",
        )
        cls.stimulus = Stimulus.objects.create(
            stable_id="ma1",
            base_syllable=cls.base_syllable,
            condition=Stimulus.Condition.TONE_BEARING,
            target_tone=1,
            display_text="mā",
        )
        ExperimentStimulus.objects.create(
            experiment=cls.experiment,
            stimulus=cls.stimulus,
        )

    def create_session(self, **overrides: object) -> RecordingSession:
        values = {
            "enrollment": self.enrollment,
            "target_duration_seconds": 1200,
            "current_stimulus": self.stimulus,
            "current_stimulus_index": 1,
        }
        values.update(overrides)
        return RecordingSession.objects.create(**values)

    def test_tone_unspecified_stimulus_cannot_have_a_target_tone(self) -> None:
        stimulus = Stimulus(
            stable_id="ma-unspecified",
            base_syllable=self.base_syllable,
            condition=Stimulus.Condition.TONE_UNSPECIFIED,
            target_tone=2,
            display_text="ma",
        )

        with self.assertRaises(ValidationError):
            stimulus.validate_constraints()

    def test_session_current_stimulus_must_belong_to_experiment(self) -> None:
        other_stimulus = Stimulus.objects.create(
            stable_id="ma2",
            base_syllable=self.base_syllable,
            condition=Stimulus.Condition.TONE_BEARING,
            target_tone=2,
            display_text="má",
        )
        session = RecordingSession(
            enrollment=self.enrollment,
            target_duration_seconds=1200,
            current_stimulus=other_stimulus,
            current_stimulus_index=1,
        )

        with self.assertRaisesMessage(
            ValidationError,
            "Stimulus is not active in this experiment.",
        ):
            session.clean()

    def test_speaker_rejected_attempt_is_valid_without_audio(self) -> None:
        session = self.create_session()
        attempt = RecordingAttempt(
            session=session,
            stimulus=self.stimulus,
            stimulus_index=1,
            attempt_number=1,
            status=RecordingAttempt.Status.SPEAKER_REJECTED,
            duration_seconds=0.8,
        )

        attempt.full_clean()
        attempt.save()

        self.assertFalse(attempt.raw_audio)

    def test_accepted_attempt_requires_raw_audio(self) -> None:
        session = self.create_session()
        attempt = RecordingAttempt(
            session=session,
            stimulus=self.stimulus,
            stimulus_index=1,
            status=RecordingAttempt.Status.ACCEPTED,
            duration_seconds=1.2,
        )

        with self.assertRaisesMessage(
            ValidationError,
            "Accepted attempts require an audio file.",
        ):
            attempt.clean()

    def test_attempt_end_cannot_precede_start(self) -> None:
        session = self.create_session()
        now = timezone.now()
        attempt = RecordingAttempt(
            session=session,
            stimulus=self.stimulus,
            stimulus_index=1,
            status=RecordingAttempt.Status.TIMED_OUT,
            started_at=now,
            ended_at=now - timedelta(seconds=1),
        )

        with self.assertRaisesMessage(
            ValidationError,
            "Attempt cannot end before it starts.",
        ):
            attempt.clean()

    def test_audio_upload_path_is_readable_unique_and_timestamped(self) -> None:
        session = self.create_session()
        recorded_at = datetime(2026, 6, 14, 20, 45, 12, tzinfo=UTC)
        attempt = RecordingAttempt(
            session=session,
            stimulus=self.stimulus,
            stimulus_index=12,
            attempt_number=2,
            status=RecordingAttempt.Status.ACCEPTED,
            recorded_at=recorded_at,
            raw_audio=SimpleUploadedFile("browser.webm", b"audio"),
        )

        path = recording_upload_to(attempt, attempt.raw_audio.name)

        self.assertEqual(
            path,
            (
                f"recordings/{self.participant.public_id}/{session.public_id}/"
                f"0012_02_ma1_20260614T204512Z_{attempt.recording_id}.webm"
            ),
        )

    def test_tone_unspecified_upload_path_uses_plain_base_label(self) -> None:
        session = self.create_session()
        unspecified = Stimulus.objects.create(
            stable_id="ma_unspecified",
            base_syllable=self.base_syllable,
            condition=Stimulus.Condition.TONE_UNSPECIFIED,
            target_tone=None,
            display_text="ma",
        )
        ExperimentStimulus.objects.create(
            experiment=self.experiment,
            stimulus=unspecified,
        )
        recorded_at = datetime(2026, 6, 14, 20, 45, 12, tzinfo=UTC)
        attempt = RecordingAttempt(
            session=session,
            stimulus=unspecified,
            stimulus_index=12,
            attempt_number=2,
            status=RecordingAttempt.Status.ACCEPTED,
            recorded_at=recorded_at,
            raw_audio=SimpleUploadedFile("browser.webm", b"audio"),
        )

        path = recording_upload_to(attempt, attempt.raw_audio.name)

        self.assertEqual(
            path,
            (
                f"recordings/{self.participant.public_id}/{session.public_id}/"
                f"0012_02_ma_20260614T204512Z_{attempt.recording_id}.webm"
            ),
        )
        self.assertEqual(unspecified.stable_id, "ma_unspecified")
