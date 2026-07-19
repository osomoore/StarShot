/* App bootstrap: auth screen + screen router + toasts. */
(function () {
  // Public identifier (not a secret); must match the backend's GOOGLE_CLIENT_ID.
  const GOOGLE_CLIENT_ID = "767497052681-as1k10s8i67r1p498i0l8thv4eht0qft.apps.googleusercontent.com";
  let authMode = "login";
  let lastDeviceDiagnosticsKey = "";

  function mediaMatches(query) {
    return Boolean(window.matchMedia?.(query)?.matches);
  }

  function isPhoneUser() {
    const coarsePointer = mediaMatches("(pointer: coarse)");
    const anyCoarsePointer = mediaMatches("(any-pointer: coarse)");
    const narrow = mediaMatches("(max-width: 760px)");
    const tabletViewport = mediaMatches("(max-width: 1366px)");
    const compactHeight = mediaMatches("(max-height: 620px)");
    const mobileAgent = /Android|iPhone|iPod|IEMobile|Mobile/i.test(navigator.userAgent || "");
    const touchCapable = (navigator.maxTouchPoints || 0) > 0;
    return Boolean(
      ((coarsePointer || anyCoarsePointer || touchCapable) && tabletViewport)
      || (mobileAgent && (narrow || compactHeight)),
    );
  }

  function applyDeviceMode(reason) {
    document.documentElement.dataset.device = isPhoneUser() ? "phone" : "desktop";
    reportDeviceDiagnostics(reason);
  }

  function collectDeviceDiagnostics(reason) {
    return {
      app: "v2",
      reason,
      data_device: document.documentElement.dataset.device || "",
      detected_phone_layout: document.documentElement.dataset.device === "phone",
      user_agent: navigator.userAgent || "",
      platform: navigator.platform || "",
      vendor: navigator.vendor || "",
      max_touch_points: navigator.maxTouchPoints || 0,
      device_pixel_ratio: window.devicePixelRatio || 1,
      inner_width: window.innerWidth,
      inner_height: window.innerHeight,
      outer_width: window.outerWidth,
      outer_height: window.outerHeight,
      screen_width: window.screen?.width,
      screen_height: window.screen?.height,
      avail_width: window.screen?.availWidth,
      avail_height: window.screen?.availHeight,
      visual_viewport_width: window.visualViewport?.width,
      visual_viewport_height: window.visualViewport?.height,
      orientation_type: window.screen?.orientation?.type || "",
      pointer_coarse: mediaMatches("(pointer: coarse)"),
      pointer_fine: mediaMatches("(pointer: fine)"),
      any_pointer_coarse: mediaMatches("(any-pointer: coarse)"),
      any_pointer_fine: mediaMatches("(any-pointer: fine)"),
      hover_hover: mediaMatches("(hover: hover)"),
      any_hover_hover: mediaMatches("(any-hover: hover)"),
      max_width_760: mediaMatches("(max-width: 760px)"),
      max_width_900: mediaMatches("(max-width: 900px)"),
      max_width_1024: mediaMatches("(max-width: 1024px)"),
      max_width_1180: mediaMatches("(max-width: 1180px)"),
      max_width_1366: mediaMatches("(max-width: 1366px)"),
      max_height_620: mediaMatches("(max-height: 620px)"),
    };
  }

  function deviceDiagnosticsKey(diagnostics) {
    return [
      diagnostics.data_device,
      diagnostics.inner_width,
      diagnostics.inner_height,
      diagnostics.max_touch_points,
      diagnostics.pointer_coarse,
      diagnostics.any_pointer_coarse,
      diagnostics.max_width_1366,
    ].join("|");
  }

  function reportDeviceDiagnostics(reason) {
    const diagnostics = collectDeviceDiagnostics(reason);
    const key = deviceDiagnosticsKey(diagnostics);
    if (key === lastDeviceDiagnosticsKey) return;
    lastDeviceDiagnosticsKey = key;
    console.info("[StarShot v2 device diagnostics]", diagnostics);
    fetch("/api/debug/device-info", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(diagnostics),
      keepalive: true,
    }).catch((error) => {
      console.warn("[StarShot v2 device diagnostics] server log failed", error);
    });
  }

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

  function initGoogleSignIn() {
    const container = document.getElementById("google-signin");
    if (!container || !window.google?.accounts?.id) return;
    google.accounts.id.initialize({
      client_id: GOOGLE_CLIENT_ID,
      callback: async (response) => {
        const errorBox = document.getElementById("auth-error");
        errorBox.textContent = "";
        try {
          await API.googleLogin(response.credential);
          Lobby.enter();
        } catch (error) {
          errorBox.textContent = error.message;
        }
      },
    });
    google.accounts.id.renderButton(container, {
      theme: "filled_black", size: "large", shape: "pill", text: "signin_with", width: 280,
    });
  }

  document.addEventListener("DOMContentLoaded", async () => {
    applyDeviceMode("v2-dom-content-loaded");
    window.addEventListener("resize", () => applyDeviceMode("v2-resize"));
    window.addEventListener("orientationchange", () => {
      setTimeout(() => applyDeviceMode("v2-orientationchange"), 150);
    });

    // The GIS script loads async: it may already be here, or arrive later.
    if (window.google?.accounts?.id) initGoogleSignIn();
    else window.onGoogleLibraryLoad = initGoogleSignIn;

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

  window.App = { showScreen, toast, reportDeviceDiagnostics, applyDeviceMode };
})();
