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
  const esc = (value) => String(value ?? "").replace(/[&<>"']/g, (char) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#39;",
  }[char]));

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
      await Promise.all([loadDeck(), loadKeywords(), loadSettings(), loadBattleHistory()]);
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
      option.textContent = (deckSet.active ? "⚓ " : "") + deckSet.name + (deckSet.custom ? " (custom)" : "") + (deckSet.active ? " — active" : "");
      if (deckSet.active) option.selected = true;
      select.appendChild(option);
    }
    renderBattleDeckSets();
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
  let battleEntries = [];
  let battleSort = { key: "created_at", dir: "desc" };

  function renderBattleDeckSets() {
    const select = document.getElementById("battle-deck-set");
    if (!select) return;
    const current = select.value;
    select.innerHTML = "";
    for (const deckSet of deckSets) {
      const option = document.createElement("option");
      option.value = deckSet.id;
      option.textContent = deckSet.name + (deckSet.active ? " (active)" : "") + (deckSet.custom ? " (custom)" : "");
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
    if (key === "baubles") return battleSummaryValue(entry, "baubles_collected", "average_baubles_collected") || 0;
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
        <td>${isBatch ? n1(entry.summary.average_baubles_collected) : n0(entry.summary.baubles_collected)}</td>
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
        ? `<tr><td>${esc(row.ai_label)}</td><td>${row.wins}</td><td>${n1(row.average_vp)}</td><td>${n1(row.average_damage)}</td><td>${n1(row.average_kills)}</td><td>${n1(row.average_baubles)}</td><td>${pct(row.survival_rate)}</td></tr>`
        : `<tr><td>${esc(row.display_name)}</td><td>${esc(row.ai_label)}</td><td>${row.victory_points}</td><td>${row.damage_dealt}</td><td>${row.ships_killed}</td><td>${row.baubles_collected}</td><td>${row.destroyed ? "sunk" : "afloat"}</td></tr>`
      ).join("");
      const runRows = ((entry.detail && entry.detail.runs) || []).slice(0, 50).map((run, index) =>
        `<tr><td>${index + 1}</td><td>${esc((run.winner_names || []).join(", ") || "Tie")}</td><td>${run.total_damage_dealt}</td><td>${run.ships_killed}</td><td>${run.baubles_collected}</td><td>${run.total_vp}</td><td>${run.rounds_played}</td></tr>`
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
            ${stat(isBatch ? "avg baubles" : "baubles", isBatch ? n1(s.average_baubles_collected) : n0(s.baubles_collected))}
            ${stat(isBatch ? "avg total VP" : "total VP", isBatch ? n1(s.average_total_vp) : n0(s.total_vp))}
            ${stat(isBatch ? "avg rounds" : "rounds", isBatch ? n1(s.average_rounds) : n0(s.rounds_played))}
            ${stat("hit rate", pct(s.hit_rate))}
            ${stat(isBatch ? "avg volleys" : "volleys", isBatch ? n1(s.average_volleys) : n0(s.volley_count))}
            ${stat("environment dmg", isBatch ? n1(s.average_environmental_damage) : n0(s.environmental_damage))}
          </div>
          <h3 class="panel-sub">${isBatch ? "AI Style Ranking" : "Combatants"}</h3>
          <table class="leaderboard">
            <tr>${isBatch ? "<th>AI</th><th>Wins</th><th>Avg VP</th><th>Avg Dmg</th><th>Avg Kills</th><th>Avg Baubles</th><th>Survival</th>" : "<th>Name</th><th>AI</th><th>VP</th><th>Dmg</th><th>Kills</th><th>Baubles</th><th>Status</th>"}</tr>
            ${rankingRows}
          </table>
          ${isBatch ? `<h3 class="panel-sub">Run Samples</h3><table class="leaderboard"><tr><th>#</th><th>Winner</th><th>Dmg</th><th>Kills</th><th>Baubles</th><th>VP</th><th>Rounds</th></tr>${runRows}</table>` : ""}
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
