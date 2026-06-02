"""Pydantic/SQLModel schemas for API requests and responses.

These classes are not database tables. They define the JSON shapes exchanged
between the browser and the FastAPI backend.
"""

from typing import Optional

from sqlmodel import SQLModel

from mandarin_tone_recorder.models import ExperimentCondition, SpeakerType


class StimulusOut(SQLModel):
    """Stimulus data sent to the browser."""

    stimulus_id: str
    display_text: str
    experiment_condition: ExperimentCondition
    target_tone: Optional[int] = None

    ascii: str = ""
    pinyin_base: str = ""
    initial: str = ""
    rhyme: str = ""

    onset: str = ""
    medial: str = ""
    nucleus: str = ""
    coda: str = ""
    ipa_base: str = ""

    is_attested: bool = True


class CreateSessionRequest(SQLModel):
    """Request body for creating a new recording session."""

    participant_code: str = "anonymous"
    speaker_type: SpeakerType = SpeakerType.LEARNER
    mandarin_background: str = ""

    experiment_condition: ExperimentCondition = ExperimentCondition.TONE_BEARING
    target_duration_sec: int = 600


class CreateSessionResponse(SQLModel):
    """Response returned after a session is created."""

    session_code: str
    first_stimulus: StimulusOut
    target_duration_sec: int
    max_duration_sec: float


class AttemptResponse(SQLModel):
    """Response returned after saving an attempt or recording an event."""

    ok: bool
    session_code: str
    session_done: bool
    target_duration_reached: bool
    next_stimulus: Optional[StimulusOut] = None
    message: str = ""


class TimeoutAttemptRequest(SQLModel):
    """Request body for recording a timed-out stimulus attempt."""

    stimulus_id: str
    stimulus_index: int
    duration_sec: float
