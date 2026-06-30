const shouldSuppressNavFlash = () => window.matchMedia("(pointer: coarse)").matches;

document.addEventListener("click", (event) => {
  if (!shouldSuppressNavFlash()) {
    return;
  }

  const link = event.target.closest("a.run-nav-link, a.help-link");

  if (!link) {
    return;
  }

  link.blur();
});

// Show a red "1" badge on the Settings nav item when an OTA update is available
(function checkUpdateBadge() {
  const links = document.querySelectorAll("a.settings-link");
  if (!links.length) return;
  fetch("/update/status")
    .then(r => r.ok ? r.json() : null)
    .then(data => {
      if (!data || !data.available || data.dismissed) return;
      links.forEach(link => {
        if (!link.querySelector(".help-badge")) {
          const badge = document.createElement("span");
          badge.className = "help-badge";
          badge.textContent = "1";
          link.appendChild(badge);
        }
      });
    })
    .catch(() => {});
})();

// One-time "Update Complete" modal after an OTA auto-reboot (#183, ADR-018).
// The backend reports status === "complete" once, driven by the on-disk sentinel.
(function showUpdateCompleteModal() {
  if (document.querySelector(".update-complete-modal")) return;
  fetch("/update/status")
    .then(r => r.ok ? r.json() : null)
    .then(data => {
      if (!data || data.status !== "complete") return;

      const backdrop = document.createElement("div");
      backdrop.className = "update-complete-modal";

      const card = document.createElement("div");
      card.className = "update-complete-modal__card";
      card.setAttribute("role", "alertdialog");
      card.setAttribute("aria-labelledby", "update-complete-title");

      const title = document.createElement("div");
      title.id = "update-complete-title";
      title.className = "update-complete-modal__title";
      title.textContent = "✓ Update Complete";

      const body = document.createElement("div");
      body.className = "update-complete-modal__body";
      body.textContent = "The device updated successfully and is ready to use.";

      const ok = document.createElement("button");
      ok.type = "button";
      ok.className = "update-complete-modal__ok";
      ok.textContent = "OK";
      ok.addEventListener("click", () => {
        backdrop.remove();
        fetch("/update/ack-complete", { method: "POST" }).catch(() => {});
      });

      card.appendChild(title);
      card.appendChild(body);
      card.appendChild(ok);
      backdrop.appendChild(card);
      document.body.appendChild(backdrop);
      ok.focus();
    })
    .catch(() => {});
})();
