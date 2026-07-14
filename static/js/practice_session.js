"use strict";

const practiceRoot = document.querySelector("[data-practice-session]");

if (practiceRoot) {
  const timer = practiceRoot.querySelector("[data-practice-timer]");
  const startedAt = Date.now();

  function renderElapsed() {
    const elapsedSeconds = Math.floor((Date.now() - startedAt) / 1000);
    const minutes = String(Math.floor(elapsedSeconds / 60)).padStart(2, "0");
    const seconds = String(elapsedSeconds % 60).padStart(2, "0");
    timer.textContent = `${minutes}:${seconds}`;
  }

  renderElapsed();
  window.setInterval(renderElapsed, 1000);
}
