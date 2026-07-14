"use strict";

const practiceRoot = document.querySelector("[data-practice-session]");

if (practiceRoot) {
  const timer = practiceRoot.querySelector("[data-practice-timer]");
  const nextForm = practiceRoot.querySelector("[data-next-form]");
  const responseTimeInput = practiceRoot.querySelector("[data-response-time-ms]");
  const pinyin = practiceRoot.querySelector("[data-sentence-pinyin]");
  const pinyinButton = practiceRoot.querySelector('[data-action="show-pinyin"]');
  const status = practiceRoot.querySelector("[data-practice-status]");
  const startedAt = Date.parse(practiceRoot.dataset.attemptStartedAt || "") || Date.now();

  function csrfToken() {
    const match = document.cookie.match(/(?:^|; )csrftoken=([^;]+)/);
    return match ? decodeURIComponent(match[1]) : "";
  }

  function elapsedMilliseconds() {
    return Math.max(0, Date.now() - startedAt);
  }

  function renderElapsed() {
    const elapsedSeconds = Math.floor(elapsedMilliseconds() / 1000);
    const minutes = String(Math.floor(elapsedSeconds / 60)).padStart(2, "0");
    const seconds = String(elapsedSeconds % 60).padStart(2, "0");
    timer.textContent = `${minutes}:${seconds}`;
  }

  if (timer) {
    renderElapsed();
    window.setInterval(renderElapsed, 1000);
  }

  if (nextForm && responseTimeInput) {
    nextForm.addEventListener("submit", () => {
      responseTimeInput.value = String(Math.round(elapsedMilliseconds()));
    });
  }

  if (pinyinButton && pinyin) {
    pinyinButton.addEventListener("click", async () => {
      pinyin.classList.remove("is-hidden");
      pinyinButton.disabled = true;
      pinyinButton.textContent = "Sentence pinyin shown";

      try {
        const body = new FormData();
        body.append("revealed_at_ms", String(Math.round(elapsedMilliseconds())));
        const response = await fetch(practiceRoot.dataset.sentencePinyinUrl, {
          method: "POST",
          headers: { "X-CSRFToken": csrfToken() },
          body,
        });
        if (!response.ok) {
          throw new Error("Could not record pinyin reveal.");
        }
      } catch (error) {
        if (status) {
          status.textContent = error.message;
        }
      }
    });
  }

  practiceRoot.addEventListener("click", async (event) => {
    const button = event.target.closest('[data-action="show-character-pinyin"]');
    if (!button) return;

    const pinyinElement = button.querySelector("[data-character-pinyin]");
    if (pinyinElement) {
      pinyinElement.classList.remove("is-hidden");
    }
    button.disabled = true;

    try {
      const body = new FormData();
      body.append("character_index", button.dataset.characterIndex);
      body.append("revealed_at_ms", String(Math.round(elapsedMilliseconds())));
      const response = await fetch(practiceRoot.dataset.characterPinyinUrl, {
        method: "POST",
        headers: { "X-CSRFToken": csrfToken() },
        body,
      });
      if (!response.ok) {
        throw new Error("Could not record character reveal.");
      }
    } catch (error) {
      if (status) {
        status.textContent = error.message;
      }
    }
  });
}
