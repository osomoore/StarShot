/* App bootstrap: auth screen + screen router + toasts. */
(function () {
  // Public identifiers (not secrets); must match the backend's GOOGLE_CLIENT_ID
  // and MICROSOFT_CLIENT_ID.
  const GOOGLE_CLIENT_ID = "767497052681-as1k10s8i67r1p498i0l8thv4eht0qft.apps.googleusercontent.com";
  const MICROSOFT_CLIENT_ID = "8020ec54-185e-476a-9d7a-74c3d47a7a8c";
  // Discord Public Client (PKCE, no secret). The redirect URI must match the
  // value registered in the Discord developer portal exactly.
  const DISCORD_CLIENT_ID = "1528360566857535590";
  const DISCORD_REDIRECT_URI = "https://david.cybrwzrds.com/v2";
  const DISCORD_STATE_KEY = "discord_oauth_state";
  const DISCORD_VERIFIER_KEY = "discord_pkce_verifier";
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

  // Lazily create the MSAL app on first use. The library script loads async,
  // so this waits for it to arrive rather than assuming it is already here.
  let msalAppPromise = null;
  function getMsalApp() {
    if (!msalAppPromise) {
      msalAppPromise = waitForGlobal(() => window.msal?.PublicClientApplication, 10000)
        .then(async () => {
          const app = new msal.PublicClientApplication({
            auth: {
              clientId: MICROSOFT_CLIENT_ID,
              authority: "https://login.microsoftonline.com/common",
              redirectUri: "https://david.cybrwzrds.com/v2/",
            },
            cache: { cacheLocation: "sessionStorage" },
          });
          await app.initialize();
          return app;
        })
        .catch((error) => {
          // Let the next click retry instead of caching the failure forever.
          msalAppPromise = null;
          throw error;
        });
    }
    return msalAppPromise;
  }

  function waitForGlobal(test, timeoutMs) {
    return new Promise((resolve, reject) => {
      if (test()) return resolve();
      let waited = 0;
      const timer = setInterval(() => {
        if (test()) {
          clearInterval(timer);
          resolve();
        } else if ((waited += 100) >= timeoutMs) {
          clearInterval(timer);
          reject(new Error("Microsoft sign-in could not load. Check yer connection and try again."));
        }
      }, 100);
    });
  }

  function initMicrosoftSignIn() {
    // Attach the handler unconditionally so the button is always live; MSAL is
    // fetched on demand inside the click, and load failures show as an error.
    const button = document.getElementById("microsoft-signin");
    if (!button) return;
    button.addEventListener("click", async () => {
      const errorBox = document.getElementById("auth-error");
      errorBox.textContent = "";
      try {
        const app = await getMsalApp();
        const result = await app.loginPopup({
          scopes: ["openid", "profile", "email"],
          prompt: "select_account",
        });
        await API.microsoftLogin(result.idToken);
        Lobby.enter();
      } catch (error) {
        // A closed popup isn't an error worth shouting about.
        if (error.errorCode === "user_cancelled") return;
        errorBox.textContent = error.message;
      }
    });
  }

  // ── Discord: OAuth2 Authorization Code + PKCE ──────────────────────────
  // Unlike Google/Microsoft (which hand us an ID token in the page), Discord
  // uses a full redirect: we send the browser to Discord with a PKCE challenge,
  // Discord bounces back to DISCORD_REDIRECT_URI with a one-time ?code, and the
  // backend redeems it. The verifier and state live in sessionStorage across
  // the round trip.
  function base64UrlEncode(buffer) {
    const bytes = new Uint8Array(buffer);
    let binary = "";
    for (let i = 0; i < bytes.length; i++) binary += String.fromCharCode(bytes[i]);
    return btoa(binary).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
  }

  function randomUrlToken(byteLength) {
    const bytes = new Uint8Array(byteLength);
    crypto.getRandomValues(bytes);
    return base64UrlEncode(bytes);
  }

  async function pkceChallenge(verifier) {
    const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(verifier));
    return base64UrlEncode(digest);
  }

  function initDiscordSignIn() {
    const button = document.getElementById("discord-signin");
    if (!button) return;
    button.addEventListener("click", async () => {
      const errorBox = document.getElementById("auth-error");
      errorBox.textContent = "";
      try {
        const verifier = randomUrlToken(32);   // 43 chars — a valid PKCE verifier
        const state = randomUrlToken(16);
        const challenge = await pkceChallenge(verifier);
        sessionStorage.setItem(DISCORD_VERIFIER_KEY, verifier);
        sessionStorage.setItem(DISCORD_STATE_KEY, state);
        const params = new URLSearchParams({
          client_id: DISCORD_CLIENT_ID,
          response_type: "code",
          redirect_uri: DISCORD_REDIRECT_URI,
          scope: "identify email",
          state,
          code_challenge: challenge,
          code_challenge_method: "S256",
        });
        window.location.assign("https://discord.com/oauth2/authorize?" + params.toString());
      } catch (error) {
        errorBox.textContent = "Discord sign-in could not start. Try again.";
      }
    });
  }

  // Returns true when the current page load is a Discord redirect we handled
  // (so the normal session boot is skipped).
  async function handleDiscordCallback() {
    const params = new URLSearchParams(location.search);
    const code = params.get("code");
    const returnedState = params.get("state");
    const providerError = params.get("error");
    const storedState = sessionStorage.getItem(DISCORD_STATE_KEY);
    const verifier = sessionStorage.getItem(DISCORD_VERIFIER_KEY);
    // Only act on a redirect we actually started (state + verifier stashed).
    if (!storedState || !verifier) return false;
    if (!code && !providerError) return false;

    sessionStorage.removeItem(DISCORD_STATE_KEY);
    sessionStorage.removeItem(DISCORD_VERIFIER_KEY);
    history.replaceState(null, "", location.pathname);  // drop the OAuth params
    const errorBox = document.getElementById("auth-error");
    errorBox.textContent = "";

    if (providerError || !code) {
      showScreen("auth");
      if (providerError !== "access_denied") {
        errorBox.textContent = "Discord sign-in was cancelled or failed. Try again.";
      }
      return true;
    }
    if (returnedState !== storedState) {
      showScreen("auth");
      errorBox.textContent = "Discord sign-in failed a security check. Try again.";
      return true;
    }
    try {
      await API.discordLogin(code, verifier, DISCORD_REDIRECT_URI);
      Lobby.enter();
    } catch (error) {
      showScreen("auth");
      errorBox.textContent = error.message;
    }
    return true;
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

    // The button attaches its own handler immediately and loads MSAL on click.
    initMicrosoftSignIn();

    // Discord redirects the whole page, so its button just needs a click handler.
    initDiscordSignIn();

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

    // A Discord redirect (?code=&state=) lands us back here — complete that
    // sign-in instead of the normal session boot.
    if (await handleDiscordCallback()) return;

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
