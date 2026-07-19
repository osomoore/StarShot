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
  async function postZip(path, file) {
    const response = await fetch("/api/v2" + path, {
      method: "POST",
      body: file,
      headers: { "Content-Type": "application/zip" },
      credentials: "same-origin",
    });
    let payload = null;
    try { payload = await response.json(); } catch (err) { /* none */ }
    if (!response.ok) {
      const error = new Error((payload && payload.detail) || `Request failed (${response.status})`);
      error.status = response.status;
      throw error;
    }
    return payload;
  }
  async function downloadZip(path, fallbackName) {
    const response = await fetch("/api/v2" + path, { credentials: "same-origin" });
    if (!response.ok) {
      let payload = null;
      try { payload = await response.json(); } catch (err) { /* none */ }
      const error = new Error((payload && payload.detail) || `Request failed (${response.status})`);
      error.status = response.status;
      throw error;
    }
    const disposition = response.headers.get("Content-Disposition") || "";
    const match = /filename="?([^"]+)"?/i.exec(disposition);
    const filename = match ? match[1] : fallbackName;
    const url = URL.createObjectURL(await response.blob());
    const link = document.createElement("a");
    link.href = url;
    link.download = filename;
    document.body.appendChild(link);
    link.click();
    link.remove();
    URL.revokeObjectURL(url);
  }
  const esc = (value) => String(value ?? "").replace(/[&<>"']/g, (char) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#39;",
  }[char]));
  const shortDateTime = (value) => {
    if (!value) return "";
    const date = new Date(value);
    return Number.isNaN(date.getTime()) ? "" : date.toLocaleString();
  };

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
      await Promise.all([loadDeck(), loadKeywords(), loadSettings(), loadBattleHistory(), loadAccounts(), loadFeedback(), loadChangelog()]);
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
  let deckSets = [];
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
    deckSets = sets || [];
    const select = document.getElementById("deck-set-select");
    select.innerHTML = "";
    for (const deckSet of deckSets) {
      const option = document.createElement("option");
      option.value = deckSet.id;
      const changed = shortDateTime(deckSet.last_changed_at || deckSet.modified_at);
      option.textContent = (deckSet.active ? "⚓ " : "") + deckSet.name + (deckSet.custom ? " (custom)" : "") +
        (deckSet.deprecated ? " (deprecated)" : "") +
        (changed ? " - " + changed : "") + (deckSet.active ? " — active" : "");
      if (deckSet.active) option.selected = true;
      select.appendChild(option);
    }
    renderSelectedDeckSetMeta();
    renderBattleDeckSets();
  }

  function selectedDeckSet() {
    const id = document.getElementById("deck-set-select").value;
    return deckSets.find((deckSet) => deckSet.id === id) || null;
  }

  function renderSelectedDeckSetMeta() {
    const deckSet = selectedDeckSet();
    const meta = document.getElementById("deck-set-meta");
    const rename = document.getElementById("deck-rename-name");
    const deleteButton = document.getElementById("deck-delete");
    const deprecateButton = document.getElementById("deck-deprecate");
    if (!deckSet) {
      meta.textContent = "";
      rename.value = "";
      deleteButton.disabled = true;
      deleteButton.title = "Pick a custom deck set first";
      deprecateButton.disabled = true;
      deprecateButton.textContent = "Deprecate";
      deprecateButton.title = "Pick a deck set first";
      return;
    }
    rename.value = deckSet.name || "";
    deleteButton.disabled = !deckSet.custom || deckSet.active;
    deleteButton.title = deckSet.active
      ? "Make another deck set active before deleting this one"
      : (deckSet.custom ? "Delete this custom deck set" : "Stock deck sets cannot be deleted");
    deprecateButton.disabled = deckSet.active && !deckSet.deprecated;
    deprecateButton.textContent = deckSet.deprecated ? "Restore" : "Deprecate";
    deprecateButton.title = deckSet.active && !deckSet.deprecated
      ? "Make another deck set active before deprecating this one"
      : (deckSet.deprecated ? "Restore this deck set to normal selectors" : "Mark this deck set deprecated");
    const uploaded = shortDateTime(deckSet.uploaded_at);
    const modified = shortDateTime(deckSet.last_changed_at || deckSet.modified_at);
    meta.textContent = [
      `ID: ${deckSet.id}`,
      deckSet.custom ? "custom" : "stock",
      deckSet.deprecated ? "deprecated" : "",
      uploaded ? `uploaded ${uploaded}` : "",
      modified ? `last changed ${modified}` : "",
    ].filter(Boolean).join(" | ");
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
  document.getElementById("deck-set-select").addEventListener("change", renderSelectedDeckSetMeta);
  document.getElementById("deck-rename").addEventListener("click", async () => {
    const deckSet = selectedDeckSet();
    const name = document.getElementById("deck-rename-name").value.trim();
    if (!deckSet) { toast("Pick a deck set first"); return; }
    if (!name) { toast("Name the deck first"); return; }
    try {
      await post("/admin/deck/rename", { id: deckSet.id, name });
      toast("Deck set renamed", true);
      await loadDeck();
    } catch (error) {
      status("deck-status", "Rename failed: " + error.message, false);
    }
  });
  document.getElementById("deck-delete").addEventListener("click", async () => {
    const deckSet = selectedDeckSet();
    if (!deckSet) { toast("Pick a deck set first"); return; }
    if (!deckSet.custom) { toast("Stock deck sets cannot be deleted"); return; }
    if (deckSet.active) { toast("Make another deck set active before deleting this one"); return; }
    if (!confirm(`Delete deck set "${deckSet.name}" (${deckSet.id})? This cannot be undone.`)) return;
    status("deck-status", "Deleting deck set...", true);
    try {
      await del("/admin/deck/" + encodeURIComponent(deckSet.id));
      status("deck-status", `Deleted ${deckSet.name}.`, true);
      toast("Deck set deleted", true);
      await loadDeck();
    } catch (error) {
      status("deck-status", "Delete failed: " + error.message, false);
    }
  });
  document.getElementById("deck-deprecate").addEventListener("click", async () => {
    const deckSet = selectedDeckSet();
    if (!deckSet) { toast("Pick a deck set first"); return; }
    const deprecated = !deckSet.deprecated;
    if (deprecated && deckSet.active) { toast("Make another deck set active before deprecating this one"); return; }
    const verb = deprecated ? "Deprecate" : "Restore";
    if (!confirm(`${verb} deck set "${deckSet.name}" (${deckSet.id})?`)) return;
    status("deck-status", `${verb} deck set...`, true);
    try {
      await post("/admin/deck/deprecation", { id: deckSet.id, deprecated });
      status("deck-status", deprecated ? `${deckSet.name} is deprecated.` : `${deckSet.name} is restored.`, true);
      toast(deprecated ? "Deck set deprecated" : "Deck set restored", true);
      await loadDeck();
    } catch (error) {
      status("deck-status", `${verb} failed: ` + error.message, false);
    }
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
  document.getElementById("deck-export").addEventListener("click", async () => {
    const id = document.getElementById("deck-set-select").value;
    if (!id) { toast("Pick a deck set first"); return; }
    status("deck-status", "Preparing deck set zip...", true);
    try {
      await downloadZip(
        "/admin/deck/export/" + encodeURIComponent(id),
        "starshot-deck-set-" + id + ".zip"
      );
      status("deck-status", "Deck set download started.", true);
    } catch (error) {
      status("deck-status", "Download failed: " + error.message + " If this says Not Found, restart the server.", false);
    }
  });
  document.getElementById("deck-import").addEventListener("click", async () => {
    const input = document.getElementById("deck-import-file");
    const file = input.files && input.files[0];
    if (!file) { toast("Choose a deck set zip first"); return; }
    const activate = document.getElementById("deck-import-activate").checked ? "true" : "false";
    status("deck-status", "Validating upload...", true);
    try {
      const result = await postZip("/admin/deck/import?activate=" + activate, file);
      input.value = "";
      status(
        "deck-status",
        `Imported ${result.name} (${result.id})${result.activated ? " and made it active" : ""}.` +
          (result.keywords_imported ? " Custom keywords were updated from the bundle." : ""),
        true
      );
      toast("Deck set imported", true);
      await loadDeck();
    } catch (error) {
      status("deck-status", "Upload failed: " + error.message, false);
    }
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
  const AI_LABELS = { vault_runner: "📦 Freebooter (vault runner)", hunter_killer: "🎯 Bloodthirsty (hunter-killer)", blaster: "☄ Cannoneer (blaster)" };
  let battleEntries = [];
  let battleSort = { key: "created_at", dir: "desc" };

  function renderBattleDeckSets() {
    const select = document.getElementById("battle-deck-set");
    if (!select) return;
    const current = select.value;
    select.innerHTML = "";
    for (const deckSet of deckSets) {
      if (deckSet.deprecated && deckSet.id !== current) continue;
      const option = document.createElement("option");
      option.value = deckSet.id;
      option.textContent = deckSet.name + (deckSet.active ? " (active)" : "") +
        (deckSet.custom ? " (custom)" : "") + (deckSet.deprecated ? " (deprecated)" : "");
      option.disabled = !!deckSet.deprecated;
      if ((current && current === deckSet.id) || (!current && deckSet.active)) option.selected = true;
      select.appendChild(option);
    }
  }

  const n0 = (value) => Math.round(Number(value || 0));
  const n1 = (value) => (Number(value || 0)).toFixed(1);
  const pct = (value) => Math.round(Number(value || 0) * 100) + "%";
  const battleAiText = (entry) => (entry.ai_types || []).map((type) => (AI_LABELS[type] || type).replace(/^.. /, "")).join(" vs ");
  const battleSummaryValue = (entry, singleKey, batchKey) =>
    entry.kind === "batch" ? entry.summary[batchKey] : entry.summary[singleKey];

  function battleWinnerText(entry) {
    if (entry.kind === "batch") {
      const best = (entry.summary.ai_rankings || [])[0];
      return best ? `${best.ai_label}: ${best.wins} wins` : "-";
    }
    return (entry.summary.winner_names || []).join(", ") || "Tie";
  }

  function battleSortValue(entry, key) {
    if (key === "ai") return battleAiText(entry);
    if (key === "damage") return battleSummaryValue(entry, "total_damage_dealt", "average_damage_dealt") || 0;
    if (key === "kills") return battleSummaryValue(entry, "ships_killed", "average_ships_killed") || 0;
    if (key === "vaults") return battleSummaryValue(entry, "vaults_collected", "average_vaults_collected") || 0;
    if (key === "winner") return battleWinnerText(entry);
    if (key === "vp") return battleSummaryValue(entry, "total_vp", "average_total_vp") || 0;
    if (key === "rounds") return battleSummaryValue(entry, "rounds_played", "average_rounds") || 0;
    return entry[key] || "";
  }

  async function loadBattleHistory() {
    try {
      const data = await get("/admin/ai-battles");
      battleEntries = data.entries || [];
      renderBattleHistory();
    } catch (err) { /* not admin yet */ }
  }

  function renderBattleHistory() {
    const body = document.getElementById("battle-history-body");
    if (!body) return;
    const filter = (document.getElementById("battle-filter").value || "").trim().toLowerCase();
    let rows = battleEntries.filter((entry) => {
      const haystack = [entry.kind, entry.deck_set_name, battleAiText(entry), battleWinnerText(entry), entry.name].join(" ").toLowerCase();
      return !filter || haystack.includes(filter);
    });
    rows.sort((a, b) => {
      const av = battleSortValue(a, battleSort.key);
      const bv = battleSortValue(b, battleSort.key);
      const cmp = typeof av === "number" || typeof bv === "number"
        ? Number(av) - Number(bv)
        : String(av).localeCompare(String(bv));
      return battleSort.dir === "asc" ? cmp : -cmp;
    });
    body.innerHTML = rows.length ? "" : `<tr><td colspan="11" class="muted">No AI battle history yet.</td></tr>`;
    for (const entry of rows) {
      const tr = document.createElement("tr");
      const isBatch = entry.kind === "batch";
      tr.innerHTML = `
        <td>${new Date(entry.created_at).toLocaleString()}</td>
        <td>${isBatch ? `batch x${entry.run_count}` : "single"}</td>
        <td>${esc(entry.deck_set_name)}</td>
        <td>${esc(battleAiText(entry))}</td>
        <td>${isBatch ? n1(entry.summary.average_damage_dealt) : n0(entry.summary.total_damage_dealt)}</td>
        <td>${isBatch ? n1(entry.summary.average_ships_killed) : n0(entry.summary.ships_killed)}</td>
        <td>${isBatch ? n1(entry.summary.average_vaults_collected) : n0(entry.summary.vaults_collected)}</td>
        <td class="winner-cell">${esc(battleWinnerText(entry))}</td>
        <td>${isBatch ? n1(entry.summary.average_total_vp) : n0(entry.summary.total_vp)}</td>
        <td>${isBatch ? n1(entry.summary.average_rounds) : n0(entry.summary.rounds_played)}</td>
        <td></td>`;
      const actions = tr.lastElementChild;
      if (entry.game_id) {
        const replay = document.createElement("a");
        replay.className = "btn gold small";
        replay.href = "/v2?game=" + encodeURIComponent(entry.game_id);
        replay.target = "_blank";
        replay.textContent = "Replay";
        actions.appendChild(replay);
      }
      const detail = document.createElement("button");
      detail.className = "btn ghost small";
      detail.textContent = "Details";
      detail.addEventListener("click", () => openBattleDetail(entry.id));
      actions.appendChild(detail);
      body.appendChild(tr);
    }
  }

  async function openBattleDetail(entryId) {
    try {
      const { entry } = await get("/admin/ai-battles/" + encodeURIComponent(entryId));
      const overlay = document.getElementById("battle-detail-overlay");
      const isBatch = entry.kind === "batch";
      const s = entry.summary;
      const stat = (label, value) => `<div class="battle-stat"><b>${value}</b><span>${label}</span></div>`;
      const rankingRows = (isBatch ? s.ai_rankings || [] : s.players || []).map((row) => isBatch
        ? `<tr><td>${esc(row.ai_label)}</td><td>${row.wins}</td><td>${n1(row.average_vp)}</td><td>${n1(row.average_damage)}</td><td>${n1(row.average_kills)}</td><td>${n1(row.average_vaults)}</td><td>${pct(row.survival_rate)}</td></tr>`
        : `<tr><td>${esc(row.display_name)}</td><td>${esc(row.ai_label)}</td><td>${row.victory_points}</td><td>${row.damage_dealt}</td><td>${row.ships_killed}</td><td>${row.vaults_collected}</td><td>${row.destroyed ? "sunk" : "afloat"}</td></tr>`
      ).join("");
      const runRows = ((entry.detail && entry.detail.runs) || []).slice(0, 50).map((run, index) =>
        `<tr><td>${index + 1}</td><td>${esc((run.winner_names || []).join(", ") || "Tie")}</td><td>${run.total_damage_dealt}</td><td>${run.ships_killed}</td><td>${run.vaults_collected}</td><td>${run.total_vp}</td><td>${run.rounds_played}</td></tr>`
      ).join("");
      overlay.innerHTML = `
        <div class="battle-detail">
          <div class="battle-detail-head">
            <div>
              <h2 class="panel-title">${esc(entry.name)}</h2>
              <div class="admin-note">${esc(entry.deck_set_name)} - ${entry.kind} - ${entry.run_count} run${entry.run_count === 1 ? "" : "s"}</div>
            </div>
            <button class="btn ghost small" id="battle-detail-close">Close</button>
          </div>
          <div class="battle-detail-grid">
            ${stat(isBatch ? "avg damage" : "damage", isBatch ? n1(s.average_damage_dealt) : n0(s.total_damage_dealt))}
            ${stat(isBatch ? "avg kills" : "kills", isBatch ? n1(s.average_ships_killed) : n0(s.ships_killed))}
            ${stat(isBatch ? "avg vaults" : "vaults", isBatch ? n1(s.average_vaults_collected) : n0(s.vaults_collected))}
            ${stat(isBatch ? "avg total VP" : "total VP", isBatch ? n1(s.average_total_vp) : n0(s.total_vp))}
            ${stat(isBatch ? "avg rounds" : "rounds", isBatch ? n1(s.average_rounds) : n0(s.rounds_played))}
            ${stat("hit rate", pct(s.hit_rate))}
            ${stat(isBatch ? "avg volleys" : "volleys", isBatch ? n1(s.average_volleys) : n0(s.volley_count))}
            ${stat("environment dmg", isBatch ? n1(s.average_environmental_damage) : n0(s.environmental_damage))}
          </div>
          <h3 class="panel-sub">${isBatch ? "AI Style Ranking" : "Combatants"}</h3>
          <table class="leaderboard">
            <tr>${isBatch ? "<th>AI</th><th>Wins</th><th>Avg VP</th><th>Avg Dmg</th><th>Avg Kills</th><th>Avg Vaults</th><th>Survival</th>" : "<th>Name</th><th>AI</th><th>VP</th><th>Dmg</th><th>Kills</th><th>Vaults</th><th>Status</th>"}</tr>
            ${rankingRows}
          </table>
          ${isBatch ? `<h3 class="panel-sub">Run Samples</h3><table class="leaderboard"><tr><th>#</th><th>Winner</th><th>Dmg</th><th>Kills</th><th>Vaults</th><th>VP</th><th>Rounds</th></tr>${runRows}</table>` : ""}
          ${isBatch ? `<h3 class="panel-sub">Win Reasons</h3><pre>${esc(JSON.stringify(s.reason_counts || {}, null, 2))}</pre>` : ""}
        </div>`;
      overlay.classList.remove("hidden");
      document.getElementById("battle-detail-close").addEventListener("click", () => overlay.classList.add("hidden"));
      overlay.addEventListener("click", (event) => { if (event.target === overlay) overlay.classList.add("hidden"); }, { once: true });
    } catch (error) { toast(error.message); }
  }

  async function runAiBattle(batch) {
    const types = ["battle-ai-1", "battle-ai-2", "battle-ai-3", "battle-ai-4"]
      .map((id) => document.getElementById(id).value)
      .filter(Boolean);
    if (types.length < 2) { toast("Pick at least two combatants"); return; }
    const running = document.getElementById("battle-running");
    const singleButton = document.getElementById("run-battle");
    const batchButton = document.getElementById("run-battle-batch");
    singleButton.disabled = true;
    batchButton.disabled = true;
    running.classList.remove("hidden");
    status("battle-status", batch ? "Running batch..." : "Running replayable battle...", true);
    try {
      const payload = {
        ai_types: types,
        deck_set_id: document.getElementById("battle-deck-set").value || null,
      };
      let result;
      if (batch) {
        payload.run_count = parseInt(document.getElementById("battle-run-count").value, 10) || 100;
        result = await runAiBattleBatchJob(payload);
      } else {
        result = await post("/admin/ai-battle", payload);
      }
      status("battle-status", batch
        ? `Saved batch: ${result.run_count} runs, ${n1(result.average_damage_dealt)} avg damage. Opening details...`
        : `Saved replayable battle: ${battleWinnerText({ kind: "single", summary: result })} won.`, true);
      await loadBattleHistory();
      if (batch && result.history_entry && result.history_entry.id) {
        await openBattleDetail(result.history_entry.id);
      }
    } catch (error) {
      status("battle-status", error.message, false);
      toast(error.message);
    } finally {
      singleButton.disabled = false;
      batchButton.disabled = false;
      running.classList.add("hidden");
    }
  }

  async function runAiBattleBatchJob(payload) {
    const job = await post("/admin/ai-battle-batch/jobs", payload);
    status("battle-status", `Running batch: ${job.remaining} battles remaining of ${job.total}.`, true);
    while (true) {
      await new Promise((resolve) => setTimeout(resolve, 2000));
      const current = await get("/admin/ai-battle-batch/jobs/" + encodeURIComponent(job.id));
      if (current.status === "error") throw new Error(current.error || "Batch failed.");
      if (current.status === "complete") return current.result;
      status(
        "battle-status",
        `Running batch: ${current.remaining} battles remaining of ${current.total} (${current.completed} done).`,
        true
      );
    }
  }

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
    await runAiBattle(false);
    return;
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
  document.getElementById("run-battle-batch").addEventListener("click", () => runAiBattle(true));
  document.getElementById("battle-filter").addEventListener("input", renderBattleHistory);
  document.querySelectorAll("#battle-history-table th[data-sort]").forEach((head) => {
    head.addEventListener("click", () => {
      const key = head.dataset.sort;
      if (battleSort.key === key) battleSort.dir = battleSort.dir === "asc" ? "desc" : "asc";
      else battleSort = { key, dir: key === "created_at" ? "desc" : "asc" };
      renderBattleHistory();
    });
  });

  // feedback
  let feedbackEntries = [];
  const stars = (rating) => "★".repeat(Number(rating || 0)) + "☆".repeat(Math.max(0, 5 - Number(rating || 0)));
  function screenshotExtension(dataUrl) {
    const match = /^data:image\/([a-z0-9.+-]+);base64,/i.exec(dataUrl || "");
    const type = (match && match[1] || "png").toLowerCase();
    if (type === "svg+xml") return "svg";
    return type === "jpeg" ? "jpg" : type.replace(/[^a-z0-9]/g, "") || "png";
  }
  function screenshotBlock(entry) {
    if (!entry.is_bug_report) return "";
    if (!entry.screenshot_data_url) {
      return `<h4>Board Screenshot</h4><p class="feedback-screenshot-missing">No screenshot was captured for this bug report.</p>`;
    }
    const url = esc(entry.screenshot_data_url);
    const ext = screenshotExtension(entry.screenshot_data_url);
    const name = esc(`starshot-bug-${entry.id || "screenshot"}.${ext}`);
    return `<h4>Board Screenshot</h4>
      <div class="feedback-screenshot-actions">
        <a class="btn ghost small" href="${url}" target="_blank" rel="noopener">Open full size</a>
        <a class="btn ghost small" href="${url}" download="${name}">Download ${esc(ext.toUpperCase())}</a>
      </div>
      <a href="${url}" target="_blank" rel="noopener" title="Open screenshot full size">
        <img class="feedback-screenshot" src="${url}" alt="Bug report board screenshot">
      </a>`;
  }
  const feedbackText = (entry) => [
    entry.liked,
    entry.disliked,
    entry.thoughts,
    entry.is_bug_report ? "bug report game log" : "",
  ].filter(Boolean).join(" ").toLowerCase();

  // ── accounts ────────────────────────────────────────────────────────────
  let accountsData = { accounts: [], illegal_names: [] };

  async function loadAccounts() {
    try {
      const data = await get("/admin/accounts");
      accountsData = { accounts: data.accounts || [], illegal_names: data.illegal_names || [] };
      renderAccounts();
    } catch (err) { /* not admin yet */ }
  }

  function accountStatus(account) {
    const bits = [];
    if (account.must_rename) bits.push('<span class="bug-pill">RENAME DUE</span>');
    if (account.name_flagged && !account.must_rename) bits.push('<span class="bug-pill">FLAGGED NAME</span>');
    if (account.last_seen) bits.push(`seen ${shortDateTime(account.last_seen)}`);
    return bits.join(" ") || "—";
  }

  function renderAccounts() {
    const body = document.getElementById("accounts-body");
    if (!body) return;
    const filter = (document.getElementById("accounts-filter").value || "").trim().toLowerCase();
    const rows = accountsData.accounts.filter((account) =>
      !filter || `${account.username} ${account.display_name}`.toLowerCase().includes(filter));
    body.innerHTML = rows.length ? "" : `<tr><td colspan="9" class="muted">No accounts.</td></tr>`;
    for (const account of rows) {
      const tr = document.createElement("tr");
      tr.innerHTML = `
        <td>${esc(account.username)}</td>
        <td>${esc(account.display_name)}</td>
        <td>${account.wins}W / ${account.losses}L</td>
        <td>${account.games_played}</td>
        <td>${shortDateTime(account.created_at)}</td>
        <td>${accountStatus(account)}</td>`;
      const matchCell = document.createElement("td");
      const matchButton = document.createElement("button");
      matchButton.className = "btn small " + (account.matchmaking_ok ? "gold" : "ghost");
      matchButton.textContent = account.matchmaking_ok ? "On" : "Off";
      matchButton.title = "Toggle player matchmaking for this account";
      matchButton.addEventListener("click", () => setAccountFlags(account.id, { matchmaking_ok: !account.matchmaking_ok }));
      matchCell.appendChild(matchButton);
      tr.appendChild(matchCell);
      const boardCell = document.createElement("td");
      const boardButton = document.createElement("button");
      boardButton.className = "btn small " + (account.leaderboard_ok ? "gold" : "ghost");
      boardButton.textContent = account.leaderboard_ok ? "On" : "Off";
      boardButton.title = "Toggle leaderboard listing for this account";
      boardButton.addEventListener("click", () => setAccountFlags(account.id, { leaderboard_ok: !account.leaderboard_ok }));
      boardCell.appendChild(boardButton);
      tr.appendChild(boardCell);
      const actions = document.createElement("td");
      const ban = document.createElement("button");
      ban.className = "btn crimson small";
      ban.textContent = "Ban name";
      ban.title = "Add this account's display name to the illegal list and force a rename";
      ban.addEventListener("click", async () => {
        if (!confirm(`Ban the name "${account.display_name}"? Anyone wearing it must rename next time they reach the lobby.`)) return;
        try {
          const result = await post(`/admin/accounts/${account.id}/ban-name`);
          accountsData = { accounts: result.accounts || [], illegal_names: result.illegal_names || [] };
          renderAccounts();
          toast(`"${result.banned_name}" struck from the registry (${result.affected_accounts} account${result.affected_accounts === 1 ? "" : "s"}).`, true);
        } catch (error) { toast(error.message); }
      });
      actions.appendChild(ban);
      const remove = document.createElement("button");
      remove.className = "btn ghost small";
      remove.textContent = "☠ Delete";
      remove.title = "Permanently delete this account (non-admin only)";
      remove.addEventListener("click", () => openDeleteAccountModal(account));
      actions.appendChild(remove);
      tr.appendChild(actions);
      body.appendChild(tr);
    }
    const illegalNode = document.getElementById("illegal-names");
    if (!accountsData.illegal_names.length) {
      illegalNode.textContent = "None banned yet.";
    } else {
      illegalNode.innerHTML = "";
      for (const entry of accountsData.illegal_names) {
        const chip = document.createElement("span");
        chip.className = "illegal-name-chip";
        chip.innerHTML = `<b>${esc(entry.name)}</b>`;
        const remove = document.createElement("button");
        remove.className = "btn ghost small";
        remove.textContent = "✕";
        remove.title = "Remove from the illegal list";
        remove.addEventListener("click", async () => {
          try {
            const result = await del("/admin/illegal-names/" + encodeURIComponent(entry.name));
            accountsData.illegal_names = result.illegal_names || [];
            renderAccounts();
          } catch (error) { toast(error.message); }
        });
        chip.appendChild(remove);
        illegalNode.appendChild(chip);
      }
    }
  }

  function openDeleteAccountModal(account) {
    const overlay = document.createElement("div");
    overlay.className = "overlay";
    const providers = (account.providers || []).join(", ") || "none";
    overlay.innerHTML = `
      <div class="picker">
        <h3>☠ Delete Account</h3>
        <p class="admin-note"><b>This is destructive and cannot be undone.</b>
          Deleting removes the account, its saved ships and bosses, preferences,
          statistics, achievements, and leaderboard presence. Shared match
          histories are anonymized, not destroyed.</p>
        <p class="admin-note">Player name: <b>${esc(account.display_name)}</b> (${esc(account.username)})<br>
          Connected providers: <b>${esc(providers)}</b>${account.is_guest ? "<br><b>Temporary guest account.</b>" : ""}</p>
        <form id="admin-delete-form">
          <label>Type <b>DELETE</b> to confirm
            <input id="admin-delete-confirm" type="text" autocomplete="off" maxlength="20">
          </label>
          <div class="feedback-actions">
            <button type="button" class="btn ghost" id="admin-delete-cancel">Cancel</button>
            <button type="submit" class="btn crimson" id="admin-delete-submit" disabled>Delete Account</button>
          </div>
          <div id="admin-delete-status" class="admin-status"></div>
        </form>
      </div>`;
    document.body.appendChild(overlay);
    const input = overlay.querySelector("#admin-delete-confirm");
    const submit = overlay.querySelector("#admin-delete-submit");
    input.addEventListener("input", () => { submit.disabled = input.value.trim() !== "DELETE"; });
    overlay.querySelector("#admin-delete-cancel").addEventListener("click", () => overlay.remove());
    overlay.querySelector("#admin-delete-form").addEventListener("submit", async (event) => {
      event.preventDefault();
      if (input.value.trim() !== "DELETE") return;
      if (!confirm(`Final confirmation: permanently delete "${account.username}"?`)) return;
      try {
        const result = await post(`/admin/accounts/${account.id}/delete`, { confirm: "DELETE" });
        accountsData.accounts = result.accounts || [];
        overlay.remove();
        renderAccounts();
        toast("Account deleted and audit entry recorded.", true);
      } catch (error) {
        overlay.querySelector("#admin-delete-status").textContent = "✘ " + error.message;
      }
    });
  }

  async function setAccountFlags(userId, flags) {
    try {
      const result = await post(`/admin/accounts/${userId}/flags`, flags);
      accountsData.accounts = result.accounts || [];
      renderAccounts();
    } catch (error) { toast(error.message); }
  }

  document.getElementById("accounts-filter").addEventListener("input", renderAccounts);

  async function loadFeedback() {
    try {
      const data = await get("/admin/feedback");
      feedbackEntries = data.entries || [];
      renderFeedback();
    } catch (err) { /* not admin yet */ }
  }

  function renderFeedback() {
    const body = document.getElementById("feedback-body");
    if (!body) return;
    const filter = (document.getElementById("feedback-filter").value || "").trim().toLowerCase();
    const rows = feedbackEntries.filter((entry) => {
      const haystack = [entry.username, entry.rating, feedbackText(entry)].join(" ").toLowerCase();
      return !filter || haystack.includes(filter);
    });
    body.innerHTML = rows.length ? "" : `<tr><td colspan="4" class="muted">No feedback yet.</td></tr>`;
    for (const entry of rows) {
      const tr = document.createElement("tr");
      tr.className = "feedback-row" + (entry.is_bug_report ? " bug-report" : "");
      tr.innerHTML = `
        <td>${entry.is_bug_report ? '<span class="bug-pill">BUG</span> ' : ""}${esc(entry.username)}</td>
        <td><span class="feedback-rating">${stars(entry.rating)}</span></td>
        <td>${entry.feedback_count}</td>
        <td>${new Date(entry.created_at).toLocaleString()}</td>`;
      tr.addEventListener("click", () => openFeedbackDetail(entry.user_id));
      body.appendChild(tr);
    }
  }

  async function openFeedbackDetail(userId) {
    try {
      const data = await get("/admin/feedback/users/" + encodeURIComponent(userId));
      const detail = document.getElementById("feedback-detail");
      const entries = data.entries || [];
      detail.innerHTML = `
        <div class="feedback-detail-head">
          <h3 class="panel-sub">${esc(data.user.username)} - ${entries.length} repl${entries.length === 1 ? "y" : "ies"}</h3>
          ${entries.length ? `<button class="btn ghost small" id="feedback-delete-user" type="button">Delete all</button>` : ""}
        </div>
        ${entries.map((entry) => `
          <article class="feedback-entry" data-feedback-id="${esc(entry.id)}">
            <div class="feedback-entry-head">
              <span>${entry.is_bug_report ? '<span class="bug-pill">BUG REPORT</span> ' : ""}<span class="feedback-rating">${stars(entry.rating)}</span></span>
              <span class="feedback-entry-actions">
                <span>${new Date(entry.created_at).toLocaleString()}</span>
                <button class="btn ghost small feedback-delete-one" type="button" data-feedback-id="${esc(entry.id)}">Delete</button>
              </span>
            </div>
            ${entry.match_id || entry.game_id ? `<div class="feedback-context">${entry.match_id ? `Match ${esc(entry.match_id)}` : ""}${entry.match_id && entry.game_id ? " · " : ""}${entry.game_id ? `Game ${esc(entry.game_id)}` : ""}</div>` : ""}
            <h4>What I liked</h4>
            <p>${esc(entry.liked || "-")}</p>
            <h4>What I didn't like</h4>
            <p>${esc(entry.disliked || "-")}</p>
            <h4>General Thoughts</h4>
            <p>${esc(entry.thoughts || "-")}</p>
            ${screenshotBlock(entry)}
            ${entry.game_log ? `<h4>Included Game Log</h4><pre class="feedback-game-log">${esc(entry.game_log)}</pre>` : ""}
          </article>`).join("")}`;
      detail.querySelector("#feedback-delete-user")?.addEventListener("click", async () => {
        if (!confirm(`Delete all feedback from ${data.user.username}? This cannot be undone.`)) return;
        try {
          const result = await del("/admin/feedback/users/" + encodeURIComponent(userId));
          toast(`Deleted ${result.deleted || 0} feedback entr${Number(result.deleted || 0) === 1 ? "y" : "ies"}.`, true);
          await loadFeedback();
          openFeedbackDetail(userId);
        } catch (error) { toast(error.message); }
      });
      detail.querySelectorAll(".feedback-delete-one").forEach((button) => {
        button.addEventListener("click", async (event) => {
          event.stopPropagation();
          const feedbackId = button.dataset.feedbackId;
          if (!feedbackId || !confirm("Delete this feedback entry? This cannot be undone.")) return;
          try {
            await del("/admin/feedback/" + encodeURIComponent(feedbackId));
            toast("Feedback entry deleted.", true);
            await loadFeedback();
            openFeedbackDetail(userId);
          } catch (error) { toast(error.message); }
        });
      });
    } catch (error) { toast(error.message); }
  }

  document.getElementById("feedback-filter").addEventListener("input", renderFeedback);

  async function loadChangelog() {
    const textNode = document.getElementById("changelog-text");
    if (!textNode) return;
    try {
      const data = await get("/admin/ai-changelog");
      textNode.textContent = data.text || "No AI change log entries yet.";
      const meta = document.getElementById("changelog-meta");
      meta.textContent = [
        data.path,
        data.build_id ? `Build ${data.build_id}` : "",
        data.modified_at ? `updated ${shortDateTime(data.modified_at)}` : "",
      ].filter(Boolean).join(" | ");
      status("changelog-status", "", true);
    } catch (error) {
      textNode.textContent = "";
      status("changelog-status", error.message, false);
    }
  }

  const changelogRefresh = document.getElementById("changelog-refresh");
  if (changelogRefresh) changelogRefresh.addEventListener("click", loadChangelog);

  async function loadSettings() {
    try {
      const settings = await get("/admin/settings");
      document.getElementById("setting-site-auth").checked = !!settings.site_auth;
      document.getElementById("setting-maintenance").value = settings.maintenance || "";
      const rules = settings.rules_config || {};
      document.getElementById("setting-mixed-stacks").checked = !!rules.allow_mixed_card_type_stacks;
      document.getElementById("setting-overdrive-style").value = rules.overdrive_style || "copy_action";
      document.getElementById("setting-overdrive-desperation").checked = !!rules.allow_overdrive_desperation;
      renderStarBreachSettings(settings.star_breach || {});
      renderStarDockSettings(settings.stardock || {});
    } catch (err) { /* not admin yet */ }
  }

  const STARDOCK_FIELDS = [
    ["setting-stardock-max-tiles", "max_tiles"],
    ["setting-stardock-primary-limit", "primary_lane_limit"],
    ["setting-stardock-min-severed", "secondary_lane_min_severed"],
    ["setting-stardock-defense-bonus", "upgrade_defense_bonus"],
    ["setting-stardock-aim-bonus", "upgrade_aim_bonus"],
  ];

  function renderStarDockSettings(stardock) {
    for (const [elementId, key] of STARDOCK_FIELDS) {
      const input = document.getElementById(elementId);
      if (input && stardock[key] != null) input.value = stardock[key];
    }
  }

  function starDockSettingsBody() {
    const body = {};
    for (const [elementId, key] of STARDOCK_FIELDS) {
      const input = document.getElementById(elementId);
      if (input && input.value !== "") body["stardock_" + key] = parseInt(input.value, 10);
    }
    return body;
  }

  function renderStarBreachSettings(starBreach) {
    const bosses = starBreach.boss_designs || [];
    const allowed = new Set(starBreach.allowed_boss_design_ids || []);
    const defaultSelect = document.getElementById("setting-starbreach-default-boss");
    const allowedBox = document.getElementById("setting-starbreach-allowed-bosses");
    if (!defaultSelect || !allowedBox) return;
    defaultSelect.innerHTML = '<option value="">No default selected</option>' + bosses.map((boss) =>
      `<option value="${esc(boss.id)}">${esc(boss.name)} (${esc(boss.id)})</option>`
    ).join("");
    defaultSelect.value = starBreach.default_boss_design_id || "";
    allowedBox.innerHTML = bosses.length ? bosses.map((boss) => `
      <label>
        <input type="checkbox" value="${esc(boss.id)}" ${allowed.has(boss.id) ? "checked" : ""}>
        <span>${esc(boss.name)} <span class="deck-set-meta">(${esc(boss.id)})</span></span>
      </label>
    `).join("") : '<div class="deck-set-meta">No battle-ready global boss designs yet.</div>';
  }

  function selectedAllowedStarBreachBosses() {
    return Array.from(document.querySelectorAll("#setting-starbreach-allowed-bosses input[type='checkbox']:checked"))
      .map((input) => input.value);
  }

  document.getElementById("save-settings").addEventListener("click", async () => {
    try {
      const result = await post("/admin/settings", {
        site_auth: document.getElementById("setting-site-auth").checked,
        maintenance: document.getElementById("setting-maintenance").value,
        allow_mixed_card_type_stacks: document.getElementById("setting-mixed-stacks").checked,
        overdrive_style: document.getElementById("setting-overdrive-style").value,
        allow_overdrive_desperation: document.getElementById("setting-overdrive-desperation").checked,
        default_starbreach_boss_design_id: document.getElementById("setting-starbreach-default-boss").value,
        allowed_starbreach_boss_design_ids: selectedAllowedStarBreachBosses(),
        ...starDockSettingsBody(),
      });
      renderStarBreachSettings(result.star_breach || {});
      renderStarDockSettings(result.stardock || {});
      status("settings-status",
        `✔ Saved. Password gate: ${result.site_auth ? "ON" : "OFF"} · ` +
        (result.maintenance ? `under construction: "${result.maintenance}"` : "site open to all"), true);
      toast("Site settings saved", true);
    } catch (error) {
      status("settings-status", "✘ " + error.message, false);
    }
  });

  const btnServerUpdate = document.getElementById("btn-server-update");
  if (btnServerUpdate) {
    btnServerUpdate.addEventListener("click", async () => {
      btnServerUpdate.disabled = true;
      try {
        const res = await post("/admin/server-update");
        toast(res.note, true);
      } catch (error) {
        toast("Update failed: " + error.message);
      }
      btnServerUpdate.disabled = false;
    });
  }

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
