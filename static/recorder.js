
/**
 * Browser-side recording interface for the Mandarin Tone Recorder.
 *
 * This file owns the subject-facing interaction:
 *
 *   Start -> request microphone access, show first stimulus, start recording
 *   Next  -> request the current audio blob, upload it, show next stimulus
 *   Finish -> upload final blob, stop recording
 *
 * The backend receives one uploaded audio chunk per stimulus.
 */

/**
 * Stimuli are injected by templates/recorder.html as window.MTR_STIMULI.
 *
 * Each stimulus is expected to have a stable `stimulus_id` and may also have
 * fields such as `pinyin`, `ascii`, `tone`, `ipa`, and `is_attested`.
 */
const stimuli = window.MTR_STIMULI || [];

// Main display elements.
const stimulusEl = document.getElementById("stimulus");
const detailsEl = document.getElementById("stimulus-details");
const progressEl = document.getElementById("progress");
const statusEl = document.getElementById("status");

// Recording controls.
const startBtn = document.getElementById("start-btn");
const nextBtn = document.getElementById("next-btn");

// Participant/session metadata fields.
const participantIdEl = document.getElementById("participant-id");
const sessionIdEl = document.getElementById("session-id");
const speakerTypeEl = document.getElementById("speaker-type");
const mandarinBackgroundEl = document.getElementById("mandarin-background");

// Browser microphone stream.
let stream = null;

// MediaRecorder instance for the current session.
let recorder = null;

// Chosen browser-supported MIME type, for example "audio/webm;codecs=opus".
let mimeType = "";

// Current position in the stimulus list.
let currentIndex = -1;

// Browser timestamp for the beginning of the current stimulus segment.
let segmentStartMs = null;

// True while waiting for MediaRecorder to produce/upload the current blob.
let waitingForBlob = false;

// Count of successfully uploaded chunks in the current session.
let uploadCount = 0;


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
 * Preference order:
 * 1. pinyin with tone marks, if present
 * 2. ascii + tone number, if present
 * 3. stimulus_id as a fallback
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
 *
 * This updates the large prompt, the smaller detail line, progress text, and
 * the Next/Finish button label.
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
 * These values are sent with every uploaded chunk so each audio file can be
 * traced back to the participant and session.
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
 * The backend endpoint writes the audio file, optionally converts it to WAV,
 * and appends one row to metadata.csv.
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
 *
 * This prevents accidental metadata changes halfway through a session.
 */
function disableMetadataInputs() {
  participantIdEl.disabled = true;
  sessionIdEl.disabled = true;
  speakerTypeEl.disabled = true;
  mandarinBackgroundEl.disabled = true;
}


/**
 * Re-enable participant/session form inputs after a session finishes.
 */
function enableMetadataInputs() {
  participantIdEl.disabled = false;
  sessionIdEl.disabled = false;
  speakerTypeEl.disabled = false;
  mandarinBackgroundEl.disabled = false;
}


/**
 * Start a new recording session.
 *
 * This requests microphone permission, creates a MediaRecorder, shows the first
 * stimulus, and begins recording. The first audio segment starts immediately
 * when the first stimulus appears.
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

  mimeType = chooseMimeType();
  currentIndex = 0;
  uploadCount = 0;
  waitingForBlob = false;
  segmentStartMs = Date.now();

  const options = mimeType ? { mimeType } : undefined;
  recorder = new MediaRecorder(stream, options);

  recorder.ondataavailable = handleDataAvailable;

  recorder.onstop = () => {
    if (stream) {
      stream.getTracks().forEach((track) => track.stop());
    }
  };

  recorder.start();

  disableMetadataInputs();

  startBtn.classList.add("hidden");
  nextBtn.classList.remove("hidden");
  nextBtn.disabled = false;

  showCurrentStimulus();
  setStatus("Recording.");
}


/**
 * Handle an audio blob produced by MediaRecorder.
 *
 * This function is called after recorder.requestData(). It uploads the blob for
 * the current stimulus. If this was not the final stimulus, it advances to the
 * next one and resets the segment start time.
 *
 * @param {BlobEvent} event - MediaRecorder event containing the audio blob.
 */
async function handleDataAvailable(event) {
  if (!event.data || event.data.size === 0) {
    waitingForBlob = false;
    nextBtn.disabled = false;
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
    segmentStartMs = Date.now();
    showCurrentStimulus();
  } catch (err) {
    console.error(err);
    setStatus(`Save failed: ${err.message}`);
  } finally {
    waitingForBlob = false;
    nextBtn.disabled = false;
  }
}


/**
 * Save the current stimulus segment and either advance or finish.
 *
 * MediaRecorder.requestData() asks the browser to emit all audio collected
 * since the previous requestData/start event. The recorder continues running,
 * so the user does not see a separate stop/start recording control.
 */
function nextOrFinish() {
  if (!recorder || recorder.state !== "recording") {
    setStatus("Recorder is not active.");
    return;
  }

  if (waitingForBlob) {
    return;
  }

  waitingForBlob = true;
  nextBtn.disabled = true;

  if (currentIndex === stimuli.length - 1) {
    setProgress("Saving final recording...");
  } else {
    setProgress("Saving and advancing...");
  }

  recorder.requestData();
}


/**
 * Finish the current recording session.
 *
 * This stops the microphone stream, restores the Start button, hides the Next
 * button, and re-enables the metadata form for another session.
 */
function finishSession() {
  if (recorder && recorder.state === "recording") {
    recorder.stop();
  }

  stimulusEl.textContent = "Done";
  detailsEl.textContent = "";
  setProgress("Session complete.");
  setStatus(`Saved ${uploadCount} chunks.`);

  nextBtn.classList.add("hidden");
  startBtn.textContent = "Start Again";
  startBtn.disabled = false;
  startBtn.classList.remove("hidden");

  enableMetadataInputs();
}


// Wire the two visible buttons to the recording workflow.
startBtn.addEventListener("click", startSession);
nextBtn.addEventListener("click", nextOrFinish);


