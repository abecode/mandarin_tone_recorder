"""Tests for stimulus assignment and recording-session lifecycle services."""

import shutil
import tempfile
from datetime import timedelta
from pathlib import Path

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
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
)
from mandarin_tone_recorder.recordings.services import (
    RecordingWorkflowError,
    StimulusMismatch,
    TargetContinuationRequired,
    abort_recording_session,
    choose_next_stimulus,
    continue_after_target,
    finish_recording_session,
    record_accepted_attempt,
    record_retry_attempt,
    start_recording_session,
)


class RecordingServiceTests(TestCase):
    @classmethod
    def setUpTestData(cls) -> None:
        cls.experiment = Experiment.objects.get(slug="mandarin-tone-reading")
        cls.experiment.target_duration_minutes = 1
        cls.experiment.save(update_fields=("target_duration_minutes",))
        cls.base = BaseSyllable.objects.create(
            ascii="ma",
            pinyin_base="ma",
            onset="m",
            nucleus="a",
            ipa_base="ma",
        )
        cls.stimuli = []
        for tone, display in ((1, "mā"), (2, "má"), (3, "mǎ")):
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
        self.enrollment = Enrollment.objects.create(
            participant=self.participant,
            experiment=self.experiment,
            routing_reason="Test enrollment.",
        )

    @staticmethod
    def first(stimuli: list[Stimulus]) -> Stimulus:
        return stimuli[0]

    def audio(self) -> SimpleUploadedFile:
        return SimpleUploadedFile(
            "browser.webm",
            b"recording bytes",
            content_type="audio/webm",
        )

    def test_start_snapshots_duration_assigns_first_item_and_updates_enrollment(
        self,
    ) -> None:
        started_at = timezone.now()

        session = start_recording_session(
            self.enrollment,
            now=started_at,
            chooser=self.first,
        )

        self.assertEqual(session.target_duration_seconds, 60)
        self.assertEqual(session.started_at, started_at)
        self.assertEqual(session.current_stimulus, self.stimuli[0])
        self.assertEqual(session.current_stimulus_index, 1)
        self.enrollment.refresh_from_db()
        self.assertEqual(self.enrollment.status, Enrollment.Status.IN_PROGRESS)

    def test_retry_records_attempt_and_keeps_current_stimulus(self) -> None:
        session = start_recording_session(self.enrollment, chooser=self.first)

        timeout = record_retry_attempt(
            session,
            self.stimuli[0],
            status=RecordingAttempt.Status.TIMED_OUT,
            duration_seconds=10,
        )
        redo = record_retry_attempt(
            session,
            self.stimuli[0],
            status=RecordingAttempt.Status.SPEAKER_REJECTED,
            duration_seconds=0.5,
        )

        self.assertEqual(timeout.next_stimulus, self.stimuli[0])
        self.assertEqual(redo.next_stimulus, self.stimuli[0])
        self.assertEqual(timeout.attempt.attempt_number, 1)
        self.assertEqual(redo.attempt.attempt_number, 2)
        session.refresh_from_db()
        self.assertEqual(session.current_stimulus, self.stimuli[0])
        self.assertEqual(session.current_stimulus_index, 1)

    def test_accepted_attempt_advances_and_never_selects_it_again(self) -> None:
        session = start_recording_session(self.enrollment, chooser=self.first)

        result = record_accepted_attempt(
            session,
            self.stimuli[0],
            raw_audio=self.audio(),
            duration_seconds=1.2,
            mime_type="audio/webm",
            chooser=self.first,
        )

        self.assertEqual(result.attempt.status, RecordingAttempt.Status.ACCEPTED)
        self.assertNotEqual(result.next_stimulus, self.stimuli[0])
        session.refresh_from_db()
        self.assertEqual(session.current_stimulus_index, 2)
        self.assertNotEqual(session.current_stimulus, self.stimuli[0])

    def test_assignment_prefers_stimulus_with_fewer_global_acceptances(self) -> None:
        other_participant = Participant.objects.create()
        other_enrollment = Enrollment.objects.create(
            participant=other_participant,
            experiment=self.experiment,
            routing_reason="Existing recording.",
            status=Enrollment.Status.IN_PROGRESS,
        )
        other_session = RecordingSession.objects.create(
            enrollment=other_enrollment,
            target_duration_seconds=60,
            current_stimulus=self.stimuli[0],
            current_stimulus_index=1,
        )
        RecordingAttempt.objects.create(
            session=other_session,
            stimulus=self.stimuli[0],
            stimulus_index=1,
            status=RecordingAttempt.Status.ACCEPTED,
            raw_audio="existing.webm",
        )
        session = RecordingSession.objects.create(
            enrollment=self.enrollment,
            target_duration_seconds=60,
        )

        selected = choose_next_stimulus(session, chooser=self.first)

        self.assertIn(selected, self.stimuli[1:])

    def test_target_is_reported_once_and_continue_acknowledges_it(self) -> None:
        started_at = timezone.now() - timedelta(seconds=61)
        session = start_recording_session(
            self.enrollment,
            now=started_at,
            chooser=self.first,
        )

        first_result = record_accepted_attempt(
            session,
            self.stimuli[0],
            raw_audio=self.audio(),
            duration_seconds=1,
            mime_type="audio/webm",
            now=timezone.now(),
            chooser=self.first,
        )
        self.assertTrue(first_result.target_reached_now)

        with self.assertRaises(TargetContinuationRequired):
            record_accepted_attempt(
                session,
                first_result.next_stimulus,
                raw_audio=self.audio(),
                duration_seconds=1,
                mime_type="audio/webm",
                now=timezone.now(),
                chooser=self.first,
            )

        continued = continue_after_target(session)
        self.assertTrue(continued.continued_after_target)

        second_result = record_accepted_attempt(
            continued,
            first_result.next_stimulus,
            raw_audio=self.audio(),
            duration_seconds=1,
            mime_type="audio/webm",
            now=timezone.now(),
            chooser=self.first,
        )
        self.assertFalse(second_result.target_reached_now)

    def test_accepting_final_stimulus_finishes_session_and_enrollment(self) -> None:
        session = start_recording_session(self.enrollment, chooser=self.first)
        current = session.current_stimulus

        for _ in range(len(self.stimuli)):
            result = record_accepted_attempt(
                session,
                current,
                raw_audio=self.audio(),
                duration_seconds=1,
                mime_type="audio/webm",
                chooser=self.first,
            )
            current = result.next_stimulus

        self.assertTrue(result.session_done)
        session.refresh_from_db()
        self.enrollment.refresh_from_db()
        self.assertEqual(session.status, RecordingSession.Status.FINISHED)
        self.assertIsNone(session.current_stimulus)
        self.assertEqual(self.enrollment.status, Enrollment.Status.COMPLETED)

    def test_finish_and_abort_update_session_and_enrollment(self) -> None:
        finish_session = start_recording_session(self.enrollment, chooser=self.first)
        finish_recording_session(finish_session)
        finish_session.refresh_from_db()
        self.enrollment.refresh_from_db()
        self.assertEqual(finish_session.status, RecordingSession.Status.FINISHED)
        self.assertEqual(self.enrollment.status, Enrollment.Status.COMPLETED)

        abort_participant = Participant.objects.create()
        abort_enrollment = Enrollment.objects.create(
            participant=abort_participant,
            experiment=self.experiment,
            routing_reason="Abort test.",
        )
        abort_session = start_recording_session(
            abort_enrollment,
            chooser=self.first,
        )
        abort_recording_session(abort_session)
        abort_session.refresh_from_db()
        abort_enrollment.refresh_from_db()
        self.assertEqual(abort_session.status, RecordingSession.Status.ABORTED)
        self.assertEqual(abort_enrollment.status, Enrollment.Status.ABORTED)

    def test_aborted_enrollment_can_start_a_new_session(self) -> None:
        first_session = start_recording_session(
            self.enrollment,
            chooser=self.first,
        )
        abort_recording_session(first_session)

        second_session = start_recording_session(
            self.enrollment,
            chooser=self.first,
        )

        self.assertNotEqual(second_session.pk, first_session.pk)
        first_session.refresh_from_db()
        self.enrollment.refresh_from_db()
        self.assertEqual(first_session.status, RecordingSession.Status.ABORTED)
        self.assertEqual(second_session.status, RecordingSession.Status.ACTIVE)
        self.assertEqual(self.enrollment.status, Enrollment.Status.IN_PROGRESS)
        self.assertEqual(self.enrollment.recording_sessions.count(), 2)

    def test_stale_stimulus_and_second_session_are_rejected(self) -> None:
        session = start_recording_session(self.enrollment, chooser=self.first)

        with self.assertRaises(StimulusMismatch):
            record_retry_attempt(
                session,
                self.stimuli[1],
                status=RecordingAttempt.Status.TIMED_OUT,
            )

        with self.assertRaises(RecordingWorkflowError):
            start_recording_session(self.enrollment, chooser=self.first)
