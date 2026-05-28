/**
 * Browser-side recording interface for the Mandarin Tone Recorder.
 *
 * This file owns the subject-facing interaction:
 *
 *   Start -> request microphone access, show first stimulus, start recording
 *   Next  -> save current stimulus segment and advance
 *   Timeout -> discard current segment and ask the subject to try again
 *   Try Again -> rerecord the same stimulus
 *   Stop Session -> abort the session without saving the current segment
 */

const stimuli = window.MTR_STIMULI || [];
const maxDurationSec = window.MTR_MAX_DURATION_SEC || 3.0;
const maxDurationMs = maxDurationSec * 1000;

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
const sessionIdEl = document.getElementById("session-id");
const speakerTypeEl = document.getElementById("speaker-type");
const mandarinBackgroundEl = document.getElementById("mandarin-background");

// Browser microphone stream.
let stream = null;

// MediaRecorder instance for the current stimulus segment.
let recorder = null;

// Chosen browser-supported MIME type, for example "audio/webm;codecs=opus".
let mimeType = "";

// Current position in the stimulus list.
let currentIndex = -1;

// Browser timestamp for the beginning of the current stimulus segment.
let segmentStartMs = null;

// Count of successfully uploaded chunks in the current session.
let uploadCount = 0;

// Timer that enforces max duration for one stimulus recording.
let segmentTimeoutId = null;

// Current app mode. This keeps button behavior explicit.
let currentMode = "ready";
// possible values:
// "ready"
// "recording"
// "saving"
// "timed_out"
// "finished"
// "aborted"

// If true, the next MediaRecorder blob is discarded instead of uploaded.
// Used for timeout and abort behavior.
let discardNextBlob = false;

// help maintain state in spite of async.  This will be updated whenever
// recording is aborted, either through timeout or stop button
let sessionGeneration = 0;

/**
 * Display a status message for the subject/researcher.
 *
 * @param {string} message - Message to show in the status area.
 */
function setStatus(message) {
  statusEl.textContent = message;
}


/**
 * Display progress through the stimulus list.
 *
 * @param {string} message - Message to show in the progress area.
 */
function setProgress(message) {
  progressEl.textContent = message;
}


/**
 * Pick the best audio MIME type supported by this browser.
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
 * Get the currently displayed stimulus object.
 *
 * @returns {Object | undefined} The current stimulus, or undefined if no
 *   session has started.
 */
function currentStimulus() {
  return stimuli[currentIndex];
}


/**
 * Choose the main display text for a stimulus.
 *
 * @param {Object} stimulus - Stimulus row object.
 * @returns {string} Text to display in the large stimulus area.
 */
function stimulusDisplayText(stimulus) {
  if (!stimulus) {
    return "";
  }

  const pinyin = stimulus.pinyin || "";
  const ascii = stimulus.ascii || "";
  const tone = stimulus.tone || "";

  return pinyin || `${ascii}${tone}` || stimulus.stimulus_id || "";
}


/**
 * Render the current stimulus and associated details.
 */
function showCurrentStimulus() {
  const stim = currentStimulus();

  stimulusEl.textContent = stimulusDisplayText(stim);

  const parts = [];

  if (stim.ascii || stim.tone) {
    parts.push(`tone-number: ${stim.ascii || ""}${stim.tone || ""}`);
  }

  if (stim.ipa) {
    parts.push(`IPA: /${stim.ipa}/`);
  }

  if (stim.is_attested !== undefined && stim.is_attested !== "") {
    parts.push(`attested: ${stim.is_attested}`);
  }

  detailsEl.textContent = parts.join("   ·   ");

  setProgress(`Stimulus ${currentIndex + 1} of ${stimuli.length}`);

  nextBtn.textContent = currentIndex === stimuli.length - 1 ? "Finish" : "Next";
}


/**
 * Read participant/session metadata from the form.
 *
 * @returns {Object} Metadata values from the form.
 */
function getMetadata() {
  return {
    participantId: participantIdEl.value || "anonymous",
    sessionId: sessionIdEl.value || "default_session",
    speakerType: speakerTypeEl.value || "",
    mandarinBackground: mandarinBackgroundEl.value || ""
  };
}


/**
 * Upload one audio blob to the backend for the given stimulus.
 *
 * @param {Blob} blob - Audio data produced by MediaRecorder.
 * @param {Object} stim - Stimulus object associated with this audio.
 * @param {number} indexForFile - One-based stimulus index within the session.
 * @param {number} startedAtMs - Browser timestamp when segment began.
 * @param {number} endedAtMs - Browser timestamp when segment ended.
 * @returns {Promise<Object>} JSON response from the backend.
 */
async function uploadBlobForStimulus(blob, stim, indexForFile, startedAtMs, endedAtMs) {
  const metadata = getMetadata();
  const form = new FormData();

  form.append("file", blob, `chunk_${indexForFile}.webm`);
  form.append("participant_id", metadata.participantId);
  form.append("session_id", metadata.sessionId);
  form.append("speaker_type", metadata.speakerType);
  form.append("mandarin_background", metadata.mandarinBackground);

  form.append("stimulus_index", String(indexForFile));
  form.append("stimulus_id", String(stim.stimulus_id));
  form.append("started_at_ms", String(startedAtMs));
  form.append("ended_at_ms", String(endedAtMs));
  form.append("mime_type", mimeType || blob.type || "application/octet-stream");

  const response = await fetch("/api/recordings/chunk", {
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
 * Disable participant/session form inputs during recording.
 */
function disableMetadataInputs() {
  participantIdEl.disabled = true;
  sessionIdEl.disabled = true;
  speakerTypeEl.disabled = true;
  mandarinBackgroundEl.disabled = true;
}


/**
 * Re-enable participant/session form inputs after a session finishes or aborts.
 */
function enableMetadataInputs() {
  participantIdEl.disabled = false;
  sessionIdEl.disabled = false;
  speakerTypeEl.disabled = false;
  mandarinBackgroundEl.disabled = false;
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
 * This is used both for the initial recording and for retrying a timed-out
 * stimulus.
 */
function startRecordingCurrentStimulus() {
  discardNextBlob = false;
  segmentStartMs = Date.now();
  currentMode = "recording";

  const options = mimeType ? { mimeType } : undefined;

  // bind recorder to current sessionGeneration
  const recorderGeneration = sessionGeneration;
  recorder = new MediaRecorder(stream, options);
  recorder.ondataavailable = (event) => {
    handleDataAvailable(event, recorderGeneration);
  };

  recorder.onstop = () => {
    // Do not stop the microphone stream here. We often stop the recorder only
    // to end one timed-out segment and then rerecord the same stimulus.
  };

  recorder.start();
  startSegmentTimer();

  nextBtn.disabled = false;
  stopBtn.disabled = false;

  nextBtn.textContent = currentIndex === stimuli.length - 1 ? "Finish" : "Next";
}


/**
 * Handle per-stimulus timeout.
 *
 * The too-long recording is deliberately discarded. The same stimulus stays on
 * screen, and the user clicks Try Again when ready.
 */
function handleSegmentTimeout() {
  if (currentMode !== "recording") {
    return;
  }

  clearSegmentTimer();

  currentMode = "timed_out";
  discardNextBlob = true;

  if (recorder && recorder.state === "recording") {
    recorder.stop();
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


/**
 * Start a new recording session.
 *
 * This requests microphone permission, initializes session state, shows the
 * first stimulus, and starts recording immediately.
 */
async function startSession() {
  if (!stimuli.length) {
    setStatus("No stimuli were loaded.");
    return;
  }

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

  sessionGeneration += 1;

  mimeType = chooseMimeType();
  currentIndex = 0;
  uploadCount = 0;
  currentMode = "recording";
  discardNextBlob = false;

  disableMetadataInputs();

  startBtn.classList.add("hidden");
  nextBtn.classList.remove("hidden");
  stopBtn.classList.remove("hidden");

  showCurrentStimulus();
  startRecordingCurrentStimulus();

  setStatus(`Recording. Maximum duration per item: ${maxDurationSec.toFixed(1)} seconds.`);
}


/**
 * Handle an audio blob produced by MediaRecorder.
 *
 * Normal path:
 *   requestData -> blob -> upload -> advance
 *
 * Timeout/abort path:
 *   stop -> blob -> discard
 *
 * @param {BlobEvent} event - MediaRecorder event containing the audio blob.
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

  const stim = currentStimulus();
  const indexForFile = currentIndex + 1;
  const startedAtMs = segmentStartMs;
  const endedAtMs = Date.now();

  const blob = new Blob([event.data], {
    type: mimeType || event.data.type || "audio/webm"
  });

  try {
    await uploadBlobForStimulus(
      blob,
      stim,
      indexForFile,
      startedAtMs,
      endedAtMs
    );

    uploadCount += 1;
    setStatus(`Saved ${uploadCount} recording(s).`);

    const wasFinalStimulus = currentIndex === stimuli.length - 1;

    if (wasFinalStimulus) {
      finishSession();
      return;
    }

    currentIndex += 1;
    showCurrentStimulus();
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
    setProgress(`Stimulus ${currentIndex + 1} of ${stimuli.length}`);
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

  if (currentIndex === stimuli.length - 1) {
    setProgress("Saving final recording...");
  } else {
    setProgress("Saving and advancing...");
  }

  recorder.requestData();
}


/**
 * Finish the current recording session normally.
 */
function finishSession() {
  currentMode = "finished";
  clearSegmentTimer();

  if (recorder && recorder.state === "recording") {
    recorder.stop();
  }

  if (stream) {
    stream.getTracks().forEach((track) => track.stop());
    stream = null;
  }

  stimulusEl.textContent = "Done";
  detailsEl.textContent = "";
  setProgress("Session complete.");
  setStatus(`Saved ${uploadCount} chunks.`);

  nextBtn.classList.add("hidden");
  stopBtn.classList.add("hidden");

  startBtn.textContent = "Start Again";
  startBtn.disabled = false;
  startBtn.classList.remove("hidden");

  enableMetadataInputs();
}


/**
 * Abort the current session without saving the current unfinished segment.
 *
 * Already-saved previous stimuli remain saved. The current in-progress segment
 * is discarded.
 *
 * @param {string} message - Message to show after aborting.
 */
function abortSession(message) {
  sessionGeneration += 1;

  currentMode = "aborted";
  clearSegmentTimer();

  discardNextBlob = true;

  if (recorder && recorder.state === "recording") {
    recorder.stop();
  }

  if (stream) {
    stream.getTracks().forEach((track) => track.stop());
    stream = null;
  }

  currentIndex = -1;
  stimulusEl.textContent = "Stopped";
  detailsEl.textContent = "";
  setProgress("Session stopped.");
  setStatus(message || "Session stopped. The current stimulus was not saved. Recordings from previous stimuli remain saved");

  nextBtn.classList.add("hidden");
  stopBtn.classList.add("hidden");

  startBtn.textContent = "Start Again";
  startBtn.disabled = false;
  startBtn.classList.remove("hidden");

  enableMetadataInputs();
}


// Wire the visible buttons to the recording workflow.
startBtn.addEventListener("click", startSession);
nextBtn.addEventListener("click", nextOrFinish);
stopBtn.addEventListener("click", () => {
  abortSession("Session stopped. Current incomplete stimulus was not saved.");
});
