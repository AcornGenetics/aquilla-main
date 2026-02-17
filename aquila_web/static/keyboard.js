const KEYBOARD_SELECTOR = ".onscreen-keyboard";
const INPUT_SELECTOR = "input[type='text'], input[type='password'], input[type='number'], input[type='search'], input[type='tel'], input[type='url'], textarea";

const KEY_ROWS = [
  ["1", "2", "3", "4", "5", "6", "7", "8", "9", "0"],
  ["q", "w", "e", "r", "t", "y", "u", "i", "o", "p"],
  ["a", "s", "d", "f", "g", "h", "j", "k", "l"],
  ["z", "x", "c", "v", "b", "n", "m", ".", "-"]
];

let activeInput = null;

function buildKeyboard() {
  if (document.querySelector(KEYBOARD_SELECTOR)) {
    return;
  }

  const keyboard = document.createElement("div");
  keyboard.className = "onscreen-keyboard";
  keyboard.addEventListener("mousedown", (event) => {
    const key = event.target.closest(".keyboard-key");
    if (!key || !key.dataset.value) {
      return;
    }
    event.preventDefault();
    handleKeyPress(key.dataset.value);
  });
  keyboard.addEventListener("touchstart", (event) => {
    const key = event.target.closest(".keyboard-key");
    if (!key || !key.dataset.value) {
      return;
    }
    event.preventDefault();
    handleKeyPress(key.dataset.value);
  });

  KEY_ROWS.forEach((row) => {
    const rowEl = document.createElement("div");
    rowEl.className = "keyboard-row";
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

  const actionRow = document.createElement("div");
  actionRow.className = "keyboard-row keyboard-row--actions";

  const leftActions = document.createElement("div");
  leftActions.className = "keyboard-actions keyboard-actions--left";

  const rightActions = document.createElement("div");
  rightActions.className = "keyboard-actions keyboard-actions--right";

  const makeAction = (label, value, className = "") => {
    const actionEl = document.createElement("button");
    actionEl.type = "button";
    actionEl.className = `keyboard-key keyboard-key--action ${className}`.trim();
    actionEl.textContent = label;
    actionEl.dataset.value = value;
    return actionEl;
  };

  leftActions.appendChild(makeAction("Back", "backspace"));
  leftActions.appendChild(makeAction("Clear", "clear"));

  const spaceKey = makeAction("Space", "space", "keyboard-key--wide");

  rightActions.appendChild(makeAction("Enter", "enter"));
  rightActions.appendChild(makeAction("Close", "close"));

  actionRow.appendChild(leftActions);
  actionRow.appendChild(spaceKey);
  actionRow.appendChild(rightActions);

  keyboard.appendChild(actionRow);
  document.body.appendChild(keyboard);
}

function updateInputValue(value, replace = false) {
  if (!activeInput) {
    return;
  }
  const input = activeInput;
  const fallbackPos = input.value.length;
  const start = Number.isInteger(input.selectionStart) ? input.selectionStart : fallbackPos;
  const end = Number.isInteger(input.selectionEnd) ? input.selectionEnd : fallbackPos;
  const current = input.value || "";
  const nextValue = replace
    ? value
    : current.slice(0, start) + value + current.slice(end);
  input.value = nextValue;
  const nextPos = replace ? nextValue.length : start + value.length;
  if (input.setSelectionRange) {
    input.setSelectionRange(nextPos, nextPos);
  }
  input.dispatchEvent(new Event("input", { bubbles: true }));
}

function handleKeyPress(value) {
  if (!activeInput) {
    return;
  }
  activeInput.focus();

  switch (value) {
    case "space":
      updateInputValue(" ");
      return;
    case "backspace": {
      const input = activeInput;
      const start = input.selectionStart ?? input.value.length;
      const end = input.selectionEnd ?? input.value.length;
      if (start !== end) {
        const current = input.value || "";
        input.value = current.slice(0, start) + current.slice(end);
        input.setSelectionRange(start, start);
        input.dispatchEvent(new Event("input", { bubbles: true }));
        return;
      }
      if (start > 0) {
        const current = input.value || "";
        input.value = current.slice(0, start - 1) + current.slice(end);
        const nextPos = Math.max(start - 1, 0);
        input.setSelectionRange(nextPos, nextPos);
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
      updateInputValue(value);
  }
}

function showKeyboard(target) {
  if (!target || target.readOnly || target.disabled) {
    return;
  }
  activeInput = target;
  activeInput.focus();
  const length = activeInput.value?.length ?? 0;
  if (activeInput.setSelectionRange) {
    activeInput.setSelectionRange(length, length);
  }
  const keyboard = document.querySelector(KEYBOARD_SELECTOR);
  if (keyboard) {
    keyboard.classList.add("is-visible");
  }
}

function hideKeyboard() {
  const keyboard = document.querySelector(KEYBOARD_SELECTOR);
  if (keyboard) {
    keyboard.classList.remove("is-visible");
  }
  activeInput = null;
}

document.addEventListener("DOMContentLoaded", () => {
  buildKeyboard();

  document.addEventListener("focusin", (event) => {
    const target = event.target;
    if (!(target instanceof HTMLElement)) {
      return;
    }
    if (target.matches(INPUT_SELECTOR) && !target.classList.contains("keyboard-ignore")) {
      showKeyboard(target);
    }
  });

  document.addEventListener("click", (event) => {
    const target = event.target;
    if (!(target instanceof HTMLElement)) {
      return;
    }
    const keyboard = document.querySelector(KEYBOARD_SELECTOR);
    if (keyboard && keyboard.contains(target)) {
      const key = target.closest(".keyboard-key");
      if (key && key.dataset.value) {
        handleKeyPress(key.dataset.value);
      }
      return;
    }
  });
});
