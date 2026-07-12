/* Admin console: deck editor, keyword manager, project download, password. */
(function () {
  async function call(path, options = {}) {
    const response = await fetch("/api/v2" + path, {
      headers: { "Content-Type": "application/json" },
      credentials: "same-origin",
      ...options,
    });
    let payload = null;
    try { payload = await response.json(); } catch (err) { /* binary/none */ }
    if (!response.ok) {
      const error = new Error((payload && payload.detail) || `Request failed (${response.status})`);
      error.status = response.status;
      throw error;
    }
    return payload;
  }
  const get = (p) => call(p);
  const post = (p, b) => call(p, { method: "POST", body: JSON.stringify(b || {}) });
  const put = (p, b) => call(p, { method: "PUT", body: JSON.stringify(b || {}) });
  const del = (p) => call(p, { method: "DELETE" });

  let toastTimer = null;
  function toast(message, good) {
    const node = document.getElementById("toast");
    node.textContent = message;
    node.className = "toast" + (good ? " good" : "");
    node.classList.remove("hidden");
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => node.classList.add("hidden"), 3600);
  }
  function status(id, message, ok) {
    const node = document.getElementById(id);
    node.textContent = message || "";
    node.className = "admin-status " + (ok ? "ok" : "err");
  }

  // ── gate ────────────────────────────────────────────────────────────────
  async function boot() {
    try {
      const me = await get("/me");
      if (!me.is_admin) {
        showLocked(`Signed in as ${me.user.username}, who is no admiral. Sign in with the admin account.`);
        return;
      }
      document.getElementById("admin-user").textContent = "⚙ " + me.user.username;
      document.getElementById("admin-locked").classList.add("hidden");
      document.getElementById("admin-main").classList.remove("hidden");
      await Promise.all([loadDeck(), loadKeywords(), loadSettings()]);
    } catch (err) {
      showLocked("Sign in as the admiral to enter.");
    }
  }
  function showLocked(reason) {
    document.getElementById("locked-reason").textContent = reason;
    document.getElementById("admin-locked").classList.remove("hidden");
    document.getElementById("admin-main").classList.add("hidden");
  }
  document.getElementById("admin-login-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const box = document.getElementById("admin-login-error");
    box.textContent = "";
    try {
      await post("/auth/login", {
        username: document.getElementById("admin-login-user").value.trim(),
        password: document.getElementById("admin-login-pass").value,
      });
      boot();
    } catch (error) { box.textContent = error.message; }
  });

  // tabs
  document.querySelectorAll(".admin-tab").forEach((tab) => {
    tab.addEventListener("click", () => {
      document.querySelectorAll(".admin-tab").forEach((t) => t.classList.toggle("active", t === tab));
      document.querySelectorAll(".admin-tabpage").forEach((page) => page.classList.add("hidden"));
      document.getElementById("tab-" + tab.dataset.tab).classList.remove("hidden");
    });
  });

  // ── deck editor ─────────────────────────────────────────────────────────
  const deckState = { base: null, desperation: null };
  const CARD_FIELDS = ["name", "copies", "side_a_type", "side_a_1", "side_a_2", "side_b_type", "side_b_1", "side_b_2"];

  async function loadDeck() {
    const data = await get("/admin/deck");
    document.getElementById("deck-path").textContent = data.deck_path;
    document.getElementById("deck-active-note").innerHTML =
      `Editing the <b>active</b> deck set: <b>${data.active_name || data.active_id || "?"}</b>. ` +
      `New games use the active set; battles in flight keep the set they started with. ` +
      `Use <i>Save current as…</i> before big experiments.`;
    deckState.base = data.base;
    deckState.desperation = data.desperation;
    renderDeckSets(data.sets || []);
    renderCards("base");
    renderCards("desperation");
  }

  function renderDeckSets(sets) {
    const select = document.getElementById("deck-set-select");
    select.innerHTML = "";
    for (const deckSet of sets) {
      const option = document.createElement("option");
      option.value = deckSet.id;
      option.textContent = (deckSet.active ? "⚓ " : "") + deckSet.name + (deckSet.custom ? " (custom)" : "") + (deckSet.active ? " — active" : "");
      if (deckSet.active) option.selected = true;
      select.appendChild(option);
    }
  }

  function renderCards(which) {
    const container = document.getElementById(which === "base" ? "base-cards" : "desp-cards");
    const cards = deckState[which].cards;
    container.innerHTML = "";
    const head = document.createElement("div");
    head.className = "card-head";
    head.innerHTML = "<span>Name</span><span>Copies</span><span>A type</span><span>Side A text</span><span>Side A alt</span><span>B type</span><span>Side B text</span><span>Side B alt</span><span></span>";
    container.appendChild(head);
    cards.forEach((card, index) => {
      const row = document.createElement("div");
      row.className = "card-row";
      const typeSelect = (field) => {
        const value = card[field] || "";
        return `<select data-field="${field}">
          <option value="" ${value === "" ? "selected" : ""}>—</option>
          <option ${value === "Basic" ? "selected" : ""}>Basic</option>
          <option ${value === "Desperate" ? "selected" : ""}>Desperate</option></select>`;
      };
      const input = (field, type) =>
        `<input data-field="${field}" type="${type || "text"}" value="${String(card[field] ?? "").replace(/"/g, "&quot;")}" ${type === "number" ? 'min="1" max="20"' : ""}>`;
      row.innerHTML = [
        input("name"), input("copies", "number"), typeSelect("side_a_type"), input("side_a_1"), input("side_a_2"),
        typeSelect("side_b_type"), input("side_b_1"), input("side_b_2"),
        `<span class="row-del" title="Remove card">✕</span>`,
      ].join("");
      row.querySelectorAll("[data-field]").forEach((node) => {
        node.addEventListener("change", () => {
          const field = node.dataset.field;
          card[field] = field === "copies" ? parseInt(node.value, 10) || 1 : node.value;
        });
      });
      row.querySelector(".row-del").addEventListener("click", () => {
        cards.splice(index, 1);
        renderCards(which);
      });
      container.appendChild(row);
    });
    const total = cards.reduce((sum, card) => sum + (parseInt(card.copies, 10) || 1), 0);
    document.getElementById(which === "base" ? "base-count" : "desp-count").textContent =
      `— ${cards.length} entries, ${total} cards`;
  }

  function cleanCards(cards) {
    return cards.map((card) => {
      const cleaned = {};
      for (const field of CARD_FIELDS) {
        const value = card[field];
        if (value === "" || value === null || value === undefined) continue;
        cleaned[field] = field === "copies" ? parseInt(value, 10) || 1 : value;
      }
      for (const key of Object.keys(card)) if (!CARD_FIELDS.includes(key)) cleaned[key] = card[key];
      return cleaned;
    });
  }

  async function saveDeck(which) {
    status("deck-status", "Validating…", true);
    try {
      const result = await put("/admin/deck", {
        which,
        header: deckState[which].header,
        cards: cleanCards(deckState[which].cards),
      });
      status("deck-status", "✔ " + result.note, true);
      toast("Deck saved", true);
      await loadDeck();
    } catch (error) {
      status("deck-status", "✘ " + error.message, false);
    }
  }

  document.getElementById("save-base").addEventListener("click", () => saveDeck("base"));
  document.getElementById("save-desp").addEventListener("click", () => saveDeck("desperation"));
  document.getElementById("deck-set-activate").addEventListener("click", async () => {
    const id = document.getElementById("deck-set-select").value;
    try {
      await post("/admin/deck/activate", { id });
      toast("Deck set activated — new games will use it", true);
      await loadDeck();
    } catch (error) { toast(error.message); }
  });
  document.getElementById("deck-saveas").addEventListener("click", async () => {
    const name = document.getElementById("deck-saveas-name").value.trim();
    if (!name) { toast("Name the deck first"); return; }
    try {
      const result = await post("/admin/deck/save-as", { name });
      document.getElementById("deck-saveas-name").value = "";
      toast(`Saved as "${name}" (${result.id})`, true);
      await loadDeck();
    } catch (error) { toast(error.message); }
  });
  document.getElementById("add-base-card").addEventListener("click", () => {
    deckState.base.cards.push({ name: "New Card", copies: 1, side_a_type: "Basic", side_a_1: "Move 2" });
    renderCards("base");
  });
  document.getElementById("add-desp-card").addEventListener("click", () => {
    deckState.desperation.cards.push({ name: "New Card", copies: 1, side_a_type: "Basic", side_a_1: "Move 2", side_b_type: "Desperate", side_b_1: "Move 5" });
    renderCards("desperation");
  });

  // ── keyword manager ─────────────────────────────────────────────────────
  let editingOriginalName = null;

  async function loadKeywords() {
    const data = await get("/admin/keywords");
    const customs = document.getElementById("custom-keywords");
    customs.innerHTML = data.customs.length ? "" : '<div class="admin-note">No custom keywords yet — copy a built-in to start.</div>';
    for (const entry of data.customs) {
      customs.appendChild(keywordRow(entry, false));
    }
    const builtins = document.getElementById("builtin-keywords");
    builtins.innerHTML = "";
    for (const entry of data.builtins) {
      builtins.appendChild(keywordRow(entry, true));
    }
  }

  function keywordRow(entry, builtin) {
    const row = document.createElement("div");
    row.className = "kw-row";
    row.innerHTML = `
      <div class="kw-meta">
        <div class="kw-name">${entry.name}${entry.enabled === false ? " (disabled)" : ""}</div>
        <div class="kw-pattern">${entry.pattern.replace(/</g, "&lt;")}</div>
        ${entry.problem ? `<div class="kw-problem">⚠ ${entry.problem}</div>` : ""}
      </div>
      <div class="kw-actions"></div>`;
    const actions = row.querySelector(".kw-actions");
    const copyButton = document.createElement("button");
    copyButton.className = "btn ghost small";
    copyButton.textContent = "⧉ Copy";
    copyButton.addEventListener("click", () => openEditor({
      name: entry.name + " (copy)", pattern: entry.pattern, code: entry.code, enabled: true,
    }, null));
    actions.appendChild(copyButton);
    if (!builtin) {
      const editButton = document.createElement("button");
      editButton.className = "btn ghost small";
      editButton.textContent = "✎ Edit";
      editButton.addEventListener("click", () => openEditor(entry, entry.name));
      const deleteButton = document.createElement("button");
      deleteButton.className = "btn ghost small";
      deleteButton.textContent = "🗑";
      deleteButton.addEventListener("click", async () => {
        try {
          await del("/admin/keywords/" + encodeURIComponent(entry.name));
          toast("Keyword removed", true);
          loadKeywords();
        } catch (error) { toast(error.message); }
      });
      actions.appendChild(editButton);
      actions.appendChild(deleteButton);
    } else {
      const tag = document.createElement("span");
      tag.className = "brand-tag";
      tag.textContent = "built-in";
      actions.appendChild(tag);
    }
    return row;
  }

  function openEditor(entry, originalName) {
    editingOriginalName = originalName;
    document.getElementById("kw-editor-title").textContent = originalName ? "Edit keyword" : "New keyword";
    document.getElementById("kw-name").value = entry.name || "";
    document.getElementById("kw-pattern").value = entry.pattern || "";
    document.getElementById("kw-code").value = entry.code || "spec = FaceSpec(family=CardFamily.MOVE, value=int(match.group(1)), requires_target=False)";
    document.getElementById("kw-test-result").textContent = "";
    document.getElementById("keyword-editor").classList.remove("hidden");
    document.getElementById("kw-name").focus();
  }

  document.getElementById("new-keyword").addEventListener("click", () => openEditor({
    name: "", pattern: "my keyword (\\d+)", code: "",
  }, null));
  document.getElementById("kw-cancel").addEventListener("click", () => {
    document.getElementById("keyword-editor").classList.add("hidden");
  });
  document.getElementById("kw-test").addEventListener("click", async () => {
    const result = document.getElementById("kw-test-result");
    try {
      const outcome = await post("/admin/keywords/test", {
        pattern: document.getElementById("kw-pattern").value,
        code: document.getElementById("kw-code").value,
        sample: document.getElementById("kw-sample").value,
      });
      if (outcome.error) result.textContent = "✘ " + outcome.error;
      else if (!outcome.matched) result.textContent = "— pattern did not match that text";
      else result.textContent = "✔ matched → FaceSpec " + JSON.stringify(outcome.spec, null, 1);
    } catch (error) { result.textContent = "✘ " + error.message; }
  });
  document.getElementById("kw-save").addEventListener("click", async () => {
    try {
      const name = document.getElementById("kw-name").value.trim();
      if (editingOriginalName && editingOriginalName !== name) {
        await del("/admin/keywords/" + encodeURIComponent(editingOriginalName)).catch(() => {});
      }
      await post("/admin/keywords", {
        name,
        pattern: document.getElementById("kw-pattern").value,
        code: document.getElementById("kw-code").value,
        enabled: true,
      });
      document.getElementById("keyword-editor").classList.add("hidden");
      status("keyword-status", "✔ Keyword saved — decks reload with it immediately.", true);
      toast("Keyword saved", true);
      loadKeywords();
    } catch (error) {
      status("keyword-status", "✘ " + error.message, false);
    }
  });

  // ── AI battle arena ─────────────────────────────────────────────────────
  const AI_LABELS = { bauble_runner: "💰 Salvage (bauble runner)", hunter_killer: "🗡 Corsair (hunter-killer)", blaster: "💥 Gunner (blaster)" };
  (function initBattleSelectors() {
    ["battle-ai-1", "battle-ai-2", "battle-ai-3", "battle-ai-4"].forEach((id, index) => {
      const select = document.getElementById(id);
      for (const type of Object.keys(AI_LABELS)) {
        const option = document.createElement("option");
        option.value = type;
        option.textContent = AI_LABELS[type];
        select.appendChild(option);
      }
      if (index === 0) select.value = "hunter_killer";
      if (index === 1) select.value = "blaster";
    });
  })();

  document.getElementById("run-battle").addEventListener("click", async () => {
    const types = ["battle-ai-1", "battle-ai-2", "battle-ai-3", "battle-ai-4"]
      .map((id) => document.getElementById(id).value)
      .filter(Boolean);
    if (types.length < 2) { toast("Pick at least two combatants"); return; }
    const button = document.getElementById("run-battle");
    const running = document.getElementById("battle-running");
    button.disabled = true;
    running.classList.remove("hidden");
    try {
      const result = await post("/admin/ai-battle", { ai_types: types });
      const winners = new Set(result.winners);
      const rows = result.players
        .sort((a, b) => b.victory_points - a.victory_points)
        .map((player) => `<tr class="${winners.has(player.player_id) ? "winner" : ""}">
            <td>${winners.has(player.player_id) ? "👑" : ""}</td>
            <td>${player.display_name}</td><td>${player.ai_type}</td>
            <td>${player.victory_points} VP</td><td>${player.destroyed ? "☠ sunk" : "afloat"}</td>
          </tr>`).join("");
      const box = document.createElement("div");
      box.className = "battle-result";
      box.innerHTML = `
        <h3 class="panel-sub">Battle decided — ${result.reason || "?"} (rounds: ${result.rounds_played})</h3>
        <table class="leaderboard">${rows}</table>
        <a class="btn gold small" href="/v2?game=${result.game_id}" target="_blank">👁 Watch the replay</a>`;
      const container = document.getElementById("battle-results");
      container.insertBefore(box, container.firstChild);
    } catch (error) {
      toast(error.message);
    } finally {
      button.disabled = false;
      running.classList.add("hidden");
    }
  });

  // ── site settings ───────────────────────────────────────────────────────
  async function loadSettings() {
    try {
      const settings = await get("/admin/settings");
      document.getElementById("setting-site-auth").checked = !!settings.site_auth;
      document.getElementById("setting-maintenance").value = settings.maintenance || "";
      const rules = settings.rules_config || {};
      document.getElementById("setting-mixed-stacks").checked = !!rules.allow_mixed_card_type_stacks;
      document.getElementById("setting-overdrive-style").value = rules.overdrive_style || "copy_action";
      document.getElementById("setting-overdrive-desperation").checked = !!rules.allow_overdrive_desperation;
    } catch (err) { /* not admin yet */ }
  }
  document.getElementById("save-settings").addEventListener("click", async () => {
    try {
      const result = await post("/admin/settings", {
        site_auth: document.getElementById("setting-site-auth").checked,
        maintenance: document.getElementById("setting-maintenance").value,
        allow_mixed_card_type_stacks: document.getElementById("setting-mixed-stacks").checked,
        overdrive_style: document.getElementById("setting-overdrive-style").value,
        allow_overdrive_desperation: document.getElementById("setting-overdrive-desperation").checked,
      });
      status("settings-status",
        `✔ Saved. Password gate: ${result.site_auth ? "ON" : "OFF"} · ` +
        (result.maintenance ? `under construction: "${result.maintenance}"` : "site open to all"), true);
      toast("Site settings saved", true);
    } catch (error) {
      status("settings-status", "✘ " + error.message, false);
    }
  });

  // ── account ─────────────────────────────────────────────────────────────
  document.getElementById("pw-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    try {
      await post("/auth/password", {
        current_password: document.getElementById("pw-current").value,
        new_password: document.getElementById("pw-new").value,
      });
      status("account-status", "✔ Password changed.", true);
      document.getElementById("pw-current").value = "";
      document.getElementById("pw-new").value = "";
    } catch (error) {
      status("account-status", "✘ " + error.message, false);
    }
  });

  boot();
})();
