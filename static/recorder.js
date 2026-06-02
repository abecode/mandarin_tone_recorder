/**
 * Browser-side recording interface for the Mandarin Tone Recorder.
 *
 * This version uses a server-driven stimulus workflow:
 *
 *   Start
 *     -> create a session on the server
 *     -> receive first stimulus
 *     -> start recording
 *
 *   Next / Finish
 *     -> upload current recording attempt
 *     -> server saves attempt
 *     -> server chooses next stimulus
 *     -> browser displays next stimulus
 *
 *   Timeout
 *     -> discard current audio locally
 *     -> notify server of a timed-out attempt
 *     -> server returns the same stimulus for retry
 *
 *   Stop Session
 *     -> abort the server-side session
 *     -> discard current unfinished recording
 *
 * The browser no longer receives all stimuli at page load. The server is the
 * source of truth for session state and stimulus assignment.
 */


/* -------------------------------------------------------------------------- */
/* Configuration injected by recorder.html                                    */
/* -------------------------------------------------------------------------- */

/**
 * Maximum allowed duration for one stimulus recording.
 *
 * This is injected by the FastAPI/Jinja template from config.MAX_DURATION_SEC.
 */
const maxDurationSec = window.MTR_MAX_DURATION_SEC || 7.0;
const maxDurationMs = maxDurationSec * 1000;

/**
 * Default target session duration.
 *
 * This is a soft target, not a hard timeout. The backend will tell us when the
 * target has been reached after an upload.
 */
const defaultSessionTargetDurationSec =
  window.MTR_DEFAULT_SESSION_TARGET_DURATION_SEC || 600;


/* -------------------------------------------------------------------------- */
/* DOM elements                                                               */
/* -------------------------------------------------------------------------- */

// Main display elements.
const stimulusEl = document.getElementById("stimulus");
const detailsEl = document.getElementById("stimulus-details");
const progressEl = document.getElementById("progress");
const statusEl = document.getElementById("status");

// Recording controls.
const startBtn = document.getElementById("start-btn");
const nextBtn = document.getElementById("next-btn");
const stopBtn = document.getElementById("stop-btn");

// Participant/session metadata fields.
const participantIdEl = document.getElementById("participant-id");
const speakerTypeEl = document.getElementById("speaker-type");
const mandarinBackgroundEl = document.getElementById("mandarin-background");

// New server-driven-session fields.
const experimentConditionEl = document.getElementById("experiment-condition");
const targetDurationSecEl = document.getElementById("target-duration-sec");


/* -------------------------------------------------------------------------- */
/* Browser recording state                                                    */
/* -------------------------------------------------------------------------- */

// Browser microphone stream.
let stream = null;

// MediaRecorder instance for the current stimulus segment.
let recorder = null;

// Chosen browser-supported MIME type, for example "audio/webm;codecs=opus".
let mimeType = "";

// Timer that enforces max duration for one stimulus recording.
let segmentTimeoutId = null;

// Safety token used to ignore late async events from old recorder/session state.
let sessionGeneration = 0;


/* -------------------------------------------------------------------------- */
/* Server/session state                                                       */
/* -------------------------------------------------------------------------- */

/**
 * Server-generated session code.
 *
 * This is returned by POST /api/sessions and then used in subsequent calls:
 *
 *   /api/sessions/{sessionCode}/attempts
 *   /api/sessions/{sessionCode}/timeouts
 *   /api/sessions/{sessionCode}/abort
 *   /api/sessions/{sessionCode}/finish
 */
let sessionCode = null;

/**
 * Current stimulus returned by the server.
 *
 * Shape expected:
 *
 * {
 *   stimulus_id: "...",
 *   display_text: "...",
 *   experiment_condition: "tone_bearing",
 *   target_tone: 1,
 *   ascii: "...",
 *   pinyin_base: "...",
 *   initial: "...",
 *   rhyme: "...",
 *   onset: "...",
 *   medial: "...",
 *   nucleus: "...",
 *   coda: "...",
 *   ipa_base: "...",
 *   is_attested: true
 * }
 */
let currentStimulusData = null;

/**
 * One-based counter for the number of stimuli shown in the current session.
 *
 * This is not a database primary key. It is a display/order counter for the
 * current session.
 */
let currentIndex = 0;

// Browser timestamp for the beginning of the current stimulus segment.
let segmentStartMs = null;

// Count of successfully uploaded accepted recordings in the current session.
let uploadCount = 0;


/* -------------------------------------------------------------------------- */
/* UI mode state                                                              */
/* -------------------------------------------------------------------------- */

/**
 * Current app mode.
 *
 * Keeping this explicit prevents the Next button from doing the wrong thing
 * during saving, timeout, or abort states.
 */
let currentMode = "ready";
// possible values:
// "ready"
// "recording"
// "saving"
// "timed_out"
// "finished"
// "aborted"

// If true, the next MediaRecorder blob is discarded instead of uploaded.
let discardNextBlob = false;


/* -------------------------------------------------------------------------- */
/* Small UI helpers                                                           */
/* -------------------------------------------------------------------------- */

/**
 * Display a status message for the subject/researcher.
 *
 * @param {string} message - Message to show in the status area.
 */
function setStatus(message) {
  statusEl.textContent = message;
}


/**
 * Display progress through the recording session.
 *
 * @param {string} message - Message to show in the progress area.
 */
function setProgress(message) {
  progressEl.textContent = message;
}


/**
 * Disable participant/session form inputs during recording.
 *
 * This prevents metadata from changing halfway through a session.
 */
function disableMetadataInputs() {
  participantIdEl.disabled = true;
  speakerTypeEl.disabled = true;
  mandarinBackgroundEl.disabled = true;
  experimentConditionEl.disabled = true;
  targetDurationSecEl.disabled = true;
}


/**
 * Re-enable participant/session form inputs after a session finishes or aborts.
 */
function enableMetadataInputs() {
  participantIdEl.disabled = false;
  speakerTypeEl.disabled = false;
  mandarinBackgroundEl.disabled = false;
  experimentConditionEl.disabled = false;
  targetDurationSecEl.disabled = false;
}


/**
 * Reset the visible UI to the initial ready state.
 *
 * This does not create or abort server sessions. It only changes the display.
 */
function showReadyUi() {
  stimulusEl.textContent = "Ready";
  detailsEl.textContent = "";
  setProgress("Press Start to begin.");
  setStatus("");

  nextBtn.classList.add("hidden");
  stopBtn.classList.add("hidden");

  startBtn.textContent = "Start";
  startBtn.disabled = false;
  startBtn.classList.remove("hidden");
}


/**
 * Show the active recording controls.
 */
function showRecordingControls() {
  startBtn.classList.add("hidden");
  nextBtn.classList.remove("hidden");
  stopBtn.classList.remove("hidden");

  nextBtn.disabled = false;
  stopBtn.disabled = false;
}


/**
 * Show the completed/finished UI.
 *
 * @param {string} message - Status message to show after finishing.
 */
function showFinishedUi(message) {
  stimulusEl.textContent = "Done";
  detailsEl.textContent = "";

  setProgress("Session complete.");
  setStatus(message || `Saved ${uploadCount} recording(s).`);

  nextBtn.classList.add("hidden");
  stopBtn.classList.add("hidden");

  startBtn.textContent = "Start Again";
  startBtn.disabled = false;
  startBtn.classList.remove("hidden");

  enableMetadataInputs();
}


/**
 * Show the aborted/stopped UI.
 *
 * @param {string} message - Status message to show after aborting.
 */
function showAbortedUi(message) {
  stimulusEl.textContent = "Stopped";
  detailsEl.textContent = "";

  setProgress("Session stopped.");
  setStatus(message || "Session stopped. Current incomplete stimulus was not saved.");

  nextBtn.classList.add("hidden");
  stopBtn.classList.add("hidden");

  startBtn.textContent = "Start Again";
  startBtn.disabled = false;
  startBtn.classList.remove("hidden");

  enableMetadataInputs();
}


/* -------------------------------------------------------------------------- */
/* Stimulus rendering                                                         */
/* -------------------------------------------------------------------------- */

/**
 * Render the current server-provided stimulus.
 *
 * Unlike the old version, this function does not index into a local stimulus
 * list. It only displays currentStimulusData, which came from the server.
 */
function showCurrentStimulus() {
  if (!currentStimulusData) {
    stimulusEl.textContent = "Ready";
    detailsEl.textContent = "";
    setProgress("No stimulus loaded.");
    return;
  }

  stimulusEl.textContent = currentStimulusData.display_text || "";

  const parts = [];

  if (currentStimulusData.target_tone !== null &&
      currentStimulusData.target_tone !== undefined) {
    parts.push(`tone: ${currentStimulusData.target_tone}`);
  }

  if (currentStimulusData.initial || currentStimulusData.rhyme) {
    const initial = currentStimulusData.initial || "∅";
    const rhyme = currentStimulusData.rhyme || "";
    parts.push(`initial/rhyme: ${initial} + ${rhyme}`);
  }

  if (currentStimulusData.ipa_base) {
    parts.push(`IPA: /${currentStimulusData.ipa_base}/`);
  }

  if (currentStimulusData.is_attested !== undefined) {
    parts.push(`attested: ${currentStimulusData.is_attested}`);
  }

  detailsEl.textContent = parts.join("   ·   ");

  setProgress(`Stimulus ${currentIndex}`);

  nextBtn.textContent = "Next";
}


/* -------------------------------------------------------------------------- */
/* Browser MediaRecorder helpers                                              */
/* -------------------------------------------------------------------------- */

/**
 * Pick the best audio MIME type supported by this browser.
 *
 * Browser support differs. Chrome typically supports WebM/Opus, Firefox may
 * support Ogg/Opus, and Safari may prefer MP4-like audio.
 *
 * @returns {string} A MediaRecorder-compatible MIME type, or an empty string
 *   to let the browser choose its default.
 */
function chooseMimeType() {
  const candidates = [
    "audio/webm;codecs=opus",
    "audio/webm",
    "audio/ogg;codecs=opus",
    "audio/mp4"
  ];

  for (const candidate of candidates) {
    if (window.MediaRecorder && MediaRecorder.isTypeSupported(candidate)) {
      return candidate;
    }
  }

  return "";
}


/**
 * Clear the current per-stimulus timeout timer.
 */
function clearSegmentTimer() {
  if (segmentTimeoutId !== null) {
    clearTimeout(segmentTimeoutId);
    segmentTimeoutId = null;
  }
}


/**
 * Start a timeout timer for the current stimulus.
 *
 * When the timer fires, the current recording is discarded and the same
 * stimulus remains on screen for rerecording.
 */
function startSegmentTimer() {
  clearSegmentTimer();

  segmentTimeoutId = setTimeout(() => {
    handleSegmentTimeout();
  }, maxDurationMs);
}


/**
 * Start MediaRecorder for the currently displayed stimulus.
 *
 * This function is called:
 *
 * - after a session is created and first stimulus is shown
 * - after a successful upload and next stimulus is shown
 * - after timeout when the user clicks Try Again
 */
function startRecordingCurrentStimulus() {
  if (!stream) {
    setStatus("Microphone stream is not available.");
    return;
  }

  if (!currentStimulusData) {
    setStatus("No current stimulus is available.");
    return;
  }

  discardNextBlob = false;
  segmentStartMs = Date.now();
  currentMode = "recording";

  const options = mimeType ? { mimeType } : undefined;
  const recorderGeneration = sessionGeneration;

  recorder = new MediaRecorder(stream, options);

  recorder.ondataavailable = (event) => {
    handleDataAvailable(event, recorderGeneration);
  };

  recorder.onstop = () => {
    // Intentionally empty.
    //
    // We often stop the recorder to discard a timed-out segment and then
    // restart recording for the same stimulus. The microphone stream itself is
    // stopped only when the whole session finishes or aborts.
  };

  recorder.start();
  startSegmentTimer();

  showRecordingControls();

  nextBtn.textContent = "Next";
  setStatus(`Recording. Maximum duration per item: ${maxDurationSec.toFixed(1)} seconds.`);
}


/* -------------------------------------------------------------------------- */
/* Server API helpers                                                         */
/* -------------------------------------------------------------------------- */

/**
 * Create a recording session on the server.
 *
 * The server returns a session_code and the first stimulus. This replaces the
 * old approach of loading the entire stimulus list into the browser.
 *
 * @returns {Promise<Object>} CreateSessionResponse from the server.
 */
async function createSessionOnServer() {
  const participantCode = participantIdEl.value || "anonymous";
  const speakerType = speakerTypeEl.value || "learner";
  const mandarinBackground = mandarinBackgroundEl.value || "";
  const experimentCondition = experimentConditionEl.value || "tone_bearing";
  const targetDurationSec =
    Number(targetDurationSecEl.value) || defaultSessionTargetDurationSec;

  const response = await fetch("/api/sessions", {
    method: "POST",
    headers: {
      "Content-Type": "application/json"
    },
    body: JSON.stringify({
      participant_code: participantCode,
      speaker_type: speakerType,
      mandarin_background: mandarinBackground,
      experiment_condition: experimentCondition,
      target_duration_sec: targetDurationSec
    })
  });

  if (!response.ok) {
    const text = await response.text();
    throw new Error(`Could not create session: ${response.status} ${text}`);
  }

  return await response.json();
}


/**
 * Upload one accepted audio blob to the current server session.
 *
 * The server saves the recording attempt and returns the next stimulus.
 *
 * @param {Blob} blob - Audio data produced by MediaRecorder.
 * @param {number} startedAtMs - Browser timestamp when the segment began.
 * @param {number} endedAtMs - Browser timestamp when the segment ended.
 * @returns {Promise<Object>} AttemptResponse from the server.
 */
async function uploadAcceptedAttempt(blob, startedAtMs, endedAtMs) {
  if (!sessionCode) {
    throw new Error("No active session_code.");
  }

  if (!currentStimulusData) {
    throw new Error("No current stimulus.");
  }

  const form = new FormData();

  form.append("file", blob, `chunk_${currentIndex}.webm`);
  form.append("stimulus_id", currentStimulusData.stimulus_id);
  form.append("stimulus_index", String(currentIndex));
  form.append("started_at_ms", String(startedAtMs));
  form.append("ended_at_ms", String(endedAtMs));
  form.append("mime_type", mimeType || blob.type || "application/octet-stream");

  const response = await fetch(`/api/sessions/${sessionCode}/attempts`, {
    method: "POST",
    body: form
  });

  if (!response.ok) {
    const text = await response.text();
    throw new Error(`Upload failed: ${response.status} ${text}`);
  }

  return await response.json();
}


/**
 * Tell the server that the current stimulus timed out.
 *
 * The server records a timed_out attempt and returns the same stimulus for
 * retry. No audio is uploaded for timeout events.
 *
 * @returns {Promise<Object>} AttemptResponse from the server.
 */
async function recordTimeoutOnServer() {
  if (!sessionCode || !currentStimulusData) {
    return null;
  }

  const response = await fetch(`/api/sessions/${sessionCode}/timeouts`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json"
    },
    body: JSON.stringify({
      stimulus_id: currentStimulusData.stimulus_id,
      stimulus_index: currentIndex,
      duration_sec: maxDurationSec
    })
  });

  if (!response.ok) {
    const text = await response.text();
    throw new Error(`Could not record timeout: ${response.status} ${text}`);
  }

  return await response.json();
}


/**
 * Tell the server that the current session was aborted.
 *
 * This is called when the user clicks Stop Session. Already-saved attempts
 * remain saved, but the current unfinished stimulus is discarded.
 */
async function abortSessionOnServer() {
  if (!sessionCode) {
    return;
  }

  const response = await fetch(`/api/sessions/${sessionCode}/abort`, {
    method: "POST"
  });

  if (!response.ok) {
    const text = await response.text();
    throw new Error(`Could not abort session: ${response.status} ${text}`);
  }
}


/**
 * Tell the server that the current session finished normally.
 *
 * This is useful when the participant chooses to end after reaching the target
 * duration, or when no eligible stimuli remain.
 */
async function finishSessionOnServer() {
  if (!sessionCode) {
    return;
  }

  const response = await fetch(`/api/sessions/${sessionCode}/finish`, {
    method: "POST"
  });

  if (!response.ok) {
    const text = await response.text();
    throw new Error(`Could not finish session: ${response.status} ${text}`);
  }
}


/* -------------------------------------------------------------------------- */
/* Session lifecycle                                                          */
/* -------------------------------------------------------------------------- */

/**
 * Start a new recording session.
 *
 * This function:
 *
 * 1. Checks browser microphone support.
 * 2. Requests microphone permission.
 * 3. Creates a session on the server.
 * 4. Receives the first stimulus.
 * 5. Starts recording immediately.
 */
async function startSession() {
  if (!window.isSecureContext) {
    setStatus("Microphone access requires a secure context. Use localhost or HTTPS.");
    return;
  }

  if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
    setStatus("This browser does not expose microphone access here.");
    return;
  }

  if (!window.MediaRecorder) {
    setStatus("This browser does not support MediaRecorder. Try Chrome, Edge, or Firefox.");
    return;
  }

  startBtn.disabled = true;
  setStatus("Requesting microphone permission...");

  try {
    stream = await navigator.mediaDevices.getUserMedia({ audio: true });
  } catch (err) {
    startBtn.disabled = false;
    setStatus(`Could not access microphone: ${err.message}`);
    return;
  }

  setStatus("Creating session...");

  let sessionInfo;
  try {
    sessionInfo = await createSessionOnServer();
  } catch (err) {
    if (stream) {
      stream.getTracks().forEach((track) => track.stop());
      stream = null;
    }

    startBtn.disabled = false;
    setStatus(err.message);
    return;
  }

  sessionGeneration += 1;

  sessionCode = sessionInfo.session_code;
  currentStimulusData = sessionInfo.first_stimulus;
  currentIndex = 1;
  uploadCount = 0;

  mimeType = chooseMimeType();
  currentMode = "recording";
  discardNextBlob = false;

  disableMetadataInputs();
  showCurrentStimulus();
  startRecordingCurrentStimulus();
}


/**
 * Finish the current recording session normally.
 *
 * This is called when the backend reports that the session is done or when we
 * decide to end the session after target duration has been reached.
 */
async function finishSession(message) {
  currentMode = "finished";
  clearSegmentTimer();

  sessionGeneration += 1;

  const recorderToStop = recorder;
  recorder = null;

  if (recorderToStop && recorderToStop.state === "recording") {
    recorderToStop.stop();
  }

  if (stream) {
    stream.getTracks().forEach((track) => track.stop());
    stream = null;
  }

  try {
    await finishSessionOnServer();
  } catch (err) {
    console.error(err);
  }

  showFinishedUi(message || `Saved ${uploadCount} recording(s).`);

  sessionCode = null;
  currentStimulusData = null;
  currentIndex = 0;
}


/**
 * Abort the current session without saving the current unfinished segment.
 *
 * Already-saved previous attempts remain saved. The current in-progress
 * segment is discarded locally.
 *
 * @param {string} message - Message to show after aborting.
 */
async function abortSession(message) {
  currentMode = "aborted";
  clearSegmentTimer();

  sessionGeneration += 1;
  discardNextBlob = true;

  const recorderToStop = recorder;
  recorder = null;

  if (recorderToStop && recorderToStop.state === "recording") {
    recorderToStop.stop();
  }

  if (stream) {
    stream.getTracks().forEach((track) => track.stop());
    stream = null;
  }

  try {
    await abortSessionOnServer();
  } catch (err) {
    console.error(err);
    // We still show the local aborted UI. The console error is enough for now
    // during prototyping.
  }

  showAbortedUi(message || "Session stopped. Current incomplete stimulus was not saved.");

  sessionCode = null;
  currentStimulusData = null;
  currentIndex = 0;
}


/* -------------------------------------------------------------------------- */
/* Recording attempt lifecycle                                                */
/* -------------------------------------------------------------------------- */

/**
 * Handle an audio blob produced by MediaRecorder.
 *
 * Normal path:
 *
 *   Next clicked
 *     -> recorder.requestData()
 *     -> dataavailable fires
 *     -> upload blob
 *     -> server returns next stimulus
 *     -> record next stimulus
 *
 * Timeout/abort path:
 *
 *   recorder.stop()
 *     -> dataavailable may fire
 *     -> discard blob
 *
 * @param {BlobEvent} event - MediaRecorder event containing the audio blob.
 * @param {number} recorderGeneration - Generation token captured when recorder
 *   was created.
 */
async function handleDataAvailable(event, recorderGeneration) {
  if (recorderGeneration !== sessionGeneration) {
    return;
  }

  if (discardNextBlob) {
    discardNextBlob = false;
    return;
  }

  if (!event.data || event.data.size === 0) {
    currentMode = "recording";
    nextBtn.disabled = false;
    stopBtn.disabled = false;
    return;
  }

  if (currentMode !== "saving") {
    // If we somehow get a blob outside the normal saving state, do not upload.
    return;
  }

  const startedAtMs = segmentStartMs;
  const endedAtMs = Date.now();

  const blob = new Blob([event.data], {
    type: mimeType || event.data.type || "audio/webm"
  });

  try {
    const result = await uploadAcceptedAttempt(blob, startedAtMs, endedAtMs);

    uploadCount += 1;

    if (result.session_done) {
      await finishSession(result.message || `Saved ${uploadCount} recording(s).`);
      return;
    }

    if (!result.next_stimulus) {
      await finishSession("No next stimulus was returned.");
      return;
    }

    currentStimulusData = result.next_stimulus;
    currentIndex += 1;

    showCurrentStimulus();

    if (result.target_duration_reached) {
      setStatus(
        "Target time reached. You may stop the session now, or continue recording."
      );
    } else {
      setStatus(`Saved ${uploadCount} recording(s).`);
    }

    startRecordingCurrentStimulus();
  } catch (err) {
    console.error(err);
    currentMode = "recording";
    setStatus(`Save failed: ${err.message}`);
    startSegmentTimer();
  } finally {
    if (currentMode !== "finished" && currentMode !== "aborted") {
      nextBtn.disabled = false;
      stopBtn.disabled = false;
    }
  }
}


/**
 * Save the current stimulus segment, retry after timeout, or finish.
 *
 * When currentMode is "timed_out", this button means Try Again.
 * When currentMode is "recording", this button means save and advance.
 */
function nextOrFinish() {
  if (currentMode === "timed_out") {
    setStatus("Recording retry.");
    setProgress(`Stimulus ${currentIndex}`);
    startRecordingCurrentStimulus();
    return;
  }

  if (currentMode !== "recording") {
    return;
  }

  if (!recorder || recorder.state !== "recording") {
    setStatus("Recorder is not active.");
    return;
  }

  currentMode = "saving";
  clearSegmentTimer();

  nextBtn.disabled = true;
  stopBtn.disabled = true;

  setProgress("Saving and advancing...");

  recorder.requestData();
}


/**
 * Handle per-stimulus timeout.
 *
 * The too-long recording is discarded. The server is notified of a timed-out
 * attempt. The same stimulus remains on screen for rerecording.
 */
async function handleSegmentTimeout() {
  if (currentMode !== "recording") {
    return;
  }

  clearSegmentTimer();

  currentMode = "timed_out";
  discardNextBlob = true;

  const recorderToStop = recorder;
  recorder = null;

  if (recorderToStop && recorderToStop.state === "recording") {
    recorderToStop.stop();
  }

  try {
    const result = await recordTimeoutOnServer();

    if (result && result.next_stimulus) {
      currentStimulusData = result.next_stimulus;
    }
  } catch (err) {
    console.error(err);
    setStatus(
      `Timed out, but could not record timeout on server: ${err.message}`
    );
  }

  setProgress("Timed out.");
  setStatus(
    `This recording exceeded ${maxDurationSec.toFixed(1)} seconds. ` +
    "Click Try Again to rerecord the same stimulus."
  );

  nextBtn.textContent = "Try Again";
  nextBtn.disabled = false;
  stopBtn.disabled = false;
}


/* -------------------------------------------------------------------------- */
/* Event listeners                                                            */
/* -------------------------------------------------------------------------- */

startBtn.addEventListener("click", startSession);

nextBtn.addEventListener("click", nextOrFinish);

stopBtn.addEventListener("click", () => {
  abortSession("Session stopped. Current incomplete stimulus was not saved.");
});


// Show a clean initial state when the script loads.
showReadyUi();
