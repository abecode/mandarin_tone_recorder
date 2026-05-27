"""FastAPI web application for the Mandarin tone recorder.

This module defines the current web interface. It is intentionally thin:
request parsing and HTTP responses live here, while reusable logic lives in
``stimuli.py`` and ``recording_store.py``.

That separation should make it easier to move from FastAPI to Django later.
"""

import json
from typing import Annotated

import uvicorn
from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from mandarin_tone_recorder.config import (
    AUDIO_DIR,
    METADATA_CSV,
    STATIC_DIR,
    STIMULI_CSV,
    TARGET_SAMPLE_RATE,
    TEMPLATES_DIR,
)
from mandarin_tone_recorder.recording_store import (
    RecordingChunk,
    save_recording_chunk,
)
from mandarin_tone_recorder.stimuli import StimulusManager


def create_app() -> FastAPI:
    """Create and configure the FastAPI application.

    The app has two responsibilities:

    1. Serve the recorder page, CSS, and JavaScript.
    2. Receive one uploaded audio chunk per stimulus and pass it to the
       framework-independent storage layer.

    Returns
    -------
    FastAPI
        A configured FastAPI application instance.
    """
    app = FastAPI(title="Mandarin Tone Recorder")

    app.mount(
        "/static",
        StaticFiles(directory=str(STATIC_DIR)),
        name="static",
    )

    templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
    stimulus_manager = StimulusManager(STIMULI_CSV)

    @app.get("/")
    async def recorder_page(request: Request):
        """Render the subject-facing recording page.

        A randomized stimulus list is serialized into the HTML page. The
        browser then advances through that list locally without needing a
        server request for every stimulus.

        Parameters
        ----------
        request:
            FastAPI/Starlette request object required by Jinja templates.

        Returns
        -------
        TemplateResponse
            The rendered recorder page.
        """
        stimuli = stimulus_manager.all_stimuli(shuffle=True, limit=None)

        return templates.TemplateResponse(
            request,
            "recorder.html",
            {
                "stimuli_json": json.dumps(stimuli, ensure_ascii=False),
            },
        )

    @app.post("/api/recordings/chunk")
    async def upload_recording_chunk(
        file: Annotated[UploadFile, File()],
        participant_id: Annotated[str, Form()] = "anonymous",
        session_id: Annotated[str, Form()] = "default_session",
        speaker_type: Annotated[str, Form()] = "",
        mandarin_background: Annotated[str, Form()] = "",
        stimulus_index: Annotated[int, Form()] = 0,
        stimulus_id: Annotated[str, Form()] = "",
        started_at_ms: Annotated[int, Form()] = 0,
        ended_at_ms: Annotated[int, Form()] = 0,
        mime_type: Annotated[str, Form()] = "",
    ):
        """Receive and save one browser-recorded stimulus chunk.

        The browser sends one multipart upload for each stimulus. The route
        validates the stimulus ID, reads the uploaded audio bytes, constructs a
        plain ``RecordingChunk`` dataclass, and delegates saving to
        ``save_recording_chunk``.

        Parameters
        ----------
        file:
            Uploaded audio file chunk from the browser.
        participant_id:
            Participant ID from the metadata form.
        session_id:
            Session ID from the metadata form.
        speaker_type:
            Speaker category selected in the form.
        mandarin_background:
            Free-text Mandarin background information.
        stimulus_index:
            One-based position of this stimulus within the session.
        stimulus_id:
            Stable stimulus ID from the CSV.
        started_at_ms:
            Browser timestamp when this stimulus segment began.
        ended_at_ms:
            Browser timestamp when this stimulus segment ended.
        mime_type:
            MIME type reported by the browser recorder.

        Returns
        -------
        JSONResponse
            JSON describing the saved recording and metadata row.

        Raises
        ------
        HTTPException
            If the stimulus ID is unknown or the uploaded audio is empty.
        """
        stimulus = stimulus_manager.by_id(stimulus_id)

        if stimulus is None:
            raise HTTPException(
                status_code=400,
                detail=f"Unknown stimulus_id: {stimulus_id}",
            )

        audio_bytes = await file.read()

        if not audio_bytes:
            raise HTTPException(
                status_code=400,
                detail="Empty audio upload.",
            )

        result = save_recording_chunk(
            RecordingChunk(
                participant_id=participant_id,
                session_id=session_id,
                speaker_type=speaker_type,
                mandarin_background=mandarin_background,
                stimulus_index=stimulus_index,
                stimulus_id=stimulus_id,
                stimulus=stimulus,
                started_at_ms=started_at_ms,
                ended_at_ms=ended_at_ms,
                mime_type=mime_type or file.content_type or "",
                audio_bytes=audio_bytes,
            ),
            audio_dir=AUDIO_DIR,
            metadata_csv=METADATA_CSV,
            target_sample_rate=TARGET_SAMPLE_RATE,
        )

        return JSONResponse({"ok": True, **result})

    return app


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
