/* Account: first-login onboarding (Terms + Privacy + player name), the
   account screen (providers, data export, deletion), and reauthentication. */
(function () {
  const esc = (value) => Cards.escapeHtml(value);
  let onboardingOpen = false;
  let currentAccount = null;

  // ── First-login onboarding ────────────────────────────────────────────
  // Blocking modal shown when the signed-in user still owes Terms acceptance,
  // Privacy acknowledgement, or a public player name. Reappears whenever the
  // Terms version changes.
  async function maybeOnboard(me) {
    if (onboardingOpen) return;
    if (!me || me.user.is_guest) return;
    if (!me.needs_terms && !me.needs_display_name) return;
    onboardingOpen = true;
    let policies = { terms: { version: "" }, privacy: { version: "" } };
    try { policies = await API.policies(); } catch (err) { /* versions shown best-effort */ }

    const needsTerms = me.needs_terms;
    const needsName = me.needs_display_name;
    const overlay = document.createElement("div");
    overlay.className = "overlay onboarding-overlay";
    overlay.innerHTML = `
      <div class="picker onboarding-modal">
        <h3>⚓ Before Ye Set Sail</h3>
        <form id="onboarding-form" class="feedback-form">
          ${needsTerms ? `
          <label class="onboarding-check">
            <input id="onboard-terms" type="checkbox" required>
            <span>I accept the <a href="/v2/terms" target="_blank" rel="noopener">Terms of Service</a>
              (version ${esc(policies.terms.version)})</span>
          </label>
          <label class="onboarding-check">
            <input id="onboard-privacy" type="checkbox" required>
            <span>I acknowledge the <a href="/v2/privacy" target="_blank" rel="noopener">Privacy Policy</a>
              (version ${esc(policies.privacy.version)})</span>
          </label>` : ""}
          ${needsName ? `
          <label>Public player name — what other captains will see
            <input id="onboard-name" type="text" minlength="3" maxlength="24" required
              value="${esc(me.user.display_name || "")}">
          </label>
          <div class="feedback-actions">
            <button type="button" class="btn ghost" id="onboard-random">🎲 Random</button>
          </div>` : ""}
          <div class="feedback-actions">
            <button type="submit" class="btn gold big">Set Sail</button>
          </div>
          <div id="onboard-status" class="auth-error"></div>
        </form>
      </div>`;
    document.body.appendChild(overlay);
    const status = overlay.querySelector("#onboard-status");
    overlay.querySelector("#onboard-random")?.addEventListener("click", async () => {
      try {
        const result = await API.randomName();
        overlay.querySelector("#onboard-name").value = result.name || "";
      } catch (error) { status.textContent = error.message; }
    });
    overlay.querySelector("#onboarding-form").addEventListener("submit", async (event) => {
      event.preventDefault();
      status.textContent = "";
      try {
        if (needsName) {
          const result = await API.setDisplayName(overlay.querySelector("#onboard-name").value.trim());
          if (result.warning) App.toast(result.warning);
        }
        if (needsTerms) {
          await API.acceptPolicies(policies.terms.version, policies.privacy.version);
        }
        overlay.remove();
        onboardingOpen = false;
        App.toast("Welcome aboard, captain!", true);
      } catch (error) {
        status.textContent = error.message;
      }
    });
  }

  // ── Reauthentication ──────────────────────────────────────────────────
  // Sensitive actions (export, unlink, delete) require a fresh sign-in.
  // Resolves true after a successful reauth with the same account.
  function reauthenticate() {
    return new Promise((resolve) => {
      const before = currentAccount ? currentAccount.username : null;
      const overlay = document.createElement("div");
      overlay.className = "overlay";
      overlay.innerHTML = `
        <div class="picker reauth-modal">
          <h3>🔐 Confirm It's You</h3>
          <p class="feedback-copy">Sign in again with a linked provider to continue.</p>
          <div id="reauth-google" class="google-signin"></div>
          <button id="reauth-microsoft" class="btn ghost">Sign in with Microsoft</button>
          <button id="reauth-discord" class="btn ghost">Continue with Discord (reloads the page)</button>
          <div class="feedback-actions">
            <button class="btn ghost" id="reauth-cancel">Cancel</button>
          </div>
          <div id="reauth-status" class="auth-error"></div>
        </div>`;
      document.body.appendChild(overlay);
      const status = overlay.querySelector("#reauth-status");
      const finish = async (ok) => {
        if (ok && before) {
          // A reauth must never silently switch accounts.
          try {
            const me = await API.me();
            if (me.user.username !== before) {
              App.toast("Signed into a different account — reloading.");
              location.reload();
              return;
            }
          } catch (err) { ok = false; }
        }
        overlay.remove();
        App.auth.initGoogleSignIn(); // restore the login page's Google handler
        resolve(ok);
      };
      overlay.querySelector("#reauth-cancel").addEventListener("click", () => finish(false));
      App.auth.renderGoogleButton(overlay.querySelector("#reauth-google"), async (credential) => {
        try {
          await API.googleLogin(credential);
          finish(true);
        } catch (error) { status.textContent = error.message; }
      });
      overlay.querySelector("#reauth-microsoft").addEventListener("click", async () => {
        status.textContent = "";
        try {
          const idToken = await App.auth.microsoftIdToken();
          if (!idToken) return;
          await API.microsoftLogin(idToken);
          finish(true);
        } catch (error) { status.textContent = error.message; }
      });
      overlay.querySelector("#reauth-discord").addEventListener("click", () => {
        App.auth.startDiscordSignIn(false).catch(() => {
          status.textContent = "Discord sign-in could not start.";
        });
      });
    });
  }

  async function withRecentAuth(action) {
    try {
      return await action();
    } catch (error) {
      if (error.status === 403 && /confirm it's you/i.test(error.message || "")) {
        if (await reauthenticate()) return action();
        return undefined;
      }
      throw error;
    }
  }

  // ── Account screen ────────────────────────────────────────────────────
  async function enter() {
    App.showScreen("account");
    const body = document.getElementById("account-body");
    body.innerHTML = '<div class="empty-note">Loading…</div>';
    let data;
    try {
      data = await API.account();
    } catch (error) {
      if (error.status === 401) { App.showScreen("auth"); return; }
      body.innerHTML = `<div class="empty-note">${esc(error.message)}</div>`;
      return;
    }
    currentAccount = data.account;
    render(data.account);
  }

  function formatDate(iso) {
    return String(iso || "").slice(0, 10);
  }

  function render(account) {
    const body = document.getElementById("account-body");
    const providers = account.providers || [];
    const providerRows = providers.map((entry) => `
      <tr>
        <td>${esc(entry.label)}</td>
        <td>${esc(entry.email || "—")}</td>
        <td>${esc(formatDate(entry.linked_at) || "—")}</td>
        <td><button class="btn ghost small account-unlink" data-provider="${esc(entry.provider)}"
          ${providers.length <= 1 ? "disabled title=\"Ye can't cast off yer last way aboard.\"" : ""}>Unlink</button></td>
      </tr>`).join("");
    body.innerHTML = `
      <div class="account-section">
        <h3 class="panel-sub">Public Player Name</h3>
        <p class="account-line"><b>${esc(account.display_name)}</b>
          <button id="account-change-name" class="btn ghost small">✏ Change Name</button></p>
        <p class="account-line muted">Sailing since ${esc(formatDate(account.created_at))} ·
          ${account.wins}W / ${account.losses}L / ${account.draws}D over ${account.games_played} battles</p>
      </div>
      <div class="account-section">
        <h3 class="panel-sub">Connected Sign-ins</h3>
        <table class="leaderboard account-providers">
          <tr><th>Provider</th><th>Email</th><th>Linked</th><th></th></tr>
          ${providerRows || '<tr><td colspan="4" class="muted">None linked.</td></tr>'}
        </table>
        <div class="account-link-buttons">
          ${["google", "microsoft", "discord"].filter((p) => !providers.some((e) => e.provider === p))
            .map((p) => `<button class="btn ghost small account-link" data-provider="${p}">＋ Link ${p[0].toUpperCase() + p.slice(1)}</button>`).join(" ")}
        </div>
      </div>
      <div class="account-section">
        <h3 class="panel-sub">Your Creations</h3>
        <p class="account-line">
          <button id="account-stardock" class="btn ghost small">🚀 Your StarDock Ships</button>
          <button id="account-starbreach" class="btn ghost small">☄ Your StarBreach Bosses</button>
        </p>
      </div>
      <div class="account-section">
        <h3 class="panel-sub">Legal</h3>
        <p class="account-line">
          <a href="/v2/terms" target="_blank" rel="noopener">Terms of Service</a> ·
          <a href="/v2/privacy" target="_blank" rel="noopener">Privacy Policy</a>
          ${account.policies && account.policies.accepted_at
            ? `<span class="muted"> — accepted ${esc(formatDate(account.policies.accepted_at))}
               (Terms ${esc(account.policies.terms_version || "?")}, Privacy ${esc(account.policies.privacy_version || "?")})</span>`
            : ""}
        </p>
      </div>
      <div class="account-section">
        <h3 class="panel-sub">Your Data</h3>
        <div class="feedback-actions account-actions">
          <button id="account-export" class="btn gold">⬇ Download My Data</button>
          <button id="account-delete" class="btn crimson">☠ Delete My Account</button>
          <button id="account-logout" class="btn ghost">Abandon Ship (Logout)</button>
        </div>
        <div id="account-status" class="auth-error"></div>
      </div>`;

    const status = () => document.getElementById("account-status");
    document.getElementById("account-change-name").addEventListener("click", () => {
      window.Lobby?.openNameModal?.(false, () => enter());
    });
    document.getElementById("account-stardock").addEventListener("click", () => window.ShipDesigner?.openPlayerDesigner?.());
    document.getElementById("account-starbreach").addEventListener("click", () => window.BossDesigner?.openPlayerDesigner?.());
    document.getElementById("account-logout").addEventListener("click", async () => {
      try { await API.logout(); } catch (err) {}
      App.showScreen("auth");
    });
    document.getElementById("account-export").addEventListener("click", async () => {
      status().textContent = "";
      try {
        await withRecentAuth(downloadExport);
      } catch (error) { status().textContent = error.message; }
    });
    document.getElementById("account-delete").addEventListener("click", openDeleteModal);
    body.querySelectorAll(".account-unlink").forEach((button) => {
      button.addEventListener("click", async () => {
        if (!confirm(`Unlink ${button.dataset.provider} from this account?`)) return;
        status().textContent = "";
        try {
          const result = await withRecentAuth(() => API.unlinkProvider(button.dataset.provider));
          if (result) { App.toast("Provider unlinked.", true); enter(); }
        } catch (error) { status().textContent = error.message; }
      });
    });
    body.querySelectorAll(".account-link").forEach((button) => {
      button.addEventListener("click", () => linkProvider(button.dataset.provider));
    });
  }

  function linkProvider(provider) {
    const status = document.getElementById("account-status");
    status.textContent = "";
    if (provider === "discord") {
      App.auth.startDiscordSignIn(true).catch(() => { status.textContent = "Discord link could not start."; });
      return;
    }
    if (provider === "microsoft") {
      (async () => {
        try {
          const idToken = await App.auth.microsoftIdToken();
          if (!idToken) return;
          await API.microsoftLogin(idToken, true);
          App.toast("Microsoft linked.", true);
          enter();
        } catch (error) { status.textContent = error.message; }
      })();
      return;
    }
    // Google: render the official button in a tiny modal.
    const overlay = document.createElement("div");
    overlay.className = "overlay";
    overlay.innerHTML = `
      <div class="picker">
        <h3>Link Google</h3>
        <div id="link-google" class="google-signin"></div>
        <button class="btn ghost picker-cancel" id="link-google-cancel">Never mind</button>
        <div id="link-google-status" class="auth-error"></div>
      </div>`;
    document.body.appendChild(overlay);
    const close = () => { overlay.remove(); App.auth.initGoogleSignIn(); };
    overlay.querySelector("#link-google-cancel").addEventListener("click", close);
    App.auth.renderGoogleButton(overlay.querySelector("#link-google"), async (credential) => {
      try {
        await API.googleLogin(credential, true);
        close();
        App.toast("Google linked.", true);
        enter();
      } catch (error) {
        overlay.querySelector("#link-google-status").textContent = error.message;
      }
    });
  }

  async function downloadExport() {
    const response = await fetch("/api/v2/account/export", { credentials: "same-origin" });
    if (!response.ok) {
      let detail = `Export failed (${response.status})`;
      try { detail = (await response.json()).detail || detail; } catch (err) {}
      const error = new Error(detail);
      error.status = response.status;
      throw error;
    }
    const blob = await response.blob();
    const disposition = response.headers.get("Content-Disposition") || "";
    const match = /filename="([^"]+)"/.exec(disposition);
    const link = document.createElement("a");
    link.href = URL.createObjectURL(blob);
    link.download = match ? match[1] : "starshot-account-data.json";
    document.body.appendChild(link);
    link.click();
    link.remove();
    URL.revokeObjectURL(link.href);
    App.toast("Yer data be downloading.", true);
  }

  function openDeleteModal() {
    const overlay = document.createElement("div");
    overlay.className = "overlay";
    overlay.innerHTML = `
      <div class="picker delete-modal">
        <h3>☠ Delete My Account</h3>
        <p class="feedback-copy"><b>This cannot be undone.</b> Deleting yer account removes the account itself,
          saved StarDock ships, saved StarBreach bosses, preferences, statistics, achievements, and yer
          leaderboard presence. Battles ye fought with other captains stay in their histories, anonymized.</p>
        <form id="delete-form" class="feedback-form">
          <label>Type <b>DELETE</b> to confirm
            <input id="delete-confirm" type="text" autocomplete="off" maxlength="20">
          </label>
          <div class="feedback-actions">
            <button type="button" class="btn ghost" id="delete-cancel">Belay That</button>
            <button type="submit" class="btn crimson" id="delete-submit" disabled>Send It to the Locker</button>
          </div>
          <div id="delete-status" class="auth-error"></div>
        </form>
      </div>`;
    document.body.appendChild(overlay);
    const input = overlay.querySelector("#delete-confirm");
    const submit = overlay.querySelector("#delete-submit");
    input.addEventListener("input", () => { submit.disabled = input.value.trim() !== "DELETE"; });
    overlay.querySelector("#delete-cancel").addEventListener("click", () => overlay.remove());
    overlay.querySelector("#delete-form").addEventListener("submit", async (event) => {
      event.preventDefault();
      if (input.value.trim() !== "DELETE") return;
      if (!confirm("Final confirmation: delete this account forever?")) return;
      const status = overlay.querySelector("#delete-status");
      status.textContent = "";
      try {
        const result = await withRecentAuth(() => API.deleteAccount());
        if (!result) return; // reauth cancelled
        overlay.remove();
        showDeletedConfirmation();
      } catch (error) { status.textContent = error.message; }
    });
  }

  function showDeletedConfirmation() {
    currentAccount = null;
    App.showScreen("account");
    document.getElementById("account-body").innerHTML = `
      <div class="account-section account-deleted">
        <h3 class="panel-sub">⚓ Account Deleted</h3>
        <p class="account-line">Yer account and its data have been sent to the deep. Fair winds, captain.</p>
        <p class="account-line"><button id="account-deleted-back" class="btn gold">Return to Port</button></p>
      </div>`;
    document.getElementById("account-deleted-back").addEventListener("click", () => App.showScreen("auth"));
  }

  document.addEventListener("DOMContentLoaded", () => {
    document.getElementById("btn-account-back")?.addEventListener("click", () => Lobby.enter());
  });

  window.Account = { enter, maybeOnboard };
})();
