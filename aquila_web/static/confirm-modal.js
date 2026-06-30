"use strict";

function historyDeleteCopy(runNames) {
  const label = runNames.length === 1 ? runNames[0] : `${runNames.length} runs`;
  return {
    title: runNames.length === 1 ? "Delete run?" : "Delete runs?",
    message: `Are you sure you want to delete ${label}?`,
  };
}

function profilesDeleteCopy(profileNames) {
  const count = profileNames.length;
  const detail = count <= 3
    ? profileNames.join(", ")
    : `${profileNames.slice(0, 3).join(", ")} and ${count - 3} more`;
  return {
    title: count === 1 ? "Delete profile?" : "Delete profiles?",
    message: `Are you sure you want to delete ${count} profile${count === 1 ? "" : "s"}?`,
    detail,
  };
}

// Themed replacement for window.confirm(). Returns a Promise<boolean>.
// Fail-safe / default-deny: resolves true ONLY on an explicit confirm-button
// click; Cancel, backdrop tap, Esc, and any internal error resolve false.
// All DOM work is deferred to call time, so requiring this file under Node
// (for the pure copy builders above) touches no `document`.
function confirmModal(options) {
  const opts = options || {};
  return new Promise((resolve) => {
    if (typeof document === "undefined") {
      resolve(false);
      return;
    }

    let settled = false;
    let root = null;

    const onKeydown = (event) => {
      if (event.key === "Escape") {
        event.preventDefault();
        finish(false);
      }
    };

    function finish(result) {
      if (settled) {
        return;
      }
      settled = true;
      document.removeEventListener("keydown", onKeydown, true);
      if (root && root.parentNode) {
        root.parentNode.removeChild(root);
      }
      resolve(result);
    }

    try {
      root = document.createElement("div");
      root.className = "confirm-modal";
      root.setAttribute("role", "alertdialog");
      root.setAttribute("aria-modal", "true");

      const card = document.createElement("div");
      card.className = "confirm-modal__card";

      const title = document.createElement("h2");
      title.className = "confirm-modal__title";
      title.textContent = opts.title || "Are you sure?";
      card.appendChild(title);

      const message = document.createElement("p");
      message.className = "confirm-modal__message";
      message.textContent = opts.message || "";
      card.appendChild(message);

      if (opts.detail) {
        const detail = document.createElement("p");
        detail.className = "confirm-modal__detail";
        detail.textContent = opts.detail;
        card.appendChild(detail);
      }

      const actions = document.createElement("div");
      actions.className = "confirm-modal__actions";

      const cancelBtn = document.createElement("button");
      cancelBtn.type = "button";
      cancelBtn.className = "confirm-modal__btn confirm-modal__btn--cancel";
      cancelBtn.textContent = "Cancel";
      cancelBtn.addEventListener("click", () => finish(false));

      const confirmBtn = document.createElement("button");
      confirmBtn.type = "button";
      confirmBtn.className = "confirm-modal__btn confirm-modal__btn--confirm";
      confirmBtn.textContent = opts.confirmLabel || "Delete";
      confirmBtn.addEventListener("click", () => finish(true));

      actions.appendChild(cancelBtn);
      actions.appendChild(confirmBtn);
      card.appendChild(actions);
      root.appendChild(card);

      // Tapping the backdrop (outside the card) cancels — primary touch dismissal.
      root.addEventListener("click", (event) => {
        if (event.target === root) {
          finish(false);
        }
      });

      document.addEventListener("keydown", onKeydown, true);
      document.body.appendChild(root);
      // Destructive-safe: open focused on Cancel, never the confirm button.
      cancelBtn.focus();
    } catch (err) {
      finish(false);
    }
  });
}

// Enable unit testing under Node (node:test) without affecting the browser,
// where `module` is undefined. Not a build step — a guarded CommonJS export.
if (typeof module !== "undefined" && module.exports) {
  module.exports = { historyDeleteCopy, profilesDeleteCopy, confirmModal };
}
