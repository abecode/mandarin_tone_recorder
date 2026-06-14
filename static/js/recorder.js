"use strict";

const root = document.querySelector("[data-recorder]");
const configElement = document.getElementById("recorder-config");

if (root && configElement) {
  const config = JSON.parse(configElement.textContent);
  const screens = Object.fromEntries(
    [...root.querySelectorAll("[data-screen]")].map((element) => [
      element.dataset.screen,
      element,
    ]),
  );
  const elements = {
    stimulus: root.querySelector("[data-stimulus]"),
    details: root.querySelector("[data-details]"),
    index: root.querySelector("[data-index]"),
    retryStimulus: root.querySelector("[data-retry-stimulus]"),
    retryIndex: root.querySelector("[data-retry-index]"),
    retryMessage: root.querySelector("[data-retry-message]"),
    status: root.querySelector("[data-status]"),
    startStatus: root.querySelector("[data-start-status]"),
    targetStatus: root.querySelector("[data-target-status]"),
  };

  let stream = null;
  let recorder = null;
  let chunks = [];
  let segmentStartedAt = null;
  let segmentTimer = null;
  let currentStimulus = config.stimulus;
  let currentIndex = config.stimulus_index;
  let continuedAfterTarget = config.continued_after_target;
  let busy = false;

  function showScreen(name) {
    for (const [screenName, element] of Object.entries(screens)) {
      element.classList.toggle("is-hidden", screenName !== name);
    }
  }

  function csrfToken() {
    const match = document.cookie.match(/(?:^|; )csrftoken=([^;]+)/);
    return match ? decodeURIComponent(match[1]) : "";
  }

  async function post(url, options = {}) {
    const response = await fetch(url, {
      method: "POST",
      headers: {
        "X-CSRFToken": csrfToken(),
        ...(options.headers || {}),
      },
      body: options.body,
    });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) {
      throw new Error(payload.error || `Request failed with status ${response.status}.`);
    }
    return payload;
  }

  function endpoint(suffix) {
    return `/recordings/sessions/${config.session_id}/${suffix}`;
  }

  function renderStimulus() {
    const text = currentStimulus ? currentStimulus.display_text : "";
    elements.stimulus.textContent = text;
    elements.retryStimulus.textContent = text;
    elements.index.textContent = `Prompt ${currentIndex}`;
    elements.retryIndex.textContent = `Prompt ${currentIndex}`;

    const details = [];
    if (currentStimulus && currentStimulus.target_tone !== null) {
      details.push(`Tone ${currentStimulus.target_tone}`);
    }
    if (currentStimulus && currentStimulus.ipa_base) {
      details.push(`/${currentStimulus.ipa_base}/`);
    }
    elements.details.textContent = details.join("  ·  ");
  }

  function setControlsDisabled(disabled) {
    for (const button of screens.recording.querySelectorAll(
      '[data-action="next"], [data-action="redo"], [data-action="abort"]',
    )) {
      button.disabled = disabled;
    }
  }

  function setRetryControlsDisabled(disabled) {
    for (const button of screens.retry.querySelectorAll(
      '[data-action="try-again"], [data-action="abort"]',
    )) {
      button.disabled = disabled;
    }
  }

  function showRetryScreen(message) {
    elements.retryMessage.textContent = message;
    setRetryControlsDisabled(false);
    busy = false;
    showScreen("retry");
  }

  function clearTimer() {
    if (segmentTimer !== null) {
      window.clearTimeout(segmentTimer);
      segmentTimer = null;
    }
  }

  function stopMicrophone() {
    if (stream) {
      for (const track of stream.getTracks()) {
        track.stop();
      }
    }
    stream = null;
  }

  function supportedMimeType() {
    const options = [
      "audio/webm;codecs=opus",
      "audio/webm",
      "audio/ogg;codecs=opus",
      "audio/mp4",
    ];
    return options.find((type) => MediaRecorder.isTypeSupported(type)) || "";
  }

  async function ensureMicrophone() {
    if (stream && stream.active) {
      return;
    }
    if (!window.isSecureContext) {
      throw new Error("Microphone access requires HTTPS or localhost.");
    }
    if (!navigator.mediaDevices?.getUserMedia || !window.MediaRecorder) {
      throw new Error("This browser does not support microphone recording.");
    }
    stream = await navigator.mediaDevices.getUserMedia({ audio: true });
  }

  function discardRecorder() {
    clearTimer();
    if (recorder && recorder.state !== "inactive") {
      recorder.onstop = null;
      recorder.stop();
    }
    recorder = null;
    chunks = [];
  }

  async function startSegment() {
    await ensureMicrophone();
    chunks = [];
    const mimeType = supportedMimeType();
    recorder = new MediaRecorder(stream, mimeType ? { mimeType } : undefined);
    recorder.ondataavailable = (event) => {
      if (event.data.size > 0) {
        chunks.push(event.data);
      }
    };
    recorder.start();
    segmentStartedAt = Date.now();
    segmentTimer = window.setTimeout(handleTimeout, config.max_duration_seconds * 1000);
    renderStimulus();
    elements.status.textContent = continuedAfterTarget
      ? "Recording. Thank you for completing your session. You may stop the session at any time."
      : "Recording";
    setControlsDisabled(false);
    showScreen("recording");
  }

  function stopAndCollect() {
    return new Promise((resolve, reject) => {
      if (!recorder || recorder.state === "inactive") {
        reject(new Error("Recorder is not active."));
        return;
      }
      const activeRecorder = recorder;
      activeRecorder.onerror = () => reject(new Error("The browser could not finish the recording."));
      activeRecorder.onstop = () => {
        const blob = new Blob(chunks, {
          type: activeRecorder.mimeType || "audio/webm",
        });
        recorder = null;
        chunks = [];
        resolve(blob);
      };
      activeRecorder.stop();
    });
  }

  async function acceptCurrent() {
    if (busy) return;
    busy = true;
    clearTimer();
    setControlsDisabled(true);
    elements.status.textContent = "Finishing recording...";

    try {
      await new Promise((resolve) =>
        window.setTimeout(resolve, config.post_click_buffer_ms),
      );
      const endedAt = Date.now();
      const blob = await stopAndCollect();
      elements.status.textContent = "Saving...";

      const form = new FormData();
      form.append("audio", blob, `prompt-${currentIndex}.webm`);
      form.append("stimulus_id", currentStimulus.stable_id);
      form.append("duration_seconds", String((endedAt - segmentStartedAt) / 1000));
      form.append("started_at_ms", String(segmentStartedAt));
      form.append("ended_at_ms", String(endedAt));
      form.append("mime_type", blob.type);

      const result = await post(endpoint("attempts/accepted/"), { body: form });
      if (result.session_done) {
        stopMicrophone();
        showScreen("finished");
        return;
      }

      currentStimulus = result.next_stimulus;
      currentIndex = result.next_index;
      renderStimulus();

      if (result.target_reached) {
        stopMicrophone();
        showScreen("target");
        return;
      }
      await startSegment();
    } catch (error) {
      elements.status.textContent = error.message;
      setControlsDisabled(false);
    } finally {
      busy = false;
    }
  }

  async function recordRetry(status, message) {
    if (busy) return;
    busy = true;
    clearTimer();
    setControlsDisabled(true);
    const duration = segmentStartedAt
      ? Math.max(0, (Date.now() - segmentStartedAt) / 1000)
      : 0;
    discardRecorder();

    try {
      const result = await post(endpoint("attempts/retry/"), {
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          stimulus_id: currentStimulus.stable_id,
          status,
          duration_seconds: duration,
        }),
      });
      currentStimulus = result.next_stimulus;
      currentIndex = result.next_index;
      renderStimulus();
      showRetryScreen(message);
    } catch (error) {
      showRetryScreen(error.message);
    } finally {
      setRetryControlsDisabled(false);
      busy = false;
    }
  }

  async function handleTimeout() {
    await recordRetry(
      "timed_out",
      `This prompt exceeded ${config.max_duration_seconds} seconds. Try it again.`,
    );
  }

  async function stopSession() {
    if (busy) return;
    busy = true;
    discardRecorder();
    stopMicrophone();
    try {
      await post(endpoint("abort/"));
      showScreen("aborted");
    } catch (error) {
      elements.status.textContent = error.message;
      busy = false;
    }
  }

  async function finishSession() {
    if (busy) return;
    busy = true;
    stopMicrophone();
    try {
      await post(endpoint("finish/"));
      showScreen("finished");
    } catch (error) {
      elements.targetStatus.textContent = error.message;
      busy = false;
    }
  }

  async function continueSession() {
    if (busy) return;
    busy = true;
    try {
      await post(endpoint("continue/"));
      continuedAfterTarget = true;
      await startSegment();
    } catch (error) {
      elements.targetStatus.textContent = error.message;
    } finally {
      busy = false;
    }
  }

  root.addEventListener("click", async (event) => {
    const button = event.target.closest("[data-action]");
    if (!button) return;
    const action = button.dataset.action;
    if (action === "begin" || action === "try-again") {
      button.disabled = true;
      try {
        await startSegment();
      } catch (error) {
        const statusElement =
          action === "try-again" ? elements.retryMessage : elements.startStatus;
        statusElement.textContent = error.message;
      } finally {
        button.disabled = false;
      }
    } else if (action === "next") {
      await acceptCurrent();
    } else if (action === "redo") {
      await recordRetry("speaker_rejected", "Redo recorded. Try the prompt again.");
    } else if (action === "abort") {
      await stopSession();
    } else if (action === "continue") {
      await continueSession();
    } else if (action === "finish") {
      await finishSession();
    }
  });

  renderStimulus();
  showScreen(config.target_pending ? "target" : "start");
}
