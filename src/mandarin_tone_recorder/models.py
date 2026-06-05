"""SQLModel table definitions for Mandarin Tone Recorder.

The models in this file describe the persistent domain objects:

- base syllables
- concrete stimuli
- participants
- recording sessions
- recording attempts

These are database models, not request/response schemas. API schemas live in
``schemas.py`` so that the database representation can evolve independently
from the public API shape.
"""

from datetime import datetime, timezone
from enum import StrEnum
from typing import Optional

from sqlmodel import Field, Relationship, SQLModel


def utc_now() -> datetime:
    """Return the current UTC time as a naive datetime.

    SQLite does not reliably preserve timezone information when datetime
    values are round-tripped through SQLModel/SQLAlchemy. To avoid mixing
    offset-aware and offset-naive datetimes, the app stores all database
    timestamps as naive UTC.

    In other words, a timestamp like:

        2026-06-01 20:15:00

    should be interpreted as UTC, even though it has no tzinfo attached.
    """
    return datetime.now(timezone.utc).replace(tzinfo=None)


class ExperimentCondition(StrEnum):
    """Supported recording conditions.

    ``tone_bearing`` means the participant is explicitly prompted with tones
    1-4. ``tone_unspecified`` means the prompt does not specify a tone.
    """

    TONE_BEARING = "tone_bearing"
    TONE_UNSPECIFIED = "tone_unspecified"


class SessionStatus(StrEnum):
    """Lifecycle states for a recording session."""

    ACTIVE = "active"
    FINISHED = "finished"
    ABORTED = "aborted"


class AttemptStatus(StrEnum):
    """Possible outcomes for one stimulus attempt."""

    ACCEPTED = "accepted"
    TIMED_OUT = "timed_out"
    SPEAKER_REJECTED = "speaker_rejected"
    ABORTED = "aborted"
    SAVE_FAILED = "save_failed"


class SpeakerType(StrEnum):
    """Broad participant categories."""

    NATIVE = "native"
    HERITAGE = "heritage"
    LEARNER = "learner"
    OTHER = "other"


class BaseSyllable(SQLModel, table=True):
    """A Mandarin syllable without tone.

    This table stores the segmental identity of the syllable. It includes both
    an intuitive initial/rhyme representation and the more detailed
    onset/medial/nucleus/coda representation.
    """

    id: Optional[int] = Field(default=None, primary_key=True)

    ascii: str = Field(index=True, unique=True)
    pinyin_base: str = Field(index=True)

    initial: str = Field(default="", index=True)
    rhyme: str = Field(default="", index=True)

    onset: str = Field(default="", index=True)
    medial: str = Field(default="", index=True)
    nucleus: str = Field(default="", index=True)
    coda: str = Field(default="", index=True)

    ipa_base: str = Field(default="")

    stimuli: list["Stimulus"] = Relationship(back_populates="base_syllable")


class Stimulus(SQLModel, table=True):
    """A concrete prompt shown to the participant.

    A stimulus may be tone-bearing, such as ``mǎ`` / ``ma3``, or tone
    unspecified, such as plain ``ma``. The target tone is null for
    tone-unspecified stimuli.
    """

    id: Optional[int] = Field(default=None, primary_key=True)

    stimulus_id: str = Field(index=True, unique=True)
    base_syllable_id: int = Field(foreign_key="basesyllable.id", index=True)

    experiment_condition: ExperimentCondition = Field(index=True)
    target_tone: Optional[int] = Field(default=None, index=True)

    display_text: str
    prompt_type: str = Field(default="pinyin")
    is_attested: bool = Field(default=True, index=True)

    base_syllable: BaseSyllable = Relationship(back_populates="stimuli")
    attempts: list["RecordingAttempt"] = Relationship(back_populates="stimulus")


class Participant(SQLModel, table=True):
    """A person contributing recordings.

    This table intentionally stores only lightweight participant metadata for
    now. IRB/consent-sensitive details can be handled separately if needed.
    """

    id: Optional[int] = Field(default=None, primary_key=True)

    participant_code: str = Field(index=True, unique=True)
    speaker_type: SpeakerType = Field(default=SpeakerType.LEARNER, index=True)
    mandarin_background: str = Field(default="")

    created_at: datetime = Field(default_factory=utc_now)

    sessions: list["RecordingSession"] = Relationship(back_populates="participant")


class RecordingSession(SQLModel, table=True):
    """One continuous recording period for one participant.

    A session is time-targeted rather than item-count-targeted. The target
    duration is a soft stopping point, not a hard timeout.
    """

    id: Optional[int] = Field(default=None, primary_key=True)

    session_code: str = Field(index=True, unique=True)
    participant_id: int = Field(foreign_key="participant.id", index=True)

    experiment_condition: ExperimentCondition = Field(index=True)
    target_duration_sec: int

    status: SessionStatus = Field(default=SessionStatus.ACTIVE, index=True)

    started_at: datetime = Field(default_factory=utc_now)
    ended_at: Optional[datetime] = Field(default=None)

    participant: Participant = Relationship(back_populates="sessions")
    attempts: list["RecordingAttempt"] = Relationship(back_populates="session")


class RecordingAttempt(SQLModel, table=True):
    """One attempt at one stimulus.

    Accepted attempts have audio paths. Timed-out attempts may have no audio
    path but are still useful for tracking difficult stimuli.
    """

    id: Optional[int] = Field(default=None, primary_key=True)

    recording_id: str = Field(index=True, unique=True)

    session_id: int = Field(foreign_key="recordingsession.id", index=True)
    stimulus_id: int = Field(foreign_key="stimulus.id", index=True)

    stimulus_index: int = Field(index=True)
    attempt_number: int = Field(default=1)

    status: AttemptStatus = Field(index=True)

    duration_sec: Optional[float] = Field(default=None)

    mime_type: str = Field(default="")
    raw_audio_path: str = Field(default="")
    wav_audio_path: str = Field(default="")

    created_at: datetime = Field(default_factory=utc_now)

    session: RecordingSession = Relationship(back_populates="attempts")
    stimulus: Stimulus = Relationship(back_populates="attempts")
