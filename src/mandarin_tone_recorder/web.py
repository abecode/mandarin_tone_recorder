"""FastAPI web application for the Mandarin tone recorder.

The web layer is intentionally thin:

- HTML/CSS/JS serving
- API request parsing
- database session dependency wiring
- delegation to assignment and storage modules

The database models, assignment policy, and file storage logic live elsewhere.
"""

import uuid
from typing import Annotated

import uvicorn
from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlmodel import Session, select

from mandarin_tone_recorder.assignment import choose_next_stimulus, stimulus_to_out
from mandarin_tone_recorder.config import (
    AUDIO_DIR,
    DEFAULT_SESSION_TARGET_DURATION_SEC,
    MAX_DURATION_SEC,
    STATIC_DIR,
    TARGET_SAMPLE_RATE,
    TEMPLATES_DIR,
)
from mandarin_tone_recorder.database import get_session, init_db
from mandarin_tone_recorder.models import (
    AttemptStatus,
    ExperimentCondition,
    Participant,
    RecordingAttempt,
    RecordingSession,
    SessionStatus,
    SpeakerType,
    Stimulus,
    utc_now,
)
from mandarin_tone_recorder.recording_store import (
    RecordingChunk,
    save_recording_chunk,
)
from mandarin_tone_recorder.schemas import (
    CreateSessionRequest,
    CreateSessionResponse,
    SpeakerRejectedAttemptRequest,
    TimeoutAttemptRequest,
)


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    app = FastAPI(title="Mandarin Tone Recorder")

    app.mount(
        "/static",
        StaticFiles(directory=str(STATIC_DIR)),
        name="static",
    )

    templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

    @app.on_event("startup")
    def on_startup() -> None:
        """Initialize database tables on app startup."""
        init_db()

    @app.get("/")
    async def recorder_page(request: Request):
        """Render the subject-facing recorder page.

        Unlike the earlier prototype, this page does not receive all stimuli at
        load time. The browser creates a session through the API and receives
        one stimulus at a time.
        """
        return templates.TemplateResponse(
            request,
            "recorder.html",
            {
                "max_duration_sec": MAX_DURATION_SEC,
                "default_session_target_duration_sec": DEFAULT_SESSION_TARGET_DURATION_SEC,
                "static_version": str(
                    max(
                        STATIC_DIR.joinpath("recorder.css").stat().st_mtime_ns,
                        STATIC_DIR.joinpath("recorder.js").stat().st_mtime_ns,
                    )
                ),
            },
        )

    @app.post("/api/sessions", response_model=CreateSessionResponse)
    async def create_recording_session(
        request_data: CreateSessionRequest,
        db: Annotated[Session, Depends(get_session)],
    ):
        """Create a database-backed recording session and return first stimulus."""
        participant = db.exec(
            select(Participant).where(
                Participant.participant_code == request_data.participant_code
            )
        ).first()

        if participant is None:
            participant = Participant(
                participant_code=request_data.participant_code,
                speaker_type=request_data.speaker_type,
                mandarin_background=request_data.mandarin_background,
            )
            db.add(participant)
            db.commit()
            db.refresh(participant)
        else:
            # Keep lightweight participant metadata fresh during prototyping.
            participant.speaker_type = request_data.speaker_type
            participant.mandarin_background = request_data.mandarin_background
            db.add(participant)
            db.commit()
            db.refresh(participant)

        session_code = f"session_{uuid.uuid4().hex[:12]}"

        recording_session = RecordingSession(
            session_code=session_code,
            participant_id=participant.id,
            experiment_condition=request_data.experiment_condition,
            target_duration_sec=request_data.target_duration_sec,
            status=SessionStatus.ACTIVE,
        )

        db.add(recording_session)
        db.commit()
        db.refresh(recording_session)

        first_stimulus = choose_next_stimulus(db, recording_session)

        if first_stimulus is None:
            raise HTTPException(
                status_code=400,
                detail="No eligible stimuli are available for this condition.",
            )

        return CreateSessionResponse(
            session_code=session_code,
            first_stimulus=stimulus_to_out(first_stimulus),
            target_duration_sec=recording_session.target_duration_sec,
            max_duration_sec=MAX_DURATION_SEC,
        )

    @app.post("/api/sessions/{session_code}/attempts")
    async def upload_recording_attempt(
        session_code: str,
        file: Annotated[UploadFile, File()],
        stimulus_id: Annotated[str, Form()],
        stimulus_index: Annotated[int, Form()],
        started_at_ms: Annotated[int, Form()],
        ended_at_ms: Annotated[int, Form()],
        mime_type: Annotated[str, Form()] = "",
        db: Session = Depends(get_session),
    ):
        """Save one accepted recording attempt and return the next stimulus."""
        recording_session = get_active_session_or_404(db, session_code)
        stimulus = get_stimulus_or_404(db, stimulus_id)
        validate_stimulus_matches_session(recording_session, stimulus)

        audio_bytes = await file.read()

        if not audio_bytes:
            raise HTTPException(status_code=400, detail="Empty audio upload.")

        recording_id = str(uuid.uuid4())

        file_result = save_recording_chunk(
            RecordingChunk(
                participant_id=recording_session.participant.participant_code,
                session_id=recording_session.session_code,
                speaker_type=recording_session.participant.speaker_type,
                mandarin_background=recording_session.participant.mandarin_background,
                stimulus_index=stimulus_index,
                stimulus_id=stimulus.stimulus_id,
                stimulus={
                    "ascii": stimulus.base_syllable.ascii,
                    "pinyin": stimulus.display_text,
                    "tone": stimulus.target_tone or "",
                },
                started_at_ms=started_at_ms,
                ended_at_ms=ended_at_ms,
                mime_type=mime_type or file.content_type or "",
                audio_bytes=audio_bytes,
            ),
            audio_dir=AUDIO_DIR,
            target_sample_rate=TARGET_SAMPLE_RATE,
            recording_id=recording_id,
        )

        duration_sec = (ended_at_ms - started_at_ms) / 1000.0

        attempt = RecordingAttempt(
            recording_id=recording_id,
            session_id=recording_session.id,
            stimulus_id=stimulus.id,
            stimulus_index=stimulus_index,
            attempt_number=get_next_attempt_number(db, recording_session.id, stimulus.id),
            status=AttemptStatus.ACCEPTED,
            duration_sec=duration_sec,
            mime_type=mime_type or file.content_type or "",
            raw_audio_path=file_result["raw_audio_path"],
            wav_audio_path=file_result.get("wav_audio_path") or "",
        )

        db.add(attempt)
        db.commit()

        return next_stimulus_response(db, recording_session)

    @app.post("/api/sessions/{session_code}/timeouts")
    async def record_timeout_attempt(
        session_code: str,
        request_data: TimeoutAttemptRequest,
        db: Annotated[Session, Depends(get_session)],
    ):
        """Record a timed-out attempt and return the same stimulus for retry."""
        recording_session = get_active_session_or_404(db, session_code)
        stimulus = get_stimulus_or_404(db, request_data.stimulus_id)
        validate_stimulus_matches_session(recording_session, stimulus)

        record_non_audio_attempt(
            db=db,
            recording_session=recording_session,
            stimulus=stimulus,
            stimulus_index=request_data.stimulus_index,
            duration_sec=request_data.duration_sec,
            status=AttemptStatus.TIMED_OUT,
        )

        return JSONResponse(
            {
                "ok": True,
                "session_code": recording_session.session_code,
                "session_done": False,
                "target_duration_reached": has_reached_target_duration(recording_session),
                "next_stimulus": stimulus_to_out(stimulus).model_dump(mode="json"),
                "message": "Timed out. Please try the same stimulus again.",
            }
        )

    @app.post("/api/sessions/{session_code}/speaker-rejections")
    async def record_speaker_rejected_attempt(
        session_code: str,
        request_data: SpeakerRejectedAttemptRequest,
        db: Annotated[Session, Depends(get_session)],
    ):
        """Record a speaker-rejected attempt and return the same stimulus."""
        recording_session = get_active_session_or_404(db, session_code)
        stimulus = get_stimulus_or_404(db, request_data.stimulus_id)
        validate_stimulus_matches_session(recording_session, stimulus)

        record_non_audio_attempt(
            db=db,
            recording_session=recording_session,
            stimulus=stimulus,
            stimulus_index=request_data.stimulus_index,
            duration_sec=request_data.duration_sec,
            status=AttemptStatus.SPEAKER_REJECTED,
        )

        return JSONResponse(
            {
                "ok": True,
                "session_code": recording_session.session_code,
                "session_done": False,
                "target_duration_reached": has_reached_target_duration(recording_session),
                "next_stimulus": stimulus_to_out(stimulus).model_dump(mode="json"),
                "message": "Redo recorded. Please try the same stimulus again.",
            }
        )

    @app.post("/api/sessions/{session_code}/abort")
    async def abort_recording_session(
        session_code: str,
        db: Annotated[Session, Depends(get_session)],
    ):
        """Mark a session as aborted."""
        recording_session = get_active_session_or_404(db, session_code)
        recording_session.status = SessionStatus.ABORTED
        recording_session.ended_at = utc_now()

        db.add(recording_session)
        db.commit()

        return {"ok": True, "message": "Session aborted."}

    @app.post("/api/sessions/{session_code}/finish")
    async def finish_recording_session(
        session_code: str,
        db: Annotated[Session, Depends(get_session)],
    ):
        """Mark a session as normally finished."""
        recording_session = get_active_session_or_404(db, session_code)
        recording_session.status = SessionStatus.FINISHED
        recording_session.ended_at = utc_now()

        db.add(recording_session)
        db.commit()

        return {"ok": True, "message": "Session finished."}

    return app


def get_active_session_or_404(db: Session, session_code: str) -> RecordingSession:
    """Return an active recording session or raise 404/400."""
    recording_session = db.exec(
        select(RecordingSession).where(RecordingSession.session_code == session_code)
    ).first()

    if recording_session is None:
        raise HTTPException(status_code=404, detail="Session not found.")

    if recording_session.status != SessionStatus.ACTIVE:
        raise HTTPException(status_code=400, detail="Session is not active.")

    return recording_session


def get_stimulus_or_404(db: Session, stimulus_id: str) -> Stimulus:
    """Return a stimulus by public stimulus_id or raise 404."""
    stimulus = db.exec(
        select(Stimulus).where(Stimulus.stimulus_id == stimulus_id)
    ).first()

    if stimulus is None:
        raise HTTPException(status_code=404, detail="Stimulus not found.")

    return stimulus


def validate_stimulus_matches_session(
    recording_session: RecordingSession,
    stimulus: Stimulus,
) -> None:
    """Reject stimuli that do not belong to the session's condition."""
    if stimulus.experiment_condition != recording_session.experiment_condition:
        raise HTTPException(
            status_code=400,
            detail=(
                "Stimulus experiment condition does not match "
                "the recording session condition."
            ),
        )


def record_non_audio_attempt(
    *,
    db: Session,
    recording_session: RecordingSession,
    stimulus: Stimulus,
    stimulus_index: int,
    duration_sec: float,
    status: AttemptStatus,
) -> RecordingAttempt:
    """Persist an attempt event that intentionally has no uploaded audio."""
    attempt = RecordingAttempt(
        recording_id=str(uuid.uuid4()),
        session_id=recording_session.id,
        stimulus_id=stimulus.id,
        stimulus_index=stimulus_index,
        attempt_number=get_next_attempt_number(db, recording_session.id, stimulus.id),
        status=status,
        duration_sec=duration_sec,
        mime_type="",
        raw_audio_path="",
        wav_audio_path="",
    )

    db.add(attempt)
    db.commit()

    return attempt


def get_next_attempt_number(
    db: Session,
    session_id: int,
    stimulus_db_id: int,
) -> int:
    """Return the next attempt number for a session/stimulus pair."""
    previous_attempts = db.exec(
        select(RecordingAttempt)
        .where(RecordingAttempt.session_id == session_id)
        .where(RecordingAttempt.stimulus_id == stimulus_db_id)
    ).all()

    return len(previous_attempts) + 1


def has_reached_target_duration(recording_session: RecordingSession) -> bool:
    """Return whether a session has reached its soft target duration.

    Database timestamps are stored as naive UTC datetimes. Therefore this
    function also uses a naive UTC ``now`` value before subtracting.
    """
    elapsed = utc_now() - recording_session.started_at
    return elapsed.total_seconds() >= recording_session.target_duration_sec


def next_stimulus_response(
    db: Session,
    recording_session: RecordingSession,
):
    """Choose the next stimulus and format a JSON response."""
    next_stimulus = choose_next_stimulus(db, recording_session)
    target_reached = has_reached_target_duration(recording_session)

    if next_stimulus is None:
        recording_session.status = SessionStatus.FINISHED
        recording_session.ended_at = utc_now()
        db.add(recording_session)
        db.commit()

        return JSONResponse(
            {
                "ok": True,
                "session_code": recording_session.session_code,
                "session_done": True,
                "target_duration_reached": target_reached,
                "next_stimulus": None,
                "message": "All eligible stimuli completed.",
            }
        )

    return JSONResponse(
        {
            "ok": True,
            "session_code": recording_session.session_code,
            "session_done": False,
            "target_duration_reached": target_reached,
            "next_stimulus": stimulus_to_out(next_stimulus).model_dump(mode="json"),
            "message": "",
        }
    )


app = create_app()


def main() -> None:
    """Run the FastAPI app with uvicorn for local development."""
    uvicorn.run(
        "mandarin_tone_recorder.web:app",
        host="127.0.0.1",
        port=7860,
        reload=True,
    )


if __name__ == "__main__":
    main()

    
