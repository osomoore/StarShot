/* App bootstrap: auth screen + screen router + toasts. */
(function () {
  let authMode = "login";

  function showScreen(name) {
    for (const screen of ["auth", "lobby", "game"]) {
      document.getElementById("screen-" + screen).classList.toggle("hidden", screen !== name);
    }
  }

  let toastTimer = null;
  function toast(message, good) {
    const node = document.getElementById("toast");
    node.textContent = message;
    node.className = "toast" + (good ? " good" : "");
    node.classList.remove("hidden");
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => node.classList.add("hidden"), 3200);
  }

  function setAuthMode(mode) {
    authMode = mode;
    document.getElementById("tab-login").classList.toggle("active", mode === "login");
    document.getElementById("tab-register").classList.toggle("active", mode === "register");
    document.getElementById("auth-submit").textContent = mode === "login" ? "Board the Ship" : "Sign the Articles";
    document.getElementById("auth-password").autocomplete = mode === "login" ? "current-password" : "new-password";
    document.getElementById("auth-error").textContent = "";
  }

  document.addEventListener("DOMContentLoaded", async () => {
    document.getElementById("tab-login").addEventListener("click", () => setAuthMode("login"));
    document.getElementById("tab-register").addEventListener("click", () => setAuthMode("register"));
    document.getElementById("auth-form").addEventListener("submit", async (event) => {
      event.preventDefault();
      const username = document.getElementById("auth-username").value.trim();
      const password = document.getElementById("auth-password").value;
      const errorBox = document.getElementById("auth-error");
      errorBox.textContent = "";
      try {
        if (authMode === "login") await API.login(username, password);
        else await API.register(username, password);
        document.getElementById("auth-password").value = "";
        Lobby.enter();
      } catch (error) {
        errorBox.textContent = error.message;
      }
    });

    // Session check: deep-link straight into a game (?game=<id>) or the lobby.
    try {
      await API.me();
      const gameParam = new URLSearchParams(location.search).get("game");
      if (gameParam) {
        history.replaceState(null, "", location.pathname);
        Game.enter(gameParam);
      } else {
        Lobby.enter();
      }
    } catch (err) {
      showScreen("auth");
    }
  });

  window.App = { showScreen, toast };
})();
