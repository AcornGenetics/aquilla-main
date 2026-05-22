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
