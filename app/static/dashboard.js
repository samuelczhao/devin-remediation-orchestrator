const REFRESH_INTERVAL_MS = 5_000;

window.setInterval(() => {
  if (document.visibilityState === "visible" && !document.querySelector("details[open]")) {
    window.location.reload();
  }
}, REFRESH_INTERVAL_MS);
