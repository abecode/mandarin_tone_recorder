"""Stimulus assignment policy.

This module decides which stimulus should be shown next. Keeping the policy in
one module makes it easier to revise later, for example to balance by tone,
rhyme, participant group, or base syllable.
"""

import random

from sqlmodel import Session, func, select

from mandarin_tone_recorder.models import (
    AttemptStatus,
    BaseSyllable,
    ExperimentCondition,
    RecordingAttempt,
    RecordingSession,
    Stimulus,
)
from mandarin_tone_recorder.schemas import StimulusOut


def stimulus_to_out(stimulus: Stimulus) -> StimulusOut:
    """Convert a database Stimulus object into a browser-facing schema."""
    base = stimulus.base_syllable

    return StimulusOut(
        stimulus_id=stimulus.stimulus_id,
        display_text=stimulus.display_text,
        experiment_condition=stimulus.experiment_condition,
        target_tone=stimulus.target_tone,
        ascii=base.ascii,
        pinyin_base=base.pinyin_base,
        initial=base.initial,
        rhyme=base.rhyme,
        onset=base.onset,
        medial=base.medial,
        nucleus=base.nucleus,
        coda=base.coda,
        ipa_base=base.ipa_base,
        is_attested=stimulus.is_attested,
    )


def choose_next_stimulus(
    session: Session,
    recording_session: RecordingSession,
) -> Stimulus | None:
    """Choose the next stimulus for a recording session.

    Initial policy:

    1. Only consider stimuli from the session's experiment condition.
    2. Do not repeat stimuli already accepted in this session.
    3. Prefer stimuli with the fewest accepted recordings globally.
    4. Break ties randomly.

    This makes early dropout less damaging because the system keeps steering
    participants toward under-recorded items.
    """
    accepted_in_this_session_query = (
        select(RecordingAttempt.stimulus_id)
        .where(RecordingAttempt.session_id == recording_session.id)
        .where(RecordingAttempt.status == AttemptStatus.ACCEPTED)
    )

    eligible_stimuli = session.exec(
        select(Stimulus)
        .join(BaseSyllable, Stimulus.base_syllable_id == BaseSyllable.id)
        .where(Stimulus.experiment_condition == recording_session.experiment_condition)
        .where(Stimulus.id.not_in(accepted_in_this_session_query))
    ).all()

    if not eligible_stimuli:
        return None

    accepted_counts = dict(
        session.exec(
            select(
                RecordingAttempt.stimulus_id,
                func.count(RecordingAttempt.id),
            )
            .where(RecordingAttempt.status == AttemptStatus.ACCEPTED)
            .group_by(RecordingAttempt.stimulus_id)
        ).all()
    )

    min_count = min(accepted_counts.get(stimulus.id, 0) for stimulus in eligible_stimuli)

    lowest_count_stimuli = [
        stimulus
        for stimulus in eligible_stimuli
        if accepted_counts.get(stimulus.id, 0) == min_count
    ]

    return random.choice(lowest_count_stimuli) 
