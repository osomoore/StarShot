/* Shared build-time footer for v2 pages. */
(function () {
  const state = { frontend: null, backend: null };
  let timer = null;

  function parseTime(value) {
    if (!value) return null;
    const date = new Date(value);
    return Number.isNaN(date.getTime()) ? null : date;
  }

  function formatLocal(date) {
    if (!date) return "unknown";
    return date.toLocaleString(undefined, {
      year: "numeric",
      month: "short",
      day: "numeric",
      hour: "numeric",
      minute: "2-digit",
    });
  }

  function formatAge(date) {
    if (!date) return "";
    const seconds = Math.max(0, Math.floor((Date.now() - date.getTime()) / 1000));
    const days = Math.floor(seconds / 86400);
    const hours = Math.floor((seconds % 86400) / 3600);
    const minutes = Math.floor((seconds % 3600) / 60);
    if (days > 0) return `${days}d ${hours}h ago`;
    if (hours > 0) return `${hours}h ${minutes}m ago`;
    if (minutes > 0) return `${minutes}m ago`;
    return "just now";
  }

  function line(label, date) {
    if (!date) return `${label}: unknown`;
    return `${label}: ${formatLocal(date)} (${formatAge(date)})`;
  }

  function render() {
    const node = document.getElementById("build-footer");
    if (!node) return;
    node.textContent = `${line("Front end", state.frontend)} | ${line("Back end", state.backend)}`;
  }

  async function loadBuildInfo() {
    const node = document.getElementById("build-footer");
    if (!node) return;
    try {
      const response = await fetch("/api/v2/build-info", { credentials: "same-origin" });
      if (!response.ok) throw new Error(`Request failed (${response.status})`);
      const payload = await response.json();
      state.frontend = parseTime(payload?.frontend?.built_at);
      state.backend = parseTime(payload?.backend?.built_at);
      render();
      clearInterval(timer);
      timer = setInterval(render, 60000);
    } catch (error) {
      node.textContent = "Build time unavailable";
      console.warn("[StarShot build footer]", error);
    }
  }

  document.addEventListener("DOMContentLoaded", loadBuildInfo);
})();
