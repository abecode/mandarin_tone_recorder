/**
 * Browser-side recording interface for the Mandarin Tone Recorder.
 *
 * The browser keeps only the current stimulus and visible screen state. The
 * server owns session creation, attempt persistence, and next-stimulus choice.
 */


/* -------------------------------------------------------------------------- */
/* Configuration                                                              */
/* -------------------------------------------------------------------------- */

const maxDurationSec = window.MTR_MAX_DURATION_SEC || 7.0;
const maxDurationMs = maxDurationSec * 1000;
const defaultSessionTargetDurationSec =
  window.MTR_DEFAULT_SESSION_TARGET_DURATION_SEC || 600;


/* -------------------------------------------------------------------------- */
/* DOM elements                                                               */
/* -------------------------------------------------------------------------- */

const screens = {
  setup: document.getElementById("setup-screen"),
  recording: document.getElementById("recording-screen"),
  ready_to_retry: document.getElementById("ready-to-retry-screen"),
  target_reached: document.getElementById("target-reached-screen"),
  finished: document.getElementById("finished-screen"),
  aborted: document.getElementById("aborted-screen")
};

const setupStatusEl = document.getElementById("setup-status");
const stimulusEl = document.getElementById("stimulus");
const detailsEl = document.getElementById("stimulus-details");
const progressEl = document.getElementById("progress");
const statusEl = document.getElementById("status");

const retryStimulusEl = document.getElementById("retry-stimulus");
const retryDetailsEl = document.getElementById("retry-details");
const retryMessageEl = document.getElementById("retry-message");
const targetStimulusEl = document.getElementById("target-stimulus");
const targetDetailsEl = document.getElementById("target-details");
const targetMessageEl = document.getElementById("target-message");
const finishedMessageEl = document.getElementById("finished-message");
const abortedMessageEl = document.getElementById("aborted-message");

const startBtn = document.getElementById("start-btn");
const nextBtn = document.getElementById("next-btn");
const redoBtn = document.getElementById("redo-btn");
const stopBtn = document.getElementById("stop-btn");
const retryBtn = document.getElementById("retry-btn");
const retryStopBtn = document.getElementById("retry-stop-btn");
const continueBtn = document.getElementById("continue-btn");
const finishBtn = document.getElementById("finish-btn");
const finishedStartAgainBtn = document.getElementById("finished-start-again-btn");
const abortedStartAgainBtn = document.getElementById("aborted-start-again-btn");

const participantIdEl = document.getElementById("participant-id");
const speakerTypeEl = document.getElementById("speaker-type");
const mandarinBackgroundEl = document.getElementById("mandarin-background");
const experimentConditionEl = document.getElementById("experiment-condition");
const targetDurationSecEl = document.getElementById("target-duration-sec");


/* -------------------------------------------------------------------------- */
/* State                                                                      */
/* -------------------------------------------------------------------------- */

let stream = null;
let recorder = null;
let mimeType = "";
let segmentTimeoutId = null;
let sessionGeneration = 0;
let discardNextBlob = false;
let segmentStartMs = null;
let saveEndedAtMs = null;

let sessionCode = null;
let currentStimulusData = null;
let currentIndex = 0;
let uploadCount = 0;
let screenState = "setup";


/* -------------------------------------------------------------------------- */
/* Screen and display helpers                                                 */
/* -------------------------------------------------------------------------- */

function setScreen(nextScreen) {
  screenState = nextScreen;

  for (const [name, element] of Object.entries(screens)) {
    element.classList.toggle("hidden", name !== nextScreen);
  }
}

function setSetupStatus(message) {
  setupStatusEl.textContent = message;
}

function setRecordingStatus(message) {
  statusEl.textContent = message;
}

function setProgress(message) {
  progressEl.textContent = message;
}

function stimulusDetails(stimulus) {
  if (!stimulus) {
    return "";
  }

  const parts = [];

  if (stimulus.target_tone !== null && stimulus.target_tone !== undefined) {
    parts.push(`tone: ${stimulus.target_tone}`);
  }

  if (stimulus.initial || stimulus.rhyme) {
    const initial = stimulus.initial || "none";
    const rhyme = stimulus.rhyme || "";
    parts.push(`initial/rhyme: ${initial} + ${rhyme}`);
  }

  if (stimulus.ipa_base) {
    parts.push(`IPA: /${stimulus.ipa_base}/`);
  }

  if (stimulus.is_attested !== undefined) {
    parts.push(`attested: ${stimulus.is_attested}`);
  }

  return parts.join("   -   ");
}

function renderStimulus(stimulus, stimulusTarget, detailsTarget) {
  stimulusTarget.textContent = stimulus ? stimulus.display_text || "" : "Ready";
  detailsTarget.textContent = stimulusDetails(stimulus);
}

function showRecordingScreen(message) {
  renderStimulus(currentStimulusData, stimulusEl, detailsEl);
  setProgress(`Stimulus ${currentIndex}`);
  setRecordingStatus(message || "");
  setRecordingControlsDisabled(false);
  setScreen("recording");
}

function showReadyToRetryScreen(message) {
  renderStimulus(currentStimulusData, retryStimulusEl, retryDetailsEl);
  retryMessageEl.textContent = message;
  retryBtn.disabled = false;
  retryStopBtn.disabled = false;
  setScreen("ready_to_retry");
}

function showTargetReachedScreen(message) {
  renderStimulus(currentStimulusData, targetStimulusEl, targetDetailsEl);
  targetMessageEl.textContent = message || "Target time reached.";
  continueBtn.disabled = false;
  finishBtn.disabled = false;
  setScreen("target_reached");
}

function showFinishedScreen(message) {
  finishedMessageEl.textContent = message || `Saved ${uploadCount} recording(s).`;
  setScreen("finished");
}

function showAbortedScreen(message) {
  abortedMessageEl.textContent =
    message || "Session stopped. Current incomplete stimulus was not saved.";
  setScreen("aborted");
}

function setRecordingControlsDisabled(disabled) {
  nextBtn.disabled = disabled;
  redoBtn.disabled = disabled;
  stopBtn.disabled = disabled;
}

function resetClientSessionState() {
  sessionCode = null;
  currentStimulusData = null;
  currentIndex = 0;
  uploadCount = 0;
  segmentStartMs = null;
  saveEndedAtMs = null;
  discardNextBlob = false;
  recorder = null;
}


/* -------------------------------------------------------------------------- */
/* MediaRecorder helpers                                                      */
/* -------------------------------------------------------------------------- */

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

function clearSegmentTimer() {
  if (segmentTimeoutId !== null) {
    clearTimeout(segmentTimeoutId);
    segmentTimeoutId = null;
  }
}

function startSegmentTimer() {
  clearSegmentTimer();
  segmentTimeoutId = setTimeout(() => {
    handleSegmentTimeout();
  }, maxDurationMs);
}

function stopRecorderForDiscard() {
  discardNextBlob = true;

  const recorderToStop = recorder;
  recorder = null;

  if (recorderToStop && recorderToStop.state === "recording") {
    recorderToStop.stop();
  }
}

function stopCurrentRecorderWithoutUpload() {
  if (!recorder || recorder.state !== "recording") {
    recorder = null;
    return;
  }

  stopRecorderForDiscard();
}

function stopMicrophoneStream() {
  if (stream) {
    stream.getTracks().forEach((track) => track.stop());
    stream = null;
  }
}

function startRecordingCurrentStimulus() {
  if (!stream) {
    setRecordingStatus("Microphone stream is not available.");
    return;
  }

  if (!currentStimulusData) {
    setRecordingStatus("No current stimulus is available.");
    return;
  }

  discardNextBlob = false;
  saveEndedAtMs = null;
  segmentStartMs = Date.now();
  const recorderGeneration = sessionGeneration;
  const options = mimeType ? { mimeType } : undefined;

  recorder = new MediaRecorder(stream, options);
  recorder.ondataavailable = (event) => {
    handleDataAvailable(event, recorderGeneration);
  };
  recorder.start();

  startSegmentTimer();
  showRecordingScreen(
    `Recording. Maximum duration per item: ${maxDurationSec.toFixed(1)} seconds.`
  );
}


/* -------------------------------------------------------------------------- */
/* Server API helpers                                                         */
/* -------------------------------------------------------------------------- */

async function createSessionOnServer() {
  const participantCode = participantIdEl.value || "anonymous";
  const speakerType = speakerTypeEl.value || "learner";
  const mandarinBackground = mandarinBackgroundEl.value || "";
  const experimentCondition = experimentConditionEl.value || "tone_bearing";
  const targetDurationSec =
    Number(targetDurationSecEl.value) || defaultSessionTargetDurationSec;

  const response = await fetch("/api/sessions", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
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

async function recordTimeoutOnServer(durationSec) {
  return await recordNonAudioAttemptOnServer("timeouts", durationSec);
}

async function recordSpeakerRejectedOnServer(durationSec) {
  return await recordNonAudioAttemptOnServer("speaker-rejections", durationSec);
}

async function recordNonAudioAttemptOnServer(endpoint, durationSec) {
  if (!sessionCode || !currentStimulusData) {
    return null;
  }

  const response = await fetch(`/api/sessions/${sessionCode}/${endpoint}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      stimulus_id: currentStimulusData.stimulus_id,
      stimulus_index: currentIndex,
      duration_sec: durationSec
    })
  });

  if (!response.ok) {
    const text = await response.text();
    throw new Error(`Could not record attempt event: ${response.status} ${text}`);
  }

  return await response.json();
}

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

async function startSession() {
  if (!window.isSecureContext) {
    setSetupStatus("Microphone access requires localhost or HTTPS.");
    return;
  }

  if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
    setSetupStatus("This browser does not expose microphone access here.");
    return;
  }

  if (!window.MediaRecorder) {
    setSetupStatus("This browser does not support MediaRecorder.");
    return;
  }

  startBtn.disabled = true;
  setSetupStatus("Requesting microphone permission...");

  try {
    stream = await navigator.mediaDevices.getUserMedia({ audio: true });
  } catch (err) {
    startBtn.disabled = false;
    setSetupStatus(`Could not access microphone: ${err.message}`);
    return;
  }

  setSetupStatus("Creating session...");

  try {
    const sessionInfo = await createSessionOnServer();
    sessionGeneration += 1;
    sessionCode = sessionInfo.session_code;
    currentStimulusData = sessionInfo.first_stimulus;
    currentIndex = 1;
    uploadCount = 0;
    mimeType = chooseMimeType();
    setSetupStatus("");
    startRecordingCurrentStimulus();
  } catch (err) {
    stopMicrophoneStream();
    startBtn.disabled = false;
    setSetupStatus(err.message);
  }
}

async function finishSession(message) {
  clearSegmentTimer();
  sessionGeneration += 1;
  stopRecorderForDiscard();
  stopMicrophoneStream();

  try {
    await finishSessionOnServer();
  } catch (err) {
    console.error(err);
  }

  showFinishedScreen(message || `Saved ${uploadCount} recording(s).`);
  resetClientSessionState();
}

async function abortSession(message) {
  clearSegmentTimer();
  sessionGeneration += 1;
  stopRecorderForDiscard();
  stopMicrophoneStream();

  try {
    await abortSessionOnServer();
  } catch (err) {
    console.error(err);
  }

  showAbortedScreen(message);
  resetClientSessionState();
}

function returnToSetup() {
  startBtn.disabled = false;
  setSetupStatus("");
  setScreen("setup");
}


/* -------------------------------------------------------------------------- */
/* Attempt lifecycle                                                          */
/* -------------------------------------------------------------------------- */

async function handleDataAvailable(event, recorderGeneration) {
  if (recorderGeneration !== sessionGeneration) {
    return;
  }

  if (discardNextBlob) {
    discardNextBlob = false;
    return;
  }

  if (screenState !== "recording" || !event.data || event.data.size === 0) {
    setRecordingControlsDisabled(false);
    return;
  }

  const startedAtMs = segmentStartMs;
  const endedAtMs = saveEndedAtMs || Date.now();
  const blob = new Blob([event.data], {
    type: mimeType || event.data.type || "audio/webm"
  });

  recorder = null;

  try {
    const result = await uploadAcceptedAttempt(blob, startedAtMs, endedAtMs);
    uploadCount += 1;

    if (result.session_done) {
      stopCurrentRecorderWithoutUpload();
      await finishSession(result.message || `Saved ${uploadCount} recording(s).`);
      return;
    }

    if (!result.next_stimulus) {
      stopCurrentRecorderWithoutUpload();
      await finishSession("No next stimulus was returned.");
      return;
    }

    currentStimulusData = result.next_stimulus;
    currentIndex += 1;

    if (result.target_duration_reached) {
      stopCurrentRecorderWithoutUpload();
      showTargetReachedScreen(
        "Target time reached. Choose whether to continue with the next item."
      );
      return;
    }

    startRecordingCurrentStimulus();
  } catch (err) {
    console.error(err);
    setRecordingStatus(`Save failed: ${err.message}`);
    setRecordingControlsDisabled(false);
    startSegmentTimer();
  }
}

function acceptCurrentStimulus() {
  if (screenState !== "recording") {
    return;
  }

  if (!recorder || recorder.state !== "recording") {
    setRecordingStatus("Recorder is not active.");
    return;
  }

  clearSegmentTimer();
  saveEndedAtMs = Date.now();
  setProgress("Saving and advancing...");
  setRecordingControlsDisabled(true);
  recorder.requestData();
}

async function rejectCurrentStimulus() {
  if (screenState !== "recording") {
    return;
  }

  clearSegmentTimer();
  setRecordingControlsDisabled(true);

  const durationSec = segmentStartMs
    ? Math.max(0, (Date.now() - segmentStartMs) / 1000.0)
    : 0;

  stopRecorderForDiscard();

  try {
    const result = await recordSpeakerRejectedOnServer(durationSec);
    if (result && result.next_stimulus) {
      currentStimulusData = result.next_stimulus;
    }
    showReadyToRetryScreen("Redo saved. Try again when ready.");
  } catch (err) {
    console.error(err);
    showReadyToRetryScreen(`Redo was not saved: ${err.message}`);
  }
}

async function handleSegmentTimeout() {
  if (screenState !== "recording") {
    return;
  }

  clearSegmentTimer();
  setRecordingControlsDisabled(true);
  stopRecorderForDiscard();

  try {
    const result = await recordTimeoutOnServer(maxDurationSec);
    if (result && result.next_stimulus) {
      currentStimulusData = result.next_stimulus;
    }
    showReadyToRetryScreen(
      `This recording exceeded ${maxDurationSec.toFixed(1)} seconds. Try again when ready.`
    );
  } catch (err) {
    console.error(err);
    showReadyToRetryScreen(
      `Timed out, but the timeout was not saved: ${err.message}`
    );
  }
}


/* -------------------------------------------------------------------------- */
/* Event listeners                                                            */
/* -------------------------------------------------------------------------- */

startBtn.addEventListener("click", startSession);
nextBtn.addEventListener("click", acceptCurrentStimulus);
redoBtn.addEventListener("click", rejectCurrentStimulus);
stopBtn.addEventListener("click", () => {
  abortSession("Session stopped before the allotted time.");
});

retryBtn.addEventListener("click", () => {
  retryBtn.disabled = true;
  retryStopBtn.disabled = true;
  startRecordingCurrentStimulus();
});

retryStopBtn.addEventListener("click", () => {
  abortSession("Session stopped before the allotted time.");
});

continueBtn.addEventListener("click", () => {
  continueBtn.disabled = true;
  finishBtn.disabled = true;
  startRecordingCurrentStimulus();
});

finishBtn.addEventListener("click", () => {
  continueBtn.disabled = true;
  finishBtn.disabled = true;
  finishSession(`Session complete. Saved ${uploadCount} recording(s).`);
});

finishedStartAgainBtn.addEventListener("click", returnToSetup);
abortedStartAgainBtn.addEventListener("click", returnToSetup);

setScreen("setup");
