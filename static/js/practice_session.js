"use strict";

const practiceRoot = document.querySelector("[data-practice-session]");

if (practiceRoot) {
  const timer = practiceRoot.querySelector("[data-practice-timer]");
  const nextForm = practiceRoot.querySelector("[data-next-form]");
  const responseTimeInput = practiceRoot.querySelector("[data-response-time-ms]");
  const pinyin = practiceRoot.querySelector("[data-sentence-pinyin]");
  const pinyinButton = practiceRoot.querySelector('[data-action="show-pinyin"]');
  const characterPrompt = practiceRoot.querySelector("[data-character-prompt]");
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

  function caretOffsetFromPoint(x, y) {
    if (document.caretPositionFromPoint) {
      const position = document.caretPositionFromPoint(x, y);
      if (position && position.offsetNode === characterPrompt.firstChild) {
        return position.offset;
      }
    }

    if (document.caretRangeFromPoint) {
      const range = document.caretRangeFromPoint(x, y);
      if (range && range.startContainer === characterPrompt.firstChild) {
        return range.startOffset;
      }
    }

    return null;
  }

  function characterIndexFromClick(event) {
    if (!characterPrompt || !characterPrompt.firstChild) return null;

    const offset = caretOffsetFromPoint(event.clientX, event.clientY);
    if (offset === null) return null;

    const promptText = characterPrompt.textContent || "";
    const index = Math.min(Math.max(offset, 0), promptText.length - 1);
    if (index < 0) return null;
    if (!practiceRoot.querySelector(`[data-character-pinyin-slot="${index}"]`)) {
      return null;
    }
    return index;
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
      pinyin.textContent = pinyin.dataset.fullPinyin || pinyin.textContent;
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
    if (!event.target.closest("[data-character-prompt]")) return;

    const characterIndex = characterIndexFromClick(event);
    if (characterIndex === null) return;

    const pinyinSlot = practiceRoot.querySelector(
      `[data-character-pinyin-slot="${characterIndex}"]`,
    );
    if (!pinyinSlot) return;

    pinyinSlot.textContent = pinyinSlot.dataset.characterPinyin || "";
    pinyinSlot.classList.add("is-revealed");

    try {
      const body = new FormData();
      body.append("character_index", String(characterIndex));
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
