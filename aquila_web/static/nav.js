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

// Show a red "1" badge on the ? help icon when an OTA update is available
(function checkUpdateBadge() {
  const links = document.querySelectorAll("a.help-link");
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

// One-time OTA result modal after an auto-reboot (#183, ADR-018).
// The backend reports status === "complete" once (update applied) or "failed" once
// (crash mid-update: still on the old image), driven by the on-disk sentinel.
// See spec_ota_update_failed_detection.md.
(function showUpdateResultModal() {
  const MODALS = {
    complete: {
      modifier: "",
      title: "✓ Update Complete",
      body: "The device updated successfully and is ready to use.",
      ack: "/update/ack-complete",
    },
    failed: {
      modifier: "update-complete-modal--failed",
      title: "✗ Update Failed",
      body: "The update did not finish; the device is still on its previous version. Please try again.",
      ack: "/update/ack-failed",
    },
  };

  if (document.querySelector(".update-complete-modal")) return;
  fetch("/update/status")
    .then(r => r.ok ? r.json() : null)
    .then(data => {
      const cfg = data && MODALS[data.status];
      if (!cfg) return;

      const backdrop = document.createElement("div");
      backdrop.className = "update-complete-modal";

      const card = document.createElement("div");
      card.className = "update-complete-modal__card";
      if (cfg.modifier) card.classList.add(cfg.modifier);
      card.setAttribute("role", "alertdialog");
      card.setAttribute("aria-labelledby", "update-result-title");

      const title = document.createElement("div");
      title.id = "update-result-title";
      title.className = "update-complete-modal__title";
      title.textContent = cfg.title;

      const body = document.createElement("div");
      body.className = "update-complete-modal__body";
      body.textContent = cfg.body;

      const ok = document.createElement("button");
      ok.type = "button";
      ok.className = "update-complete-modal__ok";
      ok.textContent = "OK";
      ok.addEventListener("click", () => {
        backdrop.remove();
        fetch(cfg.ack, { method: "POST" }).catch(() => {});
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
