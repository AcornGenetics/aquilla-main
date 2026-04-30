const KEYBOARD_SELECTOR = ".onscreen-keyboard";
const INPUT_SELECTOR = "input[type='text'], input[type='password'], input[type='number'], input[type='search'], input[type='tel'], input[type='url'], textarea";
const KEY_DEBOUNCE_MS = 50;

const KEY_ROWS = [
  ["1", "2", "3", "4", "5", "6", "7", "8", "9", "0"],
  ["q", "w", "e", "r", "t", "y", "u", "i", "o", "p"],
  ["a", "s", "d", "f", "g", "h", "j", "k", "l"],
  ["z", "x", "c", "v", "b", "n", "m", ".", "-"],
];

let activeInput = null;
let keyboardPadding = 0;
let lastPhysicalKey = null;
let lastPhysicalKeyTime = 0;
let suppressMouseEvents = false;
let isUppercase = false;

function safeSetSelectionRange(input, start, end) {
  if (!input || typeof input.setSelectionRange !== "function") return;
  try { input.setSelectionRange(start, end); } catch (_) {}
}

function updateKeyboardSpacing(keyboard, isVisible) {
  if (!keyboard) return;
  if (isVisible) {
    const rect = keyboard.getBoundingClientRect();
    keyboardPadding = rect.height + 24;
    document.body.style.paddingBottom = `${keyboardPadding}px`;
    document.body.classList.add("keyboard-visible");
    return;
  }
  document.body.style.paddingBottom = "";
  document.body.classList.remove("keyboard-visible");
  keyboardPadding = 0;
}

function buildKeyboard() {
  if (document.querySelector(KEYBOARD_SELECTOR)) return;

  const keyboard = document.createElement("div");
  keyboard.className = "onscreen-keyboard";

  // Close button in its own bar above the keys
  const topBar = document.createElement("div");
  topBar.className = "keyboard-top-bar";
  const closeBtn = document.createElement("button");
  closeBtn.type = "button";
  closeBtn.className = "keyboard-close-btn";
  closeBtn.textContent = "✕";
  closeBtn.dataset.value = "close";
  topBar.appendChild(closeBtn);
  keyboard.appendChild(topBar);

  const handlePointerPress = (event) => {
    const key = event.target.closest("[data-value]");
    if (!key || !key.dataset.value) return;
    if (event.cancelable) event.preventDefault();
    handleKeyPress(key.dataset.value);
  };

  if (window.PointerEvent) {
    keyboard.addEventListener("pointerdown", handlePointerPress);
  } else {
    keyboard.addEventListener("mousedown", (event) => {
      if (!suppressMouseEvents) handlePointerPress(event);
    });
    keyboard.addEventListener("touchstart", (event) => {
      suppressMouseEvents = true;
      handlePointerPress(event);
      window.setTimeout(() => { suppressMouseEvents = false; }, 500);
    });
  }

  // Number row + Delete
  const row0 = document.createElement("div");
  row0.className = "keyboard-row";
  KEY_ROWS[0].forEach((key) => {
    const keyEl = document.createElement("button");
    keyEl.type = "button";
    keyEl.className = "keyboard-key";
    keyEl.textContent = key;
    keyEl.dataset.value = key;
    row0.appendChild(keyEl);
  });
  const deleteBtn = document.createElement("button");
  deleteBtn.type = "button";
  deleteBtn.className = "keyboard-key keyboard-key--delete";
  deleteBtn.textContent = "Delete";
  deleteBtn.dataset.value = "backspace";
  row0.appendChild(deleteBtn);
  keyboard.appendChild(row0);

  // Letter rows
  KEY_ROWS.slice(1).forEach((row, rowIndex) => {
    const rowEl = document.createElement("div");
    rowEl.className = "keyboard-row";
    if (rowIndex === 2) {
      const shiftBtn = document.createElement("button");
      shiftBtn.type = "button";
      shiftBtn.className = "keyboard-key keyboard-key--shift";
      shiftBtn.textContent = "Shift";
      shiftBtn.dataset.value = "shift";
      rowEl.appendChild(shiftBtn);
    }
    row.forEach((key) => {
      const keyEl = document.createElement("button");
      keyEl.type = "button";
      keyEl.className = "keyboard-key";
      keyEl.textContent = key;
      keyEl.dataset.value = key;
      rowEl.appendChild(keyEl);
    });
    keyboard.appendChild(rowEl);
  });

  // Action row: Clear | Space | ENTER
  const actionRow = document.createElement("div");
  actionRow.className = "keyboard-row keyboard-row--actions";

  const clearBtn = document.createElement("button");
  clearBtn.type = "button";
  clearBtn.className = "keyboard-key keyboard-key--clear";
  clearBtn.textContent = "Clear";
  clearBtn.dataset.value = "clear";

  const spaceBtn = document.createElement("button");
  spaceBtn.type = "button";
  spaceBtn.className = "keyboard-key keyboard-key--space";
  spaceBtn.textContent = "Space";
  spaceBtn.dataset.value = "space";

  const enterBtn = document.createElement("button");
  enterBtn.type = "button";
  enterBtn.className = "keyboard-key keyboard-key--enter";
  enterBtn.textContent = "ENTER";
  enterBtn.dataset.value = "enter";

  actionRow.appendChild(clearBtn);
  actionRow.appendChild(spaceBtn);
  actionRow.appendChild(enterBtn);
  keyboard.appendChild(actionRow);

  document.body.appendChild(keyboard);
  updateKeyboardCase();
}

function updateKeyboardCase() {
  const keyboard = document.querySelector(KEYBOARD_SELECTOR);
  if (!keyboard) return;
  keyboard.querySelectorAll(".keyboard-key").forEach((keyEl) => {
    const value = keyEl.dataset.value || "";
    if (/^[a-z]$/.test(value)) {
      keyEl.textContent = isUppercase ? value.toUpperCase() : value;
    }
    if (value === "shift") {
      keyEl.classList.toggle("is-active", isUppercase);
      keyEl.setAttribute("aria-pressed", isUppercase ? "true" : "false");
    }
  });
}

function updateInputValue(value, replace = false) {
  if (!activeInput) return;
  const input = activeInput;
  const fallbackPos = input.value.length;
  const start = Number.isInteger(input.selectionStart) ? input.selectionStart : fallbackPos;
  const end   = Number.isInteger(input.selectionEnd)   ? input.selectionEnd   : fallbackPos;
  const current = input.value || "";
  const nextValue = replace ? value : current.slice(0, start) + value + current.slice(end);
  input.value = nextValue;
  const nextPos = replace ? nextValue.length : start + value.length;
  safeSetSelectionRange(input, nextPos, nextPos);
  input.dispatchEvent(new Event("input", { bubbles: true }));
}

function handleKeyPress(value) {
  if (!activeInput) return;
  activeInput.focus();

  if (value === "shift") {
    isUppercase = !isUppercase;
    updateKeyboardCase();
    return;
  }

  const outputValue = isUppercase && /^[a-z]$/.test(value) ? value.toUpperCase() : value;

  if (value !== "backspace" && value !== "clear" && outputValue.length === 1) {
    const inputType = (activeInput.getAttribute("type") || "").toLowerCase();
    if (inputType === "number") {
      const current = activeInput.value || "";
      const candidate = current + outputValue;
      const valid = candidate === "" || candidate === "-" || candidate === "."
                    || !Number.isNaN(Number(candidate));
      if (!valid) return;
    }
  }

  switch (value) {
    case "space":
      updateInputValue(" ");
      return;
    case "backspace": {
      const input = activeInput;
      const start = input.selectionStart ?? input.value.length;
      const end   = input.selectionEnd   ?? input.value.length;
      if (start !== end) {
        const cur = input.value || "";
        input.value = cur.slice(0, start) + cur.slice(end);
        safeSetSelectionRange(input, start, start);
        input.dispatchEvent(new Event("input", { bubbles: true }));
        return;
      }
      if (start > 0) {
        const cur = input.value || "";
        input.value = cur.slice(0, start - 1) + cur.slice(end);
        const np = Math.max(start - 1, 0);
        safeSetSelectionRange(input, np, np);
        input.dispatchEvent(new Event("input", { bubbles: true }));
      }
      return;
    }
    case "clear":
      updateInputValue("", true);
      return;
    case "enter":
      if (activeInput.tagName === "TEXTAREA") {
        updateInputValue("\n");
      } else {
        activeInput.blur();
        hideKeyboard();
      }
      return;
    case "close":
      hideKeyboard();
      return;
    default:
      updateInputValue(outputValue);
  }
}

function showKeyboard(target) {
  if (!target || target.readOnly || target.disabled) return;
  activeInput = target;
  activeInput.focus();
  const length = activeInput.value?.length ?? 0;
  safeSetSelectionRange(activeInput, length, length);
  const keyboard = document.querySelector(KEYBOARD_SELECTOR);
  if (keyboard) {
    keyboard.classList.add("is-visible");
    requestAnimationFrame(() => {
      updateKeyboardSpacing(keyboard, true);
      if (typeof activeInput.scrollIntoView === "function") {
        activeInput.scrollIntoView({ behavior: "smooth", block: "center" });
      }
    });
  }
}

function hideKeyboard() {
  const keyboard = document.querySelector(KEYBOARD_SELECTOR);
  if (keyboard) {
    keyboard.classList.remove("is-visible");
    updateKeyboardSpacing(keyboard, false);
  }
  activeInput = null;
}

document.addEventListener("DOMContentLoaded", () => {
  buildKeyboard();

  const handleInputActivate = (event) => {
    const target = event.target;
    if (!(target instanceof HTMLElement)) return;
    if (target.closest(KEYBOARD_SELECTOR)) return;
    if (target.matches(INPUT_SELECTOR) && !target.classList.contains("keyboard-ignore")) {
      showKeyboard(target);
    }
  };

  document.addEventListener("pointerdown", handleInputActivate);
  document.addEventListener("touchstart", handleInputActivate);
  document.addEventListener("mousedown", handleInputActivate);
  document.addEventListener("click", handleInputActivate);

  document.addEventListener("keydown", (event) => {
    const target = event.target;
    if (!(target instanceof HTMLElement)) return;
    if (!target.matches(INPUT_SELECTOR) || target.classList.contains("keyboard-ignore")) return;
    if (event.metaKey || event.ctrlKey || event.altKey) return;
    if (event.repeat) { event.preventDefault(); return; }
    const now = performance.now();
    if (event.key === lastPhysicalKey && now - lastPhysicalKeyTime < KEY_DEBOUNCE_MS) {
      event.preventDefault();
      return;
    }
    lastPhysicalKey = event.key;
    lastPhysicalKeyTime = now;
  });

  document.addEventListener("focusin", (event) => {
    const target = event.target;
    if (!(target instanceof HTMLElement)) return;
    if (target.matches(INPUT_SELECTOR) && !target.classList.contains("keyboard-ignore")) {
      showKeyboard(target);
    }
  });
});
