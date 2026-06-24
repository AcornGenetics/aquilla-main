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
