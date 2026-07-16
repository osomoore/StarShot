/* Game screen: state polling, order building, round replay with effects. */
(function () {
  const POLL_MS = 2500;
  const esc = (value) => Cards.escapeHtml(value);

  let gameId = null;
  let view = null;          // latest redacted state
  let match = null;
  let you = null;
  let lastVersion = -1;
  let animatedUpTo = 0;
  let pollTimer = null;
  let animating = false;
  let replayShipStates = null;
  let replayBossPose = null;
  let replayFleetPose = null; // craft_id -> {q, r, destroyed} while replaying
  let replayBossState = null; // rewound boss board state, rolled forward per event
  let replayOrders = null;    // your submitted stacks for the round being replayed
  let replayOrdersByRound = null;
  let endgameShown = false;
  let draft = null;
  let pendingFetch = false;
  let sideTab = "registry";
  const scenarioStatusSignatures = new Map();
  const scenarioStatusTimers = new Map();

  const els = {};
  function grab() {
    for (const id of ["game-banner", "fleet-list", "action-log", "order-slots", "hand-area",
      "btn-submit-orders", "btn-clear-orders", "orders-hint", "deck-count", "discard-count",
      "picker-overlay", "endgame-overlay", "board-callout", "board-wrap", "orders-panel"]) {
      els[id] = document.getElementById(id);
    }
    els["fleet-panel"] = document.querySelector(".fleet-panel");
    document.querySelectorAll("[data-side-tab]").forEach((button) => {
      if (button.dataset.boundSideTab === "1") return;
      button.dataset.boundSideTab = "1";
      button.addEventListener("click", () => setSideTab(button.dataset.sideTab || "registry"));
    });
    setSideTab(sideTab);
  }

  function setSideTab(tab) {
    const previous = sideTab;
    sideTab = tab === "log" ? "log" : "registry";
    document.querySelectorAll("[data-side-tab]").forEach((button) => {
      const active = button.dataset.sideTab === sideTab;
      button.classList.toggle("active", active);
      button.setAttribute("aria-selected", String(active));
    });
    document.querySelectorAll(".side-tab-panel").forEach((panel) => {
      panel.classList.toggle("active", panel.id === `fleet-tab-panel-${sideTab}`);
    });
    if (sideTab === "log" && previous !== "log") scrollLogToBottom();
  }

  function scrollLogToBottom() {
    const container = els["action-log"];
    if (!container) return;
    requestAnimationFrame(() => {
      container.scrollTop = container.scrollHeight;
    });
  }

  function isPhoneUser() {
    const coarsePointer = window.matchMedia?.("(pointer: coarse)")?.matches;
    const anyCoarsePointer = window.matchMedia?.("(any-pointer: coarse)")?.matches;
    const narrow = window.matchMedia?.("(max-width: 760px)")?.matches;
    const tabletViewport = window.matchMedia?.("(max-width: 1366px)")?.matches;
    const compactHeight = window.matchMedia?.("(max-height: 620px)")?.matches;
    const mobileAgent = /Android|iPhone|iPod|IEMobile|Mobile/i.test(navigator.userAgent || "");
    const touchCapable = (navigator.maxTouchPoints || 0) > 0;
    return Boolean(
      ((coarsePointer || anyCoarsePointer || touchCapable) && tabletViewport)
      || (mobileAgent && (narrow || compactHeight)),
    );
  }

  function applyMobileMode() {
    const phone = isPhoneUser();
    document.documentElement.dataset.device = phone ? "phone" : "desktop";
    App.reportDeviceDiagnostics?.("v2-game-mobile-mode");
    if (!phone) {
      setMobileSheet(null);
      return;
    }
    ensureMobileHud();
    syncMobileHud();
  }

  function ensureMobileHud() {
    if (!document.getElementById("mobile-game-hud")) {
      const hud = document.createElement("nav");
      hud.id = "mobile-game-hud";
      hud.className = "mobile-game-hud";
      hud.setAttribute("aria-label", "Mobile game controls");
      hud.innerHTML = `
        <button class="btn ghost" type="button" data-mobile-action="orders">Orders</button>
        <button class="btn ghost" type="button" data-mobile-action="fleet">Fleet</button>
        <button class="btn gold" type="button" data-mobile-action="map">Map</button>
      `;
      hud.addEventListener("click", (event) => {
        const action = event.target.closest("[data-mobile-action]")?.dataset.mobileAction;
        if (action === "orders") toggleMobileOrders();
        if (action === "fleet") toggleMobileFleet();
        if (action === "map") showMobileMap();
      });
      document.body.appendChild(hud);
    }
    if (!document.getElementById("mobile-orders-close") && els["orders-panel"]) {
      const close = document.createElement("button");
      close.id = "mobile-orders-close";
      close.className = "btn ghost small mobile-orders-close";
      close.type = "button";
      close.textContent = "Map";
      close.addEventListener("click", () => setMobileSheet(null));
      els["orders-panel"].prepend(close);
    }
  }

  function syncMobileHud() {
    const hud = document.getElementById("mobile-game-hud");
    if (!hud) return;
    const active = document.body.classList.contains("mobile-orders-open")
      ? "orders"
      : document.body.classList.contains("mobile-fleet-open") ? "fleet" : "map";
    hud.querySelectorAll("[data-mobile-action]").forEach((button) => {
      const pressed = button.dataset.mobileAction === active;
      button.classList.toggle("gold", pressed);
      button.classList.toggle("ghost", !pressed);
      button.setAttribute("aria-pressed", String(pressed));
    });
  }

  function toggleMobileOrders() {
    setMobileSheet(document.body.classList.contains("mobile-orders-open") ? null : "orders");
  }

  function toggleMobileFleet() {
    setMobileSheet(document.body.classList.contains("mobile-fleet-open") ? null : "fleet");
  }

  function setMobileSheet(sheet) {
    document.body.classList.toggle("mobile-orders-open", sheet === "orders");
    document.body.classList.toggle("mobile-fleet-open", sheet === "fleet");
    syncMobileHud();
  }

  function showMobileMap() {
    targetResolver = null;
    setMobileSheet(null);
    hidePicker();
  }

  function emptyDraft() {
    return { slots: [newSlot(), newSlot(), newSlot()] };
  }
  function newSlot() { return { seal: "sealed", cards: [] }; }

  function draftStorageKey() {
    if (!gameId || !you || !view) return null;
    return `ss_draft_${gameId}_${you}_${view.round_number || 0}`;
  }

  function orderTraceKey() {
    return gameId ? `ss_order_trace_${gameId}` : "ss_order_trace";
  }

  function orderTrace(event, details = {}) {
    if (!view || view.phase !== "give_orders") return;
    const me = view.players?.[you] || null;
    const entry = {
      at: new Date().toISOString(),
      event,
      game_id: gameId,
      player_id: you,
      phase: view.phase,
      round_number: view.round_number,
      details: {
        submitted: !!me?.has_submitted_orders,
        hand_count: (me?.hand || []).length,
        draft_counts: (draft?.slots || []).map((slot) => (slot.cards || []).length),
        ...details,
      },
    };
    try {
      const key = orderTraceKey();
      const recent = JSON.parse(localStorage.getItem(key) || "[]");
      recent.push(entry);
      localStorage.setItem(key, JSON.stringify(recent.slice(-40)));
    } catch (err) {}
    try {
      API.clientEvent?.({
        app: "v2",
        event: "order." + event,
        game_id: gameId,
        player_id: you,
        phase: view.phase,
        round_number: view.round_number,
        details: entry.details,
      });
    } catch (err) {}
  }

  /* playEvents() drives a long async animation loop; if anything in it throws
     (a rendering bug, an unexpected event shape, …), every call site below
     awaits or chains off it without a catch, so the corrective final
     renderAll() would silently never run and the UI would stay frozen mid-
     replay. Route every call through here so a broken replay always still
     ends with a renderAll() that snaps the UI back to the true server state. */
  async function playEventsSafely(events) {
    try {
      await playEvents(events);
    } catch (error) {
      console.error("StarShot: replay animation failed; snapping to current state.", error);
    }
  }

  function canBuildOrders(player = myPlayer()) {
    return view && view.phase === "give_orders" && player
      && !player.has_submitted_orders && !player.eliminated && !(player.ship || {}).destroyed;
  }

  function serializeDraft() {
    return {
      slots: (draft?.slots || []).map((slot) => ({
        seal: slot.seal === "overdrive" ? "overdrive" : "sealed",
        cards: (slot.cards || []).map((selection) => ({
          card_id: selection.card_id,
          face: selection.face,
          orientation: selection.orientation,
          mode: selection.mode,
          target_player_id: selection.target_player_id,
          repair_component_ids: selection.repair_component_ids || [],
          reconfigure_from_component_ids: selection.reconfigure_from_component_ids || [],
          reconfigure_to_component_ids: selection.reconfigure_to_component_ids || [],
          ace_lane_preference: selection.ace_lane_preference ?? null,
          family: selection.family,
        })),
      })),
    };
  }

  function hydrateDraft(saved, hand) {
    if (!saved || !Array.isArray(saved.slots) || saved.slots.length !== 3) return null;
    const handById = new Map((hand || []).map((card) => [card.id, card]));
    const seen = new Set();
    const slots = [];
    for (const savedSlot of saved.slots) {
      if (!savedSlot || !Array.isArray(savedSlot.cards) || savedSlot.cards.length > 2) return null;
      const cards = [];
      for (const selection of savedSlot.cards) {
        const card = handById.get(selection.card_id);
        if (!card || seen.has(card.id)) return null;
        seen.add(card.id);
        cards.push({
          card_id: card.id,
          face: selection.face === "desperate" ? "desperate" : "front",
          orientation: selection.orientation || "up",
          mode: selection.mode || null,
          target_player_id: selection.target_player_id || null,
          repair_component_ids: Array.isArray(selection.repair_component_ids) ? selection.repair_component_ids : [],
          reconfigure_from_component_ids: Array.isArray(selection.reconfigure_from_component_ids) ? selection.reconfigure_from_component_ids : [],
          reconfigure_to_component_ids: Array.isArray(selection.reconfigure_to_component_ids) ? selection.reconfigure_to_component_ids : [],
          ace_lane_preference: Number.isInteger(selection.ace_lane_preference) ? selection.ace_lane_preference : null,
          card,
          family: selection.family || card.family || card.effect?.family || null,
        });
      }
      slots.push({ seal: savedSlot.seal === "overdrive" ? "overdrive" : "sealed", cards });
    }
    return { slots };
  }

  function draftHasChoices() {
    return (draft?.slots || []).some((slot) => slot.seal === "overdrive" || (slot.cards || []).length);
  }

  function saveDraft() {
    const key = draftStorageKey();
    if (!key) return;
    try {
      if (!canBuildOrders() || !draftHasChoices()) localStorage.removeItem(key);
      else localStorage.setItem(key, JSON.stringify(serializeDraft()));
    } catch (err) {}
  }

  function restoreDraftIfAvailable() {
    const me = myPlayer();
    const key = draftStorageKey();
    if (!key || !canBuildOrders(me)) {
      draft = emptyDraft();
      if (key) {
        try { localStorage.removeItem(key); } catch (err) {}
      }
      return;
    }
    if (draftHasChoices()) return;
    try {
      const raw = localStorage.getItem(key);
      const restored = raw ? hydrateDraft(JSON.parse(raw), me.hand || []) : null;
      if (restored) {
        draft = restored;
        orderTrace("draft_restored", { card_ids: draft.slots.flatMap((slot) => slot.cards.map((card) => card.card_id)) });
      } else if (raw) {
        localStorage.removeItem(key);
        orderTrace("draft_restore_rejected");
      }
    } catch (err) {
      try { localStorage.removeItem(key); } catch (ignore) {}
      orderTrace("draft_restore_failed", { message: err.message || String(err) });
    }
  }

  // ── entry / polling ────────────────────────────────────────────────────
  async function enter(id) {
    grab();
    applyMobileMode();
    gameId = id;
    view = null; match = null; lastVersion = -1; endgameShown = false;
    draft = emptyDraft();
    armedSlot = null;
    // Persistent per-game cursor: how much of the battle this browser has
    // already watched. Anything beyond it replays as a catch-up when you
    // come back to a match (with a Skip button).
    animatedUpTo = parseInt(localStorage.getItem("ss_seen_" + id) || "-1", 10);
    App.showScreen("game");
    document.body.classList.add("mobile-game-active");
    Board.build();
    Board.setShipClickHandler(handleShipClick);
    Board.setBossClickHandler(handleBossClick);
    if (document.documentElement.dataset.device === "phone") Board.resetView?.();
    await fetchView(true);
    if (pollTimer) clearInterval(pollTimer);
    pollTimer = setInterval(() => fetchView(false), POLL_MS);
  }

  function leave() {
    if (pollTimer) clearInterval(pollTimer);
    pollTimer = null;
    gameId = null;
    document.body.classList.remove("mobile-game-active");
    setMobileSheet(null);
  }

  async function fetchView(initial) {
    if (!gameId || pendingFetch) return;
    pendingFetch = true;
    try {
      const payload = await API.gameView(gameId, lastVersion);
      if (payload.unchanged) return;
      applyPayload(payload, initial);
    } catch (error) {
      if (error.status === 401) App.showScreen("auth");
      else if (initial) App.toast(error.message);
    } finally {
      pendingFetch = false;
    }
  }

  function applyPayload(payload, initial) {
    view = payload.state;
    match = payload.match;
    you = payload.you;
    lastVersion = payload.version;
    if (match) {
      const names = {};
      const titles = {};
      for (const seat of match.seat_list) {
        names[seat.player_id] = seat.display_name;
        if (seat.title) titles[seat.player_id] = seat.title;
      }
      Board.setNameMap(names);
      Board.setTitleMap(titles);
    }
    const events = view.event_log || [];
    if (animatedUpTo < 0) animatedUpTo = 0;
    const fresh = events.slice(animatedUpTo);
    animatedUpTo = events.length;
    saveAnimCursor();
    if (initial) {
      // Opening a game: never auto-replay. If there's a tale to tell, offer
      // the choice — straight to orders, or watch it play out first.
      animating = true;   // keep the endgame modal from popping mid-setup
      renderAll();
      animating = false;
      if (events.some(shouldOfferEntryReplay)) {
        offerEntryChoice();
      } else {
        renderAll();
      }
      return;
    }
    if (fresh.some(isVisualEvent)) {
      animating = true;
      renderAll();        // draw ships/baubles first so the replay has actors
      playEventsSafely(fresh).then(renderAll);
    } else {
      renderAll();
    }
  }

  function offerEntryChoice() {
    const overlay = els["picker-overlay"];
    overlay.innerHTML = "";
    overlay.classList.remove("hidden");
    const complete = view.phase === "complete";
    const me = view.players[you];
    const canOrder = !complete && me && !me.has_submitted_orders && !me.eliminated && !(me.ship || {}).destroyed;
    const box = document.createElement("div");
    box.className = "picker";
    box.innerHTML = `
      <h3>Round ${view.round_number} · ${esc(PHASE_LABELS[view.phase] || view.phase)}</h3>
      <div class="picker-options">
        <div class="picker-option" id="entry-now">
          <div class="opt-icon">${complete ? "📜" : "⚔"}</div>
          <div class="opt-label">${complete ? "Battle Report" : canOrder ? "Straight to Orders" : "Jump to Now"}</div>
        </div>
        <div class="picker-option" id="entry-replay">
          <div class="opt-icon">▶</div>
          <div class="opt-label">Replay the tale so far</div>
          <div class="opt-sub">everything up to this moment</div>
        </div>
      </div>`;
    overlay.appendChild(box);
    document.getElementById("entry-now").addEventListener("click", () => {
      hidePicker();
      renderAll();
    });
    document.getElementById("entry-replay").addEventListener("click", async () => {
      hidePicker();
      animating = true;
      renderAll();
      await playEventsSafely(view.event_log || []);
      renderAll();
    });
  }

  function isVisualEvent(event) {
    return ["movement_resolved", "volley_resolved", "bauble_awarded", "round_advanced",
      "desperation_consequence", "player_forfeited", "starfall_revealed",
      "starfall_take_cover_damage", "captain_cleanup_movement",
      "boss_phase_started", "boss_phase_resolved", "enemy_volley_resolved",
      "boss_volley_resolved", "craft_volley_resolved", "repair_volley_resolved",
      "boss_progress_advanced", "boss_tiers_activated", "boss_fleet_spawned"].includes(event.type);
  }

  function shouldOfferEntryReplay(event) {
    if (!isVisualEvent(event)) return false;
    return !["round_advanced", "starfall_revealed"].includes(event.type);
  }

  function saveAnimCursor() {
    try { localStorage.setItem("ss_seen_" + gameId, String(animatedUpTo)); } catch (err) {}
  }

  // ── render ────────────────────────────────────────────────────────────
  const PHASE_LABELS = {
    give_orders: "Give Yer Orders", action_1: "Action I", action_2: "Action II",
    action_3: "Action III", award_baubles: "Claim the Loot", cleanup: "Swab the Decks",
    complete: "Battle Decided",
  };

  function seatOrder() {
    return (match ? match.seat_list.map((seat) => seat.player_id) : Object.keys(view.players));
  }

  function displayName(playerId) {
    const seat = match && match.seat_list.find((s) => s.player_id === playerId);
    return seat ? seat.display_name : playerId;
  }

  function titleFor(playerId) {
    const seat = match && match.seat_list.find((s) => s.player_id === playerId);
    return seat && seat.title ? seat.title : "";
  }

  /* Pretty label for any attack target: player, boss area, or fleet craft. */
  function targetLabel(target) {
    if (!target) return "";
    if (target.startsWith && target.startsWith("boss:")) {
      const area = target.split(":")[1];
      return `the StarBreacher (${area})`;
    }
    if (target.startsWith && target.startsWith("craft:")) {
      const id = target.split(":")[1];
      return id.replace("hk_", "") + " Hunter-Killer";
    }
    if (target === "starbreacher") return "the StarBreacher";
    return displayName(target);
  }

  function renderAll() {
    if (!view) return;
    restoreDraftIfAvailable();
    els["game-banner"].textContent = `Round ${view.round_number} of 6 · ${PHASE_LABELS[view.phase] || view.phase}`;
    Board.renderBaubles(view.baubles, view.round_number, { activeNumbers: extraActiveBaubleNumbers() });
    Board.renderStarBreach(effectiveStarBreach(), { preyPos: preyPosition() });
    Board.renderShips(view.players, seatOrder(), you);
    renderStarfallStatus();
    renderCaptainStatus();
    renderStarBreachStatus();
    renderFleet();
    renderLog();
    renderOrdersPanel();
    updateReportButton();
    if (view.phase === "complete" && !endgameShown && !animating) showEndgame();
  }

  function renderStarfallStatus() {
    let node = document.getElementById("starfall-status");
    if (!view.active_starfall) {
      clearScenarioStatus("starfall", node);
      return;
    }
    if (!node) {
      node = document.createElement("div");
      node.id = "starfall-status";
      node.className = "starfall-status scenario-status";
      statusStack().appendChild(node);
    }
    const sf = view.active_starfall;
    setScenarioStatus(node, "starfall", "☄", `<b>${esc(sf.name)}</b><span>${esc(sf.text)}</span>`);
  }

  function renderCaptainStatus() {
    let node = document.getElementById("captain-status");
    const me = view.players[you];
    const captain = me && me.captain;
    if (!captain) {
      clearScenarioStatus("captain", node);
      return;
    }
    if (!node) {
      node = document.createElement("div");
      node.id = "captain-status";
      node.className = "captain-status scenario-status";
      statusStack().appendChild(node);
    }
    setScenarioStatus(node, "captain", "⚓", `<b>${esc(captain.callsign || captain.name)}</b><span>${esc(captain.text)}</span>`);
  }

  function preyPosition() {
    const sb = view && view.star_breach;
    if (!sb) return null;
    const ship = displayShipFor(sb.prey_player_id);
    return ship && !ship.destroyed ? { q: ship.q, r: ship.r } : null;
  }

  function myRoles() {
    const me = myPlayer();
    return (me && me.roles) || [];
  }

  function renderStarBreachStatus() {
    let node = document.getElementById("starbreach-status");
    const sb = effectiveStarBreach();
    if (!sb) {
      clearScenarioStatus("starbreach", node);
      document.getElementById("boss-battle-board")?.remove();
      document.getElementById("boss-progress-rail")?.remove();
      document.getElementById("sb-pause-toggle")?.remove();
      return;
    }
    if (!node) {
      node = document.createElement("div");
      node.id = "starbreach-status";
      node.className = "starfall-status scenario-status";
      statusStack().appendChild(node);
    }
    const shields = ["forward", "port", "rear", "starboard"]
      .map((area) => `${area[0].toUpperCase()}${sb.shield_hp?.[area] ?? 0}`)
      .join(" ");
    const fleetAlive = (sb.fleet || []).filter((craft) => !craft.destroyed).length;
    const roleNames = myRoles().map((role) => (sb.roles && sb.roles[role] ? sb.roles[role].name : role)).join(" + ");
    setScenarioStatus(node, "starbreach", "◎", `<b>☄ StarBreacher</b>
      <span>Prey: ${esc(displayName(sb.prey_player_id))} · Progress ${sb.progress}
      · Shields ${esc(shields)} · Hunters ${fleetAlive}${roleNames ? ` · You: ${esc(roleNames)}` : ""}
      </span>`);
    node.title = "StarBreach status.";
    renderBossBattleBoardMini();
    renderPauseToggle();
  }

  function setScenarioStatus(node, key, icon, html) {
    node.classList.add("scenario-status");
    node.dataset.icon = icon;
    node.innerHTML = html;
    if (scenarioStatusSignatures.get(key) === html) return;
    scenarioStatusSignatures.set(key, html);
    node.classList.add("status-expanded");
    const prior = scenarioStatusTimers.get(key);
    if (prior) clearTimeout(prior);
    scenarioStatusTimers.set(key, window.setTimeout(() => {
      node.classList.remove("status-expanded");
      scenarioStatusTimers.delete(key);
    }, 5200));
  }

  function clearScenarioStatus(key, node) {
    if (node) node.remove();
    scenarioStatusSignatures.delete(key);
    const prior = scenarioStatusTimers.get(key);
    if (prior) clearTimeout(prior);
    scenarioStatusTimers.delete(key);
  }

  // ── boss battle board (mini in the main view, expanded in the modal) ───
  const STACK_COLORS = { "0.5": "#ff8d6b", "1.5": "#ffd75e", "2.5": "#9dff8a", "3.5": "#59c8ff", starbreach: "#d9a6ff" };
  const KIND_SYMBOL = { attack: "☄", move: "➤", breacher: "◉", spawn: "▣", ability: "⚡", filler: "·", shield: "🛡" };
  const KIND_COLORS = { attack: "#ff8d6b", move: "#9dff8a", breacher: "#d9a6ff", spawn: "#ff7ad0", ability: "#ffd75e", filler: "#9aa3b8", shield: "#59c8ff" };
  // Component tiles are colored/labelled by what they are, so a glance at the
  // hull tells you which action each tile powers (matching the chip colors).
  const COMPONENT_TYPE_COLOR = { cannon: "#ff8d6b", engine: "#9dff8a", shield_generator: "#59c8ff", core: "#d9a6ff" };
  // A font guaranteed to carry the ☄ ➤ ◉ 🛡 glyphs — the decorative body font
  // renders them as "?", so SVG symbol labels pin this explicitly.
  const SYMBOL_FONT = "'Space Grotesk', 'Segoe UI Symbol', sans-serif";
  const PHASE_SHORT = { "0.5": "0.5", "1.5": "1.5", "2.5": "2.5", "3.5": "3.5", starbreach: "SB" };
  const DEFAULT_PHASE_KIND = { "0.5": "attack", "1.5": "move", "2.5": "move", "3.5": "attack", starbreach: "breacher" };
  const COMPONENT_SYMBOL = { cannon: "☄", engine: "➤", shield_generator: "🛡", core: "◉" };
  // Which boss phase has already resolved by the time the player is acting.
  const BOSS_PHASE_DONE_BY_VIEW = { action_1: "0.5", action_2: "1.5", action_3: "2.5", award_baubles: "3.5" };

  function stackColor(key) { return STACK_COLORS[key] || "#d9a6ff"; }
  function kindColor(kind) { return KIND_COLORS[kind] || "#d9a6ff"; }
  function progressMax(sb) {
    return Math.max(...Object.values(sb.tier_progress || {}).map(Number), 1);
  }
  function displayedProgress(sb, progress) {
    return Math.min(progress || 0, progressMax(sb));
  }
  function tierLabel(sb, tier) {
    const layout = sb.boss_layout || {};
    for (const phase of layout.phases || []) {
      const slot = (phase.slots || []).find((entry) => entry.slot === "tier" && Number(entry.tier) === Number(tier));
      if (slot) {
        return {
          kind: phase.key === "starbreach" ? "breacher" : (slot.kind || phase.kind || "attack"),
          stack: phase.key,
        };
      }
    }
    if ((layout.tier_spawns || {})[String(tier)]) return { kind: "spawn", stack: null };
    const explicit = (layout.tier_labels || {})[String(tier)];
    if (explicit) return explicit;
    return { kind: "filler", stack: null };
  }

  /* The star-breach state to draw: the latest view state, overridden with the
     rewound/rolling replay state while a replay is animating, so the boss
     boards show the moment being replayed rather than the end of the game. */
  function effectiveStarBreach() {
    const sb = view && view.star_breach;
    if (!sb) return null;
    if (!replayBossState) return sb;
    return {
      ...sb,
      progress: replayBossState.progress,
      active_tiers: replayBossState.active_tiers,
      destroyed_hexes: replayBossState.destroyed_hexes,
      destroyed_component_ids: replayBossState.destroyed_component_ids,
      shield_hp: replayBossState.shield_hp,
    };
  }

  /* Where the boss stands inside the current turn's action stacks. */
  function bossPhaseCursor() {
    if (replayBossState) {
      return { done: replayBossState.phaseCursor, resolving: replayBossState.phaseResolving };
    }
    return { done: BOSS_PHASE_DONE_BY_VIEW[view.phase] || null, resolving: null };
  }

  /* Whether a boss action slot currently fires (mirrors the engine). */
  function bossSlotActive(sb, slot) {
    if (slot.slot === "base") return true;
    if (slot.slot === "component") {
      return !(sb.destroyed_component_ids || []).includes(slot.component_id);
    }
    if (slot.slot === "tier") {
      if (!(sb.active_tiers || []).includes(slot.tier)) return false;
      const core = slot.core_hex;
      if (core && (sb.destroyed_hexes || []).some(([q, r]) => q === core[0] && r === core[1])) return false;
      return slot.min_round == null || (view.round_number || 1) >= slot.min_round;
    }
    return false;
  }

  function bossComponentById(sb) {
    const byId = {};
    for (const component of (sb.boss_layout || {}).components || []) byId[component.id] = component;
    return byId;
  }

  /* Short symbol+number label for a slot chip: what powers this action. */
  function slotChipText(sb, slot, componentById) {
    if (slot.slot === "base") return "⬢";
    if (slot.slot === "tier") return "★" + slot.tier;
    const component = componentById[slot.component_id];
    return component ? (COMPONENT_SYMBOL[component.type] || "?") + (component.number ?? "") : "?";
  }

  function slotChipTitle(sb, slot, componentById, active) {
    const state = active ? "" : " (offline)";
    if (slot.slot === "base") return "Base action" + state;
    if (slot.slot === "tier") {
      const bits = [`Progress Tier ${slot.tier}`];
      if (slot.min_round != null) bits.push(`round ${slot.min_round}+`);
      if (slot.core_hex) bits.push("needs its core intact");
      return bits.join(" · ") + state;
    }
    const component = componentById[slot.component_id];
    return (component ? component.name : slot.component_id) + state;
  }

  /* Discrete progress-track boxes: one per progress point, filled up to the
     current progress, thick "major" borders where an ability is gained. */
  function progressBoxesHTML(sb, progress) {
    const thresholds = {};
    for (const [tier, threshold] of Object.entries(sb.tier_progress || {})) {
      thresholds[threshold] = Number(tier);
    }
    const shownProgress = displayedProgress(sb, progress);
    const maxTrack = progressMax(sb);
    let boxes = "";
    for (let step = 1; step <= maxTrack; step++) {
      const tier = thresholds[step];
      const label = tier != null ? tierLabel(sb, tier) : null;
      const kind = label ? label.kind : null;
      const online = tier != null && (sb.active_tiers || []).includes(tier);
      const classes = ["bmb-box"];
      if (step <= shownProgress) classes.push("filled");
      if (tier != null) classes.push("major");
      if (online) classes.push("online");
      // Ability boxes stay gray-ish until the tier comes online, then take the
      // color of the ability kind they grant (matching the action chips).
      const color = online ? kindColor(kind || "filler") : "#8a8a96";
      const symbol = tier != null ? (KIND_SYMBOL[kind] || "★") : "";
      const title = tier != null
        ? `Space ${step} — Tier ${tier}: ${kind || "ability"}${online ? " (online)" : ""}`
        : `Space ${step}`;
      boxes += `<span class="${classes.join(" ")}"${tier != null ? ` data-tier="${tier}" style="border-color:${color}${online ? `;color:${color}` : ""}"` : ""} title="${esc(title)}">${symbol}</span>`;
    }
    return boxes;
  }

  function progressTrackHTML(sb, progressOverride = null) {
    const progress = displayedProgress(sb, progressOverride ?? sb.progress ?? 0);
    return `<div class="bmb-track" title="Boss Progress Track — fills as the boss progresses; marked boxes grant abilities.">
      <span class="bmb-track-label">☄ ${progress}</span>${progressBoxesHTML(sb, progress)}</div>`;
  }

  /* One row of slot chips per boss action phase (+ fleet markers). Chips are
     color-coded by what the action does (attack/move/breacher…), rows that
     already resolved this turn dim, and a gold "we are here" marker sits
     between the resolved actions and the ones still to come. */
  function actionRowsHTML(sb) {
    const layout = sb.boss_layout || {};
    const cursor = bossPhaseCursor();
    const marker = `<div class="bmb-now" title="The turn stands here — actions above have resolved; the rest are still to come."><span>▶</span></div>`;
    const rowClasses = (index, doneIndex, key) => "bmb-row"
      + (doneIndex >= 0 && index <= doneIndex ? " done" : "")
      + (cursor.resolving === key ? " resolving" : "");
    const totalChip = (kind, count, title, fleet = false) => {
      if (!count) return "";
      const color = fleet ? "#9aa3b8" : kindColor(kind);
      const symbol = fleet ? `▣${KIND_SYMBOL[kind] || ""}` : (KIND_SYMBOL[kind] || "");
      return `<span class="bmb-chip on bmb-total${fleet ? " fleet" : ""} bmb-kind-${kind}"
        style="border-color:${color};color:${color}"
        title="${esc(title)}">${symbol}${count}</span>`;
    };
    const phases = layout.phases || [];
    if (!phases.length) {
      // Older games without phase data: fall back to plain counts.
      const entries = Object.entries(sb.expected_actions || {});
      const doneIndex = entries.findIndex(([key]) => key === cursor.done);
      return entries.map(([key, count], index) => {
        const kind = DEFAULT_PHASE_KIND[key] || "attack";
        const color = kindColor(kind);
        return `<div class="${rowClasses(index, doneIndex, key)}"><span class="bmb-phase" style="color:${stackColor(key)}">${esc(PHASE_SHORT[key] || key)}${KIND_SYMBOL[kind] || ""}</span>
         <span class="bmb-chip on" style="border-color:${color};color:${color}" title="${esc(kind)} ×${count}">${KIND_SYMBOL[kind] || ""}${count}</span></div>`
          + (index === doneIndex ? marker : "");
      }).join("");
    }
    const fleetAlive = (sb.fleet || []).filter((craft) => !craft.destroyed).length;
    const doneIndex = phases.findIndex((phase) => phase.key === cursor.done);
    return phases.map((phase, index) => {
      const color = stackColor(phase.key);
      const totals = {};
      for (const slot of phase.slots || []) {
        if (!bossSlotActive(sb, slot)) continue;
        const kind = slot.kind || phase.kind;
        totals[kind] = (totals[kind] || 0) + 1;
      }
      const fleetKinds = ((layout.fleet_actions || {})[phase.key]) || [];
      if (fleetAlive) {
        for (const kind of fleetKinds) totals[`fleet_${kind}`] = (totals[`fleet_${kind}`] || 0) + fleetAlive;
      }
      const chips = ["attack", "move", "breacher", "spawn", "ability"].concat(["fleet_attack", "fleet_move"])
        .map((kind) => {
          const fleet = kind.startsWith("fleet_");
          const baseKind = fleet ? kind.slice(6) : kind;
          return totalChip(baseKind, totals[kind], `${phase.key} ${fleet ? "fleet " : ""}${baseKind} total: ${totals[kind] || 0}`, fleet);
        })
        .join("");
      return `<div class="${rowClasses(index, doneIndex, phase.key)}">
        <span class="bmb-phase" style="color:${color}" title="${esc(phase.key === "starbreach" ? "StarBreach phase" : "Boss Action " + phase.key)}">${esc(PHASE_SHORT[phase.key] || phase.key)}${KIND_SYMBOL[phase.kind] || ""}</span>
        ${chips || '<span class="bmb-none">—</span>'}</div>`
        + (index === doneIndex ? marker : "");
    }).join("");
  }

  function renderBossBattleBoardMini() {
    const sb = effectiveStarBreach();
    let board = document.getElementById("boss-battle-board");
    let rail = document.getElementById("boss-progress-rail");
    if (!sb) { board?.remove(); rail?.remove(); return; }
    if (!board) {
      board = document.createElement("div");
      board.id = "boss-battle-board";
      board.className = "boss-mini-board";
      board.title = "The boss's battle board — click for the full damage board.";
      board.addEventListener("click", showBossModal);
      els["board-wrap"].appendChild(board);
    }
    board.innerHTML = `<div class="bmb-rows">${actionRowsHTML(sb)}</div>`;
    rail?.remove();
  }

  function pauseAfterActions() {
    try { return (localStorage.getItem("ss_sb_pause") ?? "1") === "1"; } catch (err) { return true; }
  }

  function renderPauseToggle() {
    if (document.getElementById("sb-pause-toggle")) return;
    const label = document.createElement("label");
    label.id = "sb-pause-toggle";
    label.className = "sb-pause-toggle scenario-status";
    label.dataset.icon = "⏸";
    label.innerHTML = `<input type="checkbox" ${pauseAfterActions() ? "checked" : ""}>
      <b>Replay Pause</b><span>Pause after each player action</span>`;
    label.querySelector("input").addEventListener("change", (event) => {
      try { localStorage.setItem("ss_sb_pause", event.target.checked ? "1" : "0"); } catch (err) {}
      label.classList.add("status-expanded");
      window.setTimeout(() => label.classList.remove("status-expanded"), 1600);
    });
    statusStack().appendChild(label);
  }

  function statusStack() {
    let node = document.getElementById("board-status-stack");
    if (!node) {
      node = document.createElement("div");
      node.id = "board-status-stack";
      node.className = "board-status-stack";
      els["board-wrap"].appendChild(node);
    }
    return node;
  }

  function extraActiveBaubleNumbers() {
    if (activeStarfall("most_dangerous_game")) return [1, 2, 3, 4, 5];
    if (activeStarfall("stars_align") && view.starfall_bauble_number) return [view.starfall_bauble_number];
    return [];
  }

  function renderFleet() {
    const container = els["fleet-list"];
    container.innerHTML = "";
    for (const playerId of seatOrder()) {
      const player = view.players[playerId];
      if (!player) continue;
      const ship = displayShipFor(playerId);
      const seat = match && match.seat_list.find((s) => s.player_id === playerId);
      const dead = ship.destroyed || player.eliminated;
      const card = document.createElement("div");
      card.className = "fleet-card" + (dead ? " dead" : "") + (playerId === you ? " mine" : "");
      card.style.borderLeftColor = Board.colorOf(playerId);
      const submitted = view.phase === "give_orders"
        ? (player.has_submitted_orders
          ? `<span class="badge-ready">⚑ orders sealed</span>`
          : `<span class="badge-wait">… plotting</span>`)
        : "";
      card.innerHTML = `
        <div class="fc-name">
          <span>${esc(displayName(playerId))}
            ${playerId === you ? '<span class="badge-you">YOU</span>' : ""}
            ${titleFor(playerId) ? `<span class="badge-title">${esc(titleFor(playerId))}</span>` : ""}
            ${seat && seat.is_ai ? `<span class="badge-ai">${esc(seat.ai_label || "AI")}</span>` : ""}
            ${view.star_breach && view.star_breach.prey_player_id === playerId ? '<span class="badge-title" style="color:#ff8a7a">PREY</span>' : ""}
            ${view.star_breach && (player.roles || []).length ? `<span class="badge-title">${esc((player.roles || []).map((role) => (view.star_breach.roles?.[role]?.name) || role).join(" · "))}</span>` : ""}
          </span>
          <span class="vp">${player.victory_points} VP</span>
        </div>
        <div class="fc-body">
          <div class="fc-mini">${ShipView.miniShipSVG(ship, playerId === you ? 96 : 74)}</div>
          <div class="fc-sub">
            <span class="shield-pips" title="Shield charges">${"◈".repeat(ship.shields || 0) || "—"}</span>
            <span class="hull-pips" title="Components destroyed">${player.eliminated && !ship.destroyed ? "🏳 struck colors" : dead ? "☠ SUNK" : ((ship.destroyed_components || []).length ? `✕${(ship.destroyed_components || []).length}` : "hull sound")}</span>
            <span title="Cards in hand">🂠 ${player.hand_count ?? "?"}</span>
            ${submitted}
          </div>
        </div>`;
      card.title = "Click for the full ship board";
      card.addEventListener("click", () => showShipModal(playerId));
      container.appendChild(card);
    }
  }

  function showShipModal(playerId) {
    const player = view.players[playerId];
    if (!player) return;
    const ship = displayShipFor(playerId);
    const overlay = els["picker-overlay"];
    overlay.innerHTML = "";
    overlay.classList.remove("hidden");
    const box = document.createElement("div");
    box.className = "picker ship-modal";
    const knocked = ship.knocked_out_round
      ? `<div class="opt-sub">Knocked out round ${ship.knocked_out_round}</div>` : "";
    box.innerHTML = `
      <h3 style="color:${Board.colorOf(playerId)}">${esc(displayName(playerId))} — Ship Board</h3>
      <div class="opt-sub">d12 damage lanes enter from the rim; a shot destroys the first intact
        component along its lane. Lose the Bridge or both Life Supports and the ship is done.</div>
      ${knocked}
      ${ShipView.fullShipSVG(ship)}
      <button class="btn ghost picker-cancel" id="ship-modal-close">Close</button>`;
    overlay.appendChild(box);
    document.getElementById("ship-modal-close").addEventListener("click", hidePicker);
    const backdropClose = (event) => {
      if (event.target === overlay) {
        overlay.removeEventListener("click", backdropClose);
        hidePicker();
      }
    };
    overlay.addEventListener("click", backdropClose);
  }

  function logLine(event) {
    const name = (id) => displayName(id || "");
    switch (event.type) {
      case "round_advanced": return { cls: "round", text: `— Round ${event.round} —` };
      case "phase_changed": return event.phase && event.phase.startsWith("action")
        ? { cls: "round", text: `⚔ ${PHASE_LABELS[event.phase] || event.phase}` } : null;
      case "orders_submitted": return { cls: "", text: `${name(event.player_id)} sealed their orders.` };
      case "captain_chosen": {
        const captain = event.captain_name || event.captain_callsign || event.captain_id || "a StarCommand captain";
        return { cls: "loot", text: `${name(event.player_id)} chooses ${captain}.` };
      }
      case "starfall_revealed": return { cls: "round", text: `Starfall: ${event.starfall} - ${event.text}` };
      case "movement_resolved": {
        const dist = (event.steps || []).reduce((total, step) => total + (step.distance || 0), 0);
        return dist ? { cls: "", text: `${name(event.player_id)} sails ${dist} hex${dist > 1 ? "es" : ""}${event.overdrive_copy ? " (overdrive)" : ""}.` } : null;
      }
      case "volley_resolved": {
        const result = event.shielded ? "shield takes it" : event.hit ? `HIT for ${event.damage_applied || event.damage}` : "misses";
        return { cls: event.hit ? "hit" : "", text: `${name(event.attacker_id)} fires on ${name(event.target_id)} — 🎲${event.roll}+${event.aim_bonus} vs ${event.defense_threshold}: ${result}${event.target_destroyed ? " — SHIP DESTROYED ☠" : ""}` };
      }
      case "bauble_awarded": {
        const who = (event.awards || []).map((award) => {
          const draws = award.desperation_card_drawn
            ? ` + desperate card added to deck from ${event.bauble?.is_fang ? "Fang" : "bauble"}${award.captain_bonus ? " (Beto bonus)" : ""}`
            : "";
          return `${name(award.player_id)} +${award.vp_awarded} VP${draws}`;
        }).join(", ");
        return { cls: "loot", text: `✦ Loot claimed: ${who}` };
      }
      case "desperation_consequence": return { cls: "hit", text: `${name(event.player_id)} adds a desperate card to the top of their deck because their ship took unshielded hull damage.` };
      case "hand_drawn": {
        const bonus = event.bonus_draws || 0;
        return bonus
          ? { cls: "loot", text: `${name(event.player_id)} draws ${event.hand_count || "a hand"} cards, including ${bonus} bonus card${bonus === 1 ? "" : "s"} from StarBreach bauble support.` }
          : null;
      }
      case "action_cards_moved":
        return (event.returned_to_desperation_deck || []).length
          ? { cls: "", text: `${name(event.player_id)} returns used desperate card${event.returned_to_desperation_deck.length === 1 ? "" : "s"} to the desperation deck.` }
          : null;
      case "starfall_jolly_roger_draw":
        return { cls: "loot", text: `${name(event.player_id)} adds a desperate card to the top of their deck from Jolly Roger after their first hit this round.` };
      case "captain_davey_reward":
        return { cls: "loot", text: `${name(event.player_id)} adds a desperate card to the top of their deck from Davey Locker after a bridge/life-support break, and gains ${event.vp_awarded || 2} VP.` };
      case "boss_phase_resolved": {
        if (!(event.slots || []).length && !(event.fleet || []).length) return null;
        const label = event.boss_phase === "starbreach" ? "STARBREACH" : `Action ${event.boss_phase}`;
        return { cls: "round", text: `☄ The StarBreacher acts (${label}) — ${event.kind}.` };
      }
      case "boss_progress_advanced": {
        const tiers = event.tiers_unlocked || [];
        return {
          cls: "hit",
          text: `☄ Boss progress +${event.amount} (now ${event.progress})${tiers.length ? ` — Tier ${tiers.join(", ")} reached (powers up next round)` : ""}`,
        };
      }
      case "boss_tiers_activated":
        return { cls: "hit", text: `☄ Boss Tier ${event.tiers.join(", ")} comes online — more boss actions this round.` };
      case "boss_fleet_spawned": {
        const where = { boss_front: "ahead of the boss", bauble: "at the bauble", fang: "at The Fang" }[event.location] || "";
        return { cls: "hit", text: `☄ Reinforcements! ${(event.craft || []).length} fleet craft warp in ${where} (Tier ${event.tier}).` };
      }
      case "enemy_volley_resolved": {
        const result = event.shielded ? "shield takes it" : event.hit ? `HIT for ${event.damage_applied || 1}` : "misses";
        return { cls: event.hit ? "hit" : "", text: `${targetLabel(event.attacker)} fires on ${name(event.target_id)} — 🎲${event.roll}${event.aim_bonus ? "+" + event.aim_bonus : ""} vs ${event.defense_threshold}: ${result}${event.target_destroyed ? " — SHIP DESTROYED ☠" : ""}` };
      }
      case "boss_volley_resolved": {
        let result = "misses";
        if (event.hit) {
          const bits = [];
          if (event.shields_absorbed) bits.push(`${event.shields_absorbed} soaked by shields`);
          const laneShots = (event.shots || [])
            .filter((shot) => ["hull_destroyed", "glancing_blow", "overpenetration"].includes(shot.result))
            .map((shot) => {
              const shift = shot.ace_shift ? ` (Fighting Ace ${shot.ace_shift > 0 ? "+" : ""}${shot.ace_shift})` : "";
              if (shot.result === "glancing_blow") return `lane roll ${shot.roll}${shift}: glancing blow, desperate card added to top of deck`;
              if (shot.result === "overpenetration") return `lane roll ${shot.roll} -> lane ${shot.lane}${shift}: overpenetrates`;
              const target = shot.component_id ? shot.component_id.replace(/_/g, " ") : `hex ${shot.hex?.join(",")}`;
              return `lane roll ${shot.roll} -> lane ${shot.lane}${shift}: ${target} destroyed`;
            });
          if (laneShots.length) bits.push(laneShots.join("; "));
          else if (event.hexes_destroyed) bits.push(`${event.hexes_destroyed} hull hex${event.hexes_destroyed > 1 ? "es" : ""} destroyed`);
          if ((event.components_destroyed || []).length) bits.push(`${event.components_destroyed.join(", ")} DESTROYED`);
          result = "HIT: " + (bits.join(", ") || "no effect");
        }
        return { cls: event.hit ? "hit" : "", text: `${name(event.attacker_id)} fires on ${targetLabel(event.target_id)} — 🎲${event.roll} vs ${event.defense_threshold}: ${result}` };
      }
      case "craft_volley_resolved": {
        const result = event.hit ? (event.craft_destroyed ? "DESTROYED ☠" : `HIT for ${event.damage_applied} (${event.craft_hp_left} HP left)`) : "misses";
        return { cls: event.hit ? "hit" : "", text: `${name(event.attacker_id)} fires on the ${targetLabel(event.target_id)} — 🎲${event.roll} vs ${event.defense_threshold}: ${result}` };
      }
      case "repair_volley_resolved": {
        const result = event.hit
          ? (event.restored_component_id ? `repairs ${event.restored_component_id.replace(/_/g, " ")}` : event.shield_restored ? "restores a shield" : "nothing to fix")
          : "fumbles the repair";
        return { cls: "loot", text: `🔧 ${name(event.attacker_id)} works on ${name(event.target_id)} — 🎲${event.roll} vs ${event.defense_threshold}: ${result}.` };
      }
      case "player_forfeited": return { cls: "round", text: `🏳 ${name(event.player_id)} strikes their colors and abandons the battle!` };
      case "deck_refreshed": return { cls: "", text: `${name(event.player_id)} reshuffles.` };
      default: return null;
    }
  }

  function renderLog() {
    const container = els["action-log"];
    const wasNearBottom = container.scrollHeight - container.scrollTop - container.clientHeight < 24;
    container.innerHTML = "";
    const events = (view.event_log || []).slice(-120);
    for (const event of events) {
      const line = logLine(event);
      if (!line) continue;
      const div = document.createElement("div");
      div.className = "log-entry " + line.cls;
      div.textContent = line.text;
      container.appendChild(div);
    }
    if (sideTab === "log" && wasNearBottom) scrollLogToBottom();
  }

  // ── orders panel ──────────────────────────────────────────────────────
  function myPlayer() { return view.players[you]; }

  function renderOrdersPanel() {
    const me = myPlayer();
    const handArea = els["hand-area"];
    const slotsArea = els["order-slots"];
    els["deck-count"].textContent = me ? me.deck_count : 0;
    els["discard-count"].textContent = me ? (me.discard || []).length : 0;

    const ordering = view.phase === "give_orders" && me && !me.has_submitted_orders && !me.eliminated && !(me.ship || {}).destroyed;

    // While the round replays, keep the captain's submitted orders on the
    // table and highlight each stack as it plays out — but never let a
    // stuck, overlapping, or slow-to-finish replay block placing fresh
    // orders once the server has actually moved the game on. The real
    // current state (view.phase / round_number) always wins.
    if (animating && replayOrders && replayOrders.round === view.round_number && !ordering) {
      renderReplayOrders(slotsArea, handArea);
      return;
    }
    const needsCaptain = ordering && me.captain_options && me.captain_options.length && !me.captain;
    els["btn-submit-orders"].disabled = !ordering || needsCaptain;
    els["btn-clear-orders"].disabled = !ordering || needsCaptain;

    slotsArea.innerHTML = "";
    for (let index = 0; index < 3; index++) {
      slotsArea.appendChild(slotEl(index, ordering));
    }

    handArea.innerHTML = "";
    if (!me) {
      const note = document.createElement("div");
      note.className = "hand-note";
      note.textContent = "👁 Spectating — watching the AI captains slug it out.";
      handArea.appendChild(note);
      els["orders-hint"].textContent = "";
      return;
    }
    if (needsCaptain) {
      slotsArea.innerHTML = "";
      handArea.innerHTML = "";
      const picker = document.createElement("div");
      picker.className = "captain-choice";
      picker.innerHTML = `<h3>Choose Your StarCommand Captain</h3>`;
      const row = document.createElement("div");
      row.className = "captain-options";
      for (const captain of me.captain_options || []) {
        const card = document.createElement("button");
        card.className = "captain-card";
        card.type = "button";
        card.innerHTML = `<b>${esc(captain.callsign || captain.name)}</b><span>${esc(captain.name)}</span><small>${esc(captain.text)}</small>`;
        card.addEventListener("click", () => chooseCaptain(captain.id));
        row.appendChild(card);
      }
      picker.appendChild(row);
      handArea.appendChild(picker);
      els["orders-hint"].textContent = "Pick a captain before sealing your first orders.";
      return;
    }
    if (!ordering) {
      const note = document.createElement("div");
      note.className = "hand-note";
      if (view.phase === "complete") note.textContent = "The battle is decided.";
      else if (me.eliminated || (me.ship || {}).destroyed) note.textContent = "Yer ship rests in the black. Watch the fireworks.";
      else if (me.has_submitted_orders) note.textContent = "Orders sealed. Waiting on the other captains…";
      else note.textContent = "Resolving the round…";
      handArea.appendChild(note);
      els["orders-hint"].textContent = "";
      return;
    }
    const placed = new Set(draft.slots.flatMap((slot) => slot.cards.map((c) => c.card_id)));
    const hand = me.hand || [];
    const spread = hand.filter((card) => !placed.has(card.id));
    spread.forEach((card) => {
      const node = Cards.cardEl(card, {
        onClick: () => beginPlacement(card, armedSlot),
      });
      node.draggable = true;
      node.addEventListener("dragstart", (event) => {
        event.dataTransfer.setData("text/plain", card.id);
        event.dataTransfer.effectAllowed = "move";
      });
      handArea.appendChild(node);
    });
    els["orders-hint"].textContent = spread.length
      ? (armedSlot !== null
        ? `Action ${armedSlot + 1} armed — click a card to load it (or click the slot again to disarm).`
        : "Click or drag a card onto an action — or click an action slot first, then pick cards for it.")
      : "All hands assigned. Seal yer orders!";
    computePreview();
  }

  /* Read-only view of the submitted stacks while the round replays. */
  function renderReplayOrders(slotsArea, handArea) {
    els["btn-submit-orders"].disabled = true;
    els["btn-clear-orders"].disabled = true;
    const me = myPlayer();
    const cardById = new Map();
    for (const pile of [me?.hand, me?.discard, me?.overheat]) {
      for (const card of pile || []) cardById.set(card.id, card);
    }
    slotsArea.innerHTML = "";
    replayOrders.slots.forEach((stack, index) => {
      const node = document.createElement("div");
      node.className = "order-slot replaying"
        + (replayOrders.active === index ? " playing" : "")
        + (replayOrders.active !== null && index < replayOrders.active ? " played" : "");
      node.dataset.slot = index;
      const label = document.createElement("div");
      label.className = "slot-label";
      label.textContent = `Action ${index + 1}` + (replayOrders.active === index ? " ⚔" : "");
      node.appendChild(label);
      const cardsBox = document.createElement("div");
      cardsBox.className = "slot-cards";
      for (const selection of (stack && stack.cards) || []) {
        const card = cardById.get(selection.card_id) || { id: selection.card_id, name: "Card", effect: {} };
        const family = selection.mode
          || (selection.face === "desperate" ? (card.desperate_face || {}).family : (card.effect || {}).family || card.family)
          || null;
        const target = selection.target_player_id;
        const tag = family === "attack"
          ? "→ " + (!target ? "ahead"
            : String(target).startsWith("boss:") ? `Boss ${areaDisplayName(String(target).split(":")[1])}`
            : String(target).startsWith("craft:") ? "Hunter" : Board.shortName(target))
          : Cards.orientationLabel(selection.orientation || "forward").split(" ")[0];
        cardsBox.appendChild(Cards.cardEl(card, { inSlot: true, faceUsed: selection.face, useTag: tag }));
      }
      if (!stack || !(stack.cards || []).length) {
        const hint = document.createElement("span");
        hint.style.cssText = "color:var(--ink-dim);font-size:11px;font-style:italic";
        hint.textContent = "empty — ship coasts";
        cardsBox.appendChild(hint);
      }
      node.appendChild(cardsBox);
      const seal = document.createElement("div");
      seal.className = "replay-seal" + (stack && stack.seal === "overdrive" ? " overdrive" : "");
      seal.textContent = stack && stack.seal === "overdrive" ? "🔥 OVERDRIVE" : "☠ sealed";
      node.appendChild(seal);
      slotsArea.appendChild(node);
    });
    handArea.innerHTML = "";
    const note = document.createElement("div");
    note.className = "hand-note";
    note.textContent = `⚔ Round ${replayOrders.round} — yer orders play out. Watch the board!`;
    handArea.appendChild(note);
    els["orders-hint"].textContent = "";
  }

  async function chooseCaptain(captainId) {
    try {
      const payload = await API.chooseCaptain(gameId, captainId);
      applyPayload(payload, false);
    } catch (error) {
      App.toast(error.message);
    }
  }

  function slotEl(index, ordering) {
    const slot = draft.slots[index];
    const node = document.createElement("div");
    node.className = "order-slot" + (armedSlot === index ? " armed" : "");
    node.dataset.slot = index;
    if (ordering) {
      // Click the slot itself (not a card/seal) to arm it for slot-first picking.
      node.addEventListener("click", (event) => {
        if (event.target.closest(".card") || event.target.closest(".seal-toggle") || event.target.closest(".seal-details")) return;
        armedSlot = armedSlot === index ? null : index;
        renderOrdersPanel();
      });
      node.addEventListener("dragover", (event) => {
        event.preventDefault();
        node.classList.add("receiving");
      });
      node.addEventListener("dragleave", () => node.classList.remove("receiving"));
      node.addEventListener("drop", (event) => {
        event.preventDefault();
        node.classList.remove("receiving");
        const cardId = event.dataTransfer.getData("text/plain");
        const me = myPlayer();
        const card = (me.hand || []).find((c) => c.id === cardId);
        if (card) beginPlacement(card, index);
      });
    }
    const cardsHtml = document.createElement("div");
    cardsHtml.className = "slot-cards";
    for (const selection of slot.cards) {
      const mini = Cards.cardEl(selection.card, {
        inSlot: true,
        faceUsed: selection.face,
        useTag: useTag(selection),
        onClick: ordering ? () => { removeFromSlot(index, selection); } : null,
      });
      mini.title = "Click to return to hand";
      cardsHtml.appendChild(mini);
    }
    if (!slot.cards.length) {
      const hint = document.createElement("span");
      hint.style.cssText = "color:var(--ink-dim);font-size:11px;font-style:italic";
      hint.textContent = "empty — ship coasts";
      cardsHtml.appendChild(hint);
    }
    const seal = document.createElement("div");
    seal.className = "seal-control";
    const overdriveNote = overdriveCopiesAction() ? "OVERDRIVE x2" : "OVERDRIVE";
    seal.innerHTML = `<div class="seal-toggle ${slot.seal === "overdrive" ? "overdrive" : ""}" title="Toggle Sealed / Overdrive">${slot.seal === "overdrive" ? "🔥" : "☠"}</div>
      <div class="seal-note">${slot.seal === "overdrive" ? overdriveNote : "sealed"}</div>`;
    seal.querySelector(".seal-toggle").innerHTML = `<span class="seal-mode-text">${slot.seal === "overdrive" ? overdriveNote : "SEALED"}</span>`;
    seal.querySelector(".seal-note")?.remove();
    if (ordering) {
      seal.querySelector(".seal-toggle").addEventListener("click", () => {
        slot.seal = slot.seal === "overdrive" ? "sealed" : "overdrive";
        orderTrace("seal_toggled", { slot_index: index, seal: slot.seal });
        saveDraft();
        renderOrdersPanel();
      });
    }
    const label = document.createElement("div");
    label.className = "slot-label";
    label.textContent = `Action ${index + 1}`;
    node.appendChild(label);
    node.appendChild(cardsHtml);
    const shotPreview = slotShotPreviewEl(index);
    if (shotPreview) {
      const details = document.createElement("div");
      details.className = "seal-details";
      details.innerHTML = `<button class="seal-details-button" type="button">Details</button>`;
      details.querySelector(".seal-details-button").textContent = "i";
      details.querySelector(".seal-details-button").setAttribute("aria-label", "Shot details");
      details.querySelector(".seal-details-button").addEventListener("click", (event) => {
        event.stopPropagation();
        if (document.documentElement.dataset.device === "phone") {
          showShotPreviewPopup(index);
        }
      });
      if (document.documentElement.dataset.device !== "phone") {
        details.appendChild(shotPreview);
      }
      seal.appendChild(details);
    }
    node.appendChild(seal);
    return node;
  }

  function slotShotPreviewEl(index) {
    const html = slotShotPreviewHtml(index);
    if (!html) return null;
    const node = document.createElement("div");
    node.className = "slot-shot-preview";
    node.innerHTML = html;
    return node;
  }

  function slotShotPreviewHtml(index) {
    const projections = attackProjectionsForSlot(index);
    if (!projections.length) return "";
    return `
      <div class="shot-preview-kicker">Shot Preview</div>
      ${projections.map((projection) => `
        <div class="shot-preview-row">
          <b>${esc(projection.label)}</b>
          <span>${esc(projectionSummary(projection))}</span>
        </div>
      `).join("")}
      ${projections.some((projection) => projection.overdriveCopy)
        ? `<div class="shot-preview-note">${esc(overdriveCopiesAction()
          ? "Overdrive repeats eligible cards as a second volley."
          : "Overdrive combines eligible card values into this volley.")}</div>`
        : ""}
    `;
  }

  function showShotPreviewPopup(index) {
    const html = slotShotPreviewHtml(index);
    const overlay = els["picker-overlay"];
    if (!html || !overlay) return;
    overlay.innerHTML = "";
    overlay.classList.remove("hidden");
    const box = document.createElement("div");
    box.className = "picker shot-preview-picker";
    box.innerHTML = `
      <h3>Action ${index + 1} Shot Preview</h3>
      <div class="slot-shot-preview mobile-popup">${html}</div>
      <button class="btn ghost picker-cancel" type="button">Close</button>
    `;
    box.querySelector(".picker-cancel").addEventListener("click", hidePicker);
    overlay.appendChild(box);
  }

  function useTag(selection) {
    if (selection.family === "attack") {
      return selection.target_player_id ? "→ " + Board.shortName(selection.target_player_id) : "→ ahead";
    }
    return Cards.orientationLabel(selection.orientation).split(" ")[0];
  }

  function overdriveCopiesAction() {
    return (view?.rules_config?.overdrive_style || "copy_action") === "copy_action";
  }

  function overdriveCopiesCards() {
    return (view?.rules_config?.overdrive_style || "copy_action") === "combine_cards";
  }

  /* First living enemy on the straight line out of `pos` (untargeted volley). */
  function forwardTarget(pos) {
    for (let distance = 1; distance <= Board.RADIUS * 2; distance++) {
      const [dq, dr] = Board.DIRECTIONS[((pos.facing % 6) + 6) % 6];
      const q = pos.q + dq * distance, r = pos.r + dr * distance;
      if (Board.hexDistance(0, 0, q, r) > Board.RADIUS) return null;
      for (const pid of seatOrder()) {
        const player = view.players[pid];
        if (!player || pid === you || player.eliminated || (player.ship || {}).destroyed) continue;
        if (player.ship.q === q && player.ship.r === r) return pid;
      }
    }
    return null;
  }

  function removeFromSlot(index, selection) {
    const slot = draft.slots[index];
    slot.cards = slot.cards.filter((c) => c !== selection);
    orderTrace("card_removed", { slot_index: index, card_id: selection.card_id });
    saveDraft();
    renderOrdersPanel();
  }

  // ── placement flow ────────────────────────────────────────────────────
  let targetResolver = null;
  let armedSlot = null;

  function handleShipClick(playerId) {
    if (targetResolver && view.star_breach) {
      // Co-op: clicking a crew ship is only meaningful for Engineer repairs.
      if (myRoles().includes("engineer")) {
        const resolve = targetResolver;
        targetResolver = null;
        hidePicker();
        resolve(playerId);
      }
      return;
    }
    if (targetResolver && playerId !== you) {
      const resolve = targetResolver;
      targetResolver = null;
      hidePicker();
      resolve(playerId);
      return;
    }
    if (document.documentElement.dataset.device === "phone") {
      showShipModal(playerId);
    }
  }

  function handleBossClick(area) {
    if (targetResolver) {
      const resolve = targetResolver;
      targetResolver = null;
      hidePicker();
      resolve("boss:" + area);
      return;
    }
    showBossModal();
  }

  // ── boss hull SVG (shared by the damage-board modal and the target picker) ─
  const AREA_FILL = { forward: "217,166,255", port: "170,110,190", rear: "190,120,80", starboard: "110,170,120" };
  const AREA_STROKE = { forward: "#9ee7ff", port: "#bcb0ff", rear: "#ffd08a", starboard: "#9fe8b6" };
  // Designed bosses name their areas after shield regions; give them stable
  // colors by position in the layout's area list.
  const EXTRA_FILL = ["89,200,255", "255,157,107", "157,255,138", "255,215,94", "255,122,208", "143,157,255", "107,255,216", "255,107,107", "208,255,94"];
  const EXTRA_STROKE = ["#59c8ff", "#ff9d6b", "#9dff8a", "#ffd75e", "#ff7ad0", "#8f9dff", "#6bffd8", "#ff6b6b", "#d0ff5e"];
  const COMPONENT_BADGE = { shield_generator: "SG", cannon: "☄", engine: "➤", core: "◉" };

  function areaPalette(sb) {
    const layoutAreas = (sb.boss_layout || {}).areas || [];
    return {
      fill: (area) => AREA_FILL[area] || EXTRA_FILL[Math.max(0, layoutAreas.indexOf(area)) % EXTRA_FILL.length],
      stroke: (area) => AREA_STROKE[area] || EXTRA_STROKE[Math.max(0, layoutAreas.indexOf(area)) % EXTRA_STROKE.length],
    };
  }

  function areaDisplayName(area) {
    return /^\d+$/.test(area) ? `region ${area}` : area;
  }

  /* Areas that can still be damaged (mirrors the engine's area check). */
  function bossAliveAreas() {
    const sb = view.star_breach;
    if (!sb) return {};
    const destroyed = new Set((sb.destroyed_hexes || []).map(([q, r]) => q + "," + r));
    const areaAlive = {};
    for (const cell of (sb.boss_layout || {}).footprint || []) {
      if (cell.area && !destroyed.has(cell.q + "," + cell.r)) areaAlive[cell.area] = true;
    }
    // Designed bosses: an area also lives while any of its damage lanes can
    // still bite. Stock areas are exactly their footprint cells.
    const laneBackedAreas = String(sb.scenario_id || "").startsWith("design:");
    for (const [area, lanes] of Object.entries(laneBackedAreas ? (sb.boss_layout || {}).damage_lanes || {} : {})) {
      if (areaAlive[area]) continue;
      for (const lane of Object.values(lanes || {})) {
        if ((lane || []).some(([q, r]) => !destroyed.has(q + "," + r))) {
          areaAlive[area] = true;
          break;
        }
      }
    }
    return areaAlive;
  }

  /* Build the boss hull as SVG markup. Options:
       lanes: draw damage lanes (laneAreaFilter limits them to one area)
       shields: draw the stock shield arcs
       clickableAreas: {area: true} — hexes become buttons with data-area
       selectedArea: highlight one region */
  function bossHullParts(sb, opts = {}) {
    const layout = sb.boss_layout || {};
    const destroyed = new Set((sb.destroyed_hexes || []).map(([q, r]) => q + "," + r));
    const componentsByHex = {};
    for (const component of layout.components || []) {
      componentsByHex[component.q + "," + component.r] = component;
    }
    const palette = areaPalette(sb);
    const size = opts.size || 13, sq = Math.sqrt(3);
    const cells = layout.footprint || [];
    const xy = (q, r) => [size * 1.5 * q, size * sq * (r + q / 2)];
    let hullSvg = "";
    for (const cell of cells) {
      const [x, y] = xy(cell.q, cell.r);
      const dead = destroyed.has(cell.q + "," + cell.r);
      const component = componentsByHex[cell.q + "," + cell.r];
      const selected = opts.selectedArea && cell.area === opts.selectedArea;
      const clickable = opts.clickableAreas && cell.area && opts.clickableAreas[cell.area];
      // In component-color mode the tile is tinted by what it is (so the shield
      // arcs alone carry the region grouping); otherwise tiles carry the region
      // color the way the target picker needs.
      const typeColor = component && COMPONENT_TYPE_COLOR[component.type];
      const useTypeColor = opts.componentColors && typeColor;
      const tint = cell.area ? palette.fill(cell.area) : "150,150,150";
      const pts = [];
      for (let i = 0; i < 6; i++) {
        const a = (Math.PI / 180) * (60 * i);
        pts.push(`${(x + (size - 0.8) * Math.cos(a)).toFixed(1)},${(y + (size - 0.8) * Math.sin(a)).toFixed(1)}`);
      }
      const fillAlpha = selected ? ".78" : ".5";
      let fill, stroke;
      if (dead) {
        fill = "rgba(25,25,32,.9)"; stroke = "#333";
      } else if (useTypeColor) {
        fill = `${typeColor}44`; stroke = selected ? "#fff" : typeColor;
      } else if (opts.componentColors) {
        // Non-component hull in component-color mode: neutral so the tiles that
        // do something stand out.
        fill = "rgba(120,124,138,.28)"; stroke = selected ? "#fff" : "#6b7080";
      } else {
        fill = `rgba(${tint},${fillAlpha})`; stroke = selected ? "#fff" : `rgb(${tint})`;
      }
      const componentAttrs = component
        ? `data-component-id="${esc(component.id)}" class="boss-component-node"`
        : "";
      hullSvg += `<polygon points="${pts.join(" ")}"
        fill="${fill}" stroke="${stroke}" stroke-width="${selected ? 1.8 : 1}"
        ${clickable ? `data-area="${esc(cell.area)}" class="boss-region-cell" cursor="pointer"` : componentAttrs}>
        <title>${esc(component ? component.name : `${areaDisplayName(cell.area)} hull`)}${dead ? " (destroyed)" : ""}</title></polygon>`;
      if (component) {
        const label = `${COMPONENT_SYMBOL[component.type] || "◆"}${component.number ?? ""}`;
        const labelFill = dead ? "#555" : (useTypeColor ? "#f4f1e6" : "#0a0f1e");
        // Label size tracks the hex size so big boards get big, readable text.
        const fontSize = size * 0.72;
        hullSvg += `<text x="${x}" y="${(y + fontSize * 0.36).toFixed(1)}" text-anchor="middle" font-size="${fontSize.toFixed(1)}" font-weight="700"
          font-family="${SYMBOL_FONT}" fill="${labelFill}" pointer-events="none">${label}</text>`;
      } else if (dead) {
        const fontSize = size * 0.72;
        hullSvg += `<text x="${x}" y="${(y + fontSize * 0.36).toFixed(1)}" text-anchor="middle" font-size="${fontSize.toFixed(1)}" fill="#555" pointer-events="none">✕</text>`;
      }
    }
    let laneSvg = "";
    if (opts.lanes) {
      for (const [area, lanes] of Object.entries(layout.damage_lanes || {})) {
        if (opts.laneAreaFilter && area !== opts.laneAreaFilter) continue;
        const color = palette.stroke(area);
        for (const [roll, lane] of Object.entries(lanes || {})) {
          if (!Array.isArray(lane) || lane.length < 1) continue;
          const points = lane.map(([q, r]) => xy(q, r).map((n) => n.toFixed(1)).join(",")).join(" ");
          const [fx, fy] = xy(lane[0][0], lane[0][1]);
          let nx = 0, ny = -1;
          if (lane.length > 1) {
            const [sx, sy] = xy(lane[1][0], lane[1][1]);
            const len = Math.hypot(sx - fx, sy - fy) || 1;
            nx = (sx - fx) / len; ny = (sy - fy) / len;
          }
          const labelX = fx - nx * size * 1.8;
          const labelY = fy - ny * size * 1.8;
          const tipX = fx - nx * size * 0.82;
          const tipY = fy - ny * size * 0.82;
          const highlight = opts.highlightLane != null && String(opts.highlightLane) === String(roll)
            && (!opts.laneAreaFilter || area === opts.laneAreaFilter);
          laneSvg += `<g class="boss-lane-mark"${opts.laneClickable ? ` data-lane="${esc(roll)}" cursor="pointer"` : ""}><title>${esc(areaDisplayName(area))} lane ${esc(roll)}</title>
            <polyline points="${points}" fill="none" stroke="${highlight ? "#fff" : color}" stroke-width="${highlight ? 2 : 1.0}"
              stroke-linecap="round" stroke-linejoin="round" opacity="${highlight ? ".75" : ".2"}"/>
            <text x="${labelX.toFixed(1)}" y="${(labelY + 4.5).toFixed(1)}" text-anchor="middle"
              font-size="12" fill="${highlight ? "#ffd76a" : "#e8e0cc"}" font-family="Pirata One">${esc(roll)}</text>
            <line x1="${(labelX + nx * 8).toFixed(1)}" y1="${(labelY + ny * 8).toFixed(1)}"
              x2="${tipX.toFixed(1)}" y2="${tipY.toFixed(1)}" stroke="#e8e0cc" stroke-width="1.25"
              marker-end="url(#bossLaneArrow)"/></g>`;
        }
      }
    }
    // Shield arcs the way the boss designer draws them: layered lines hugging
    // the outer edge of every shielded area's hull hexes — one layer per
    // remaining shield charge. Works for stock and designed bosses alike.
    let shieldSvg = "";
    if (opts.shields) {
      const footprint = new Set(cells.map((cell) => cell.q + "," + cell.r));
      for (const cell of cells) {
        if (!cell.area) continue;
        const hp = sb.shield_hp?.[cell.area] ?? 0;
        if (hp <= 0) continue;
        const layers = Math.min(hp, 4);
        const color = palette.stroke(cell.area);
        const [cx, cy] = xy(cell.q, cell.r);
        for (let facing = 0; facing < 6; facing++) {
          const [dq, dr] = Board.DIRECTIONS[facing];
          if (footprint.has((cell.q + dq) + "," + (cell.r + dr))) continue;
          const [ex, ey] = xy(cell.q + dq, cell.r + dr);
          let ux = ex - cx, uy = ey - cy;
          const len = Math.hypot(ux, uy) || 1;
          ux /= len; uy /= len;
          const px = -uy, py = ux, half = size / 2;
          for (let layer = 0; layer < layers; layer++) {
            const mx = cx + ux * (len / 2 + size * (0.30 + layer * 0.18));
            const my = cy + uy * (len / 2 + size * (0.30 + layer * 0.18));
            shieldSvg += `<line class="boss-detail-shield"
              x1="${(mx + px * half).toFixed(1)}" y1="${(my + py * half).toFixed(1)}"
              x2="${(mx - px * half).toFixed(1)}" y2="${(my - py * half).toFixed(1)}"
              stroke="${color}" opacity="${Math.max(0.35, 0.9 - layer * 0.14).toFixed(2)}">
              <title>${esc(areaDisplayName(cell.area))} shield — ${hp} charge${hp === 1 ? "" : "s"}</title></line>`;
          }
        }
      }
    }
    const xs = cells.map((c) => size * 1.5 * c.q), ys = cells.map((c) => size * sq * (c.r + c.q / 2));
    return {
      hullSvg, laneSvg, shieldSvg, xy, size, palette, componentsByHex,
      minX: Math.min(...xs, 0) - size * 5.1,
      maxX: Math.max(...xs, 0) + size * 5.1,
      minY: Math.min(...ys, 0) - size * 4.3,
      maxY: Math.max(...ys, 0) + size * 4.3,
    };
  }

  /* Circuit-board battle board: one vertical action stack per phase, with
     traces running from each component hex to the action chip it powers.
     Desktop lays the stacks off the hull's right side (opts.layout "right");
     mobile keeps them below the hull so the ship can use the narrow width. */
  function battleBoardCircuitSVG(sb, parts, opts = {}) {
    const layout = sb.boss_layout || {};
    const phases = layout.phases || [];
    if (!phases.length) return { svg: "", minX: parts.minX, maxX: parts.maxX, minY: parts.minY, maxY: parts.maxY };
    const componentById = bossComponentById(sb);
    const chipW = 26, chipH = 20, chipGap = 7, colGap = 18, gutter = 8, innerGap = 6;
    // Stacks are two chips wide so they stay short.
    const stackW = chipW * 2 + innerGap;
    const colW = stackW + colGap;
    // Reserve a routing band between the hull and the chips: one horizontal
    // lane per hull trace (wrapped) so the drops don't stack on top of each other.
    let traceCount = 0;
    for (const phase of phases) {
      for (const slot of phase.slots || []) {
        if (slot.slot === "component") traceCount++;
      }
    }
    const laneSpacing = 4.5, laneMax = 12;
    const fleetAlive = (sb.fleet || []).filter((craft) => !craft.destroyed).length;
    // Two layouts: "right" (desktop) hangs the stacks off the hull's starboard
    // side so the wide modal is used and the ship stays big; "below" (mobile)
    // stacks them under the hull for the tall narrow screen.
    const sideways = opts.layout === "right";
    const totalColsW = phases.length * colW - colGap;
    let busTop = 0, busLeft = 0, labelY, chipsTop, firstColCenterX;
    if (sideways) {
      const chipCount = (phase) => (phase.slots || []).length
        + (fleetAlive ? (((layout.fleet_actions || {})[phase.key]) || []).length : 0);
      const maxRows = Math.max(1, ...phases.map((phase) => Math.ceil(chipCount(phase) / 2)));
      busLeft = parts.maxX + 10;
      const busBandW = Math.min(traceCount, laneMax) * laneSpacing + 8;
      firstColCenterX = busLeft + busBandW + gutter + stackW / 2;
      // Stack block vertically centered on the hull.
      const blockH = 22 + maxRows * (chipH + chipGap);
      const blockTop = (parts.minY + parts.maxY) / 2 - blockH / 2;
      labelY = blockTop + 12;
      chipsTop = blockTop + 22;
    } else {
      busTop = parts.maxY + 8;
      const busBandH = Math.min(traceCount, laneMax) * laneSpacing + 8;
      labelY = busTop + busBandH + 12;
      chipsTop = labelY + 8;
      // Columns, one per phase, centered under the hull.
      const hullCenterX = (parts.minX + parts.maxX) / 2;
      firstColCenterX = hullCenterX - totalColsW / 2 + stackW / 2;
    }
    const colCenterX = (p) => firstColCenterX + p * colW;
    let svg = "";
    let busIndex = 0;
    let linkIndex = 0;
    let maxChipBottom = chipsTop;
    phases.forEach((phase, phaseIndex) => {
      const cx = colCenterX(phaseIndex);
      const gutterX = cx - stackW / 2 - gutter; // vertical trace lane left of the stack
      const phaseColor = stackColor(phase.key);
      let chipIndex = 0; // chips fill the stack two per row, left then right
      const chipCenterX = (i) => cx - stackW / 2 + (i % 2) * (chipW + innerGap) + chipW / 2;
      const chipTopY = (i) => chipsTop + Math.floor(i / 2) * (chipH + chipGap);
      // Draw a chip in the next stack cell; returns its {x: centerX, y: topY}.
      const drawChip = (text, active, title, opts = {}) => {
        const { linkId = "", fleet = false, color = "#9aa3b8", tier = null, componentId = "" } = opts;
        const ccx = chipCenterX(chipIndex), cty = chipTopY(chipIndex), sub = chipIndex % 2;
        chipIndex++;
        const rx = fleet ? 10 : 4;
        const strike = !active && !fleet;
        const stroke = active ? color : (fleet ? "#9aa3b8" : "#4a4a55");
        // Fleet chips are informational only — they don't power (or get powered
        // by) anything, so they carry no hover linkage at all.
        const hotspotAttrs = fleet ? "" : ` class="boss-circuit-hotspot" data-link-id="${linkId}"`
          + (tier != null ? ` data-tier="${esc(tier)}"` : "")
          + (componentId ? ` data-component-id="${esc(componentId)}"` : "")
          + ` data-stack-key="${esc(phase.key)}"`;
        svg += `<g${hotspotAttrs}><title>${esc(title)}</title>
          <rect x="${(ccx - chipW / 2).toFixed(1)}" y="${cty.toFixed(1)}" width="${chipW}" height="${chipH}" rx="${rx}"
            fill="${active ? `${color}22` : (fleet ? "rgba(160,160,180,.12)" : "rgba(30,30,38,.9)")}"
            stroke="${stroke}" stroke-width="${active ? 1.4 : 1}" ${active || fleet ? "" : 'stroke-dasharray="3 2"'}/>
          <text x="${ccx.toFixed(1)}" y="${(cty + chipH / 2 + 4).toFixed(1)}" text-anchor="middle" font-size="11" font-weight="700"
            font-family="${SYMBOL_FONT}" fill="${active ? color : (fleet ? "#9aa3b8" : "#555")}">${esc(text)}</text>
          ${strike ? `<line x1="${(ccx - chipW / 2 + 3).toFixed(1)}" y1="${(cty + 3).toFixed(1)}" x2="${(ccx + chipW / 2 - 3).toFixed(1)}" y2="${(cty + chipH - 3).toFixed(1)}" stroke="#883333" stroke-width="1.2"/>` : ""}
        </g>`;
        return { x: ccx, y: cty, sub };
      };
      // Trace a hull hex into a chip, ending in a short downward drop with an
      // arrowhead. Below-mode routes down through a horizontal bus band and the
      // stack's left gutter; sideways-mode routes right through a vertical bus
      // band, then along the gap above the target row.
      const trace = (hx, hy, active, linkId, chip, color) => {
        // Jog in the gap above the target row, staggered per sub-column so two
        // traces into the same row don't overlap.
        const jogY = chip.y - (chip.sub ? 3 : 5);
        const stroke = active ? color : "#4a4a55";
        const route = sideways
          ? (() => {
              const busX = busLeft + (busIndex++ % laneMax) * laneSpacing;
              return `M ${hx.toFixed(1)} ${hy.toFixed(1)} L ${busX.toFixed(1)} ${hy.toFixed(1)} L ${busX.toFixed(1)} ${jogY.toFixed(1)} L ${chip.x.toFixed(1)} ${jogY.toFixed(1)} L ${chip.x.toFixed(1)} ${chip.y.toFixed(1)}`;
            })()
          : (() => {
              const busY = busTop + (busIndex++ % laneMax) * laneSpacing;
              return `M ${hx.toFixed(1)} ${hy.toFixed(1)} L ${hx.toFixed(1)} ${busY.toFixed(1)} L ${gutterX.toFixed(1)} ${busY.toFixed(1)} L ${gutterX.toFixed(1)} ${jogY.toFixed(1)} L ${chip.x.toFixed(1)} ${jogY.toFixed(1)} L ${chip.x.toFixed(1)} ${chip.y.toFixed(1)}`;
            })();
        svg += `<g class="boss-circuit-link${active ? " active" : " inactive"}" data-link-id="${linkId}" data-stack-key="${esc(phase.key)}"
            style="--trace-color:${stroke}" pointer-events="none">
          <path class="boss-circuit-line" d="${route}"
            fill="none" stroke="${stroke}" stroke-width="1.2"
            ${active ? "" : 'stroke-dasharray="3 3"'} stroke-linejoin="round"/>
          <circle class="boss-circuit-dot" cx="${hx.toFixed(1)}" cy="${hy.toFixed(1)}" r="2.2" fill="${stroke}"/>
          <polygon class="boss-circuit-arrow" points="${(chip.x - 3).toFixed(1)},${(chip.y - 4.5).toFixed(1)} ${(chip.x + 3).toFixed(1)},${(chip.y - 4.5).toFixed(1)} ${chip.x.toFixed(1)},${chip.y.toFixed(1)}" fill="${stroke}"/></g>
          <circle class="boss-circuit-hotspot" data-link-id="${linkId}" data-stack-key="${esc(phase.key)}"
            cx="${hx.toFixed(1)}" cy="${hy.toFixed(1)}" r="10" fill="transparent"/>`;
      };
      // Phase label — just the stack name (the kind is carried by each chip now).
      svg += `<text x="${cx.toFixed(1)}" y="${labelY.toFixed(1)}" text-anchor="middle" font-size="14" font-family="Pirata One"
        fill="${phaseColor}">${esc(PHASE_SHORT[phase.key] || phase.key)}</text>`;
      // Display order mirrors resolution: active slots first with moves ahead
      // of attacks; not-yet-active slots sink to the bottom of the stack.
      const orderedSlots = (phase.slots || [])
        .map((slot) => ({ slot, active: bossSlotActive(sb, slot) }))
        .sort((a, b) => {
          const rank = (entry) => (entry.active ? 0 : 2)
            + ((entry.slot.kind || phase.kind) === "move" ? 0 : 1);
          return rank(a) - rank(b);
        });
      for (const { slot, active } of orderedSlots) {
        const kind = slot.kind || phase.kind;
        const color = kindColor(kind);
        const text = slotChipText(sb, slot, componentById);
        const linkId = `phase-${phase.key}-${linkIndex++}`;
        const title = `${slotChipTitle(sb, slot, componentById, active)} - ${kind}`;
        if (slot.slot === "tier") {
          // Progression actions link to their box on the progress track (drawn
          // by the HTML overlay), not to a hull hex.
          drawChip(text, active, title, { linkId, color, tier: slot.tier });
        } else {
          const componentId = slot.slot === "component" ? slot.component_id : "";
          const chip = drawChip(text, active, title, { linkId, color, componentId });
          if (slot.slot === "component") {
            const component = componentById[slot.component_id];
            if (component) trace(...parts.xy(component.q, component.r), active, linkId, chip, color);
          }
        }
      }
      // Fleet chips: craft move before they shoot, same as resolution.
      const fleetKinds = (((layout.fleet_actions || {})[phase.key]) || [])
        .slice().sort((a, b) => (a === "move" ? 0 : 1) - (b === "move" ? 0 : 1));
      for (const kind of fleetKinds) {
        if (!fleetAlive) break;
        drawChip(`▣${KIND_SYMBOL[kind] || ""}`, false, `Fleet x${fleetAlive} - ${kind}`, { fleet: true });
      }
      if (chipIndex > 0) maxChipBottom = Math.max(maxChipBottom, chipTopY(chipIndex - 1) + chipH + chipGap);
    });
    if (sideways) {
      return {
        svg,
        minX: parts.minX,
        maxX: firstColCenterX + (phases.length - 1) * colW + stackW / 2 + 6,
        minY: Math.min(parts.minY, labelY - 16),
        maxY: Math.max(parts.maxY, maxChipBottom + 6),
      };
    }
    const hullCenterX = (parts.minX + parts.maxX) / 2;
    const halfSpan = totalColsW / 2 + gutter + 4;
    return {
      svg,
      minX: Math.min(parts.minX, hullCenterX - halfSpan),
      maxX: Math.max(parts.maxX, hullCenterX + halfSpan),
      minY: parts.minY,
      maxY: maxChipBottom + 6,
    };
  }

  /* The StarBreacher's battle board: internal hull, components, shields,
     circuit-linked action rows, and the discrete progress track. */
  function showBossModal() {
    const sb = effectiveStarBreach();
    if (!sb || !sb.boss_layout) return;
    // Damage lanes stay hidden here — they only show while assigning a lane
    // (the target picker). Shields render as arcs hugging the shielded hull.
    const phoneLayout = document.documentElement.dataset.device === "phone";
    const parts = bossHullParts(sb, { shields: true, size: 20, componentColors: true });
    const circuit = battleBoardCircuitSVG(sb, parts, { layout: phoneLayout ? "below" : "right" });
    const palette = parts.palette;
    const shields = (sb.boss_layout.areas || []).map((area) => {
      const hp = sb.shield_hp?.[area] ?? 0, max = sb.shield_max?.[area] ?? hp;
      return `<tr><td><span class="bmb-swatch" style="background:${palette.stroke(area)}"></span>${esc(areaDisplayName(area))}</td><td>${"🛡".repeat(hp) || "—"} ${hp}/${max}</td></tr>`;
    }).join("");
    const pendingTiers = (sb.tiers_unlocked || []).filter((tier) => !(sb.active_tiers || []).includes(tier));
    const spawnNotes = Object.entries((sb.boss_layout || {}).tier_spawns || {})
      .map(([tier, spawn]) => `Tier ${tier}: spawns ${spawn.count} craft (${String(spawn.location || "").replace("_", " ")})`)
      .join(" · ");
    const overlay = els["picker-overlay"];
    overlay.innerHTML = "";
    overlay.classList.remove("hidden");
    const box = document.createElement("div");
    box.className = "picker boss-board-modal";
    box.innerHTML = `
      <h3>☄ ${esc(sb.boss_name || "The StarBreacher")} — Battle Board</h3>
      <div class="boss-modal-map">
        <svg viewBox="${circuit.minX} ${circuit.minY} ${circuit.maxX - circuit.minX} ${circuit.maxY - circuit.minY}" style="width:100%;height:100%">
          <defs><marker id="bossLaneArrow" markerWidth="7" markerHeight="7" refX="5" refY="2.5" orient="auto">
            <polygon points="0 0, 6 2.5, 0 5" fill="#e8e0cc"/></marker></defs>
          <g class="boss-detail-lanes">${parts.laneSvg}</g>
          <g class="boss-detail-hull">${parts.hullSvg}</g>
          <g class="boss-detail-shields">${parts.shieldSvg}</g>
          <g class="boss-battle-circuit">${circuit.svg}</g>
        </svg>
      </div>
      <div class="boss-modal-bottom">
        <div class="boss-modal-side">
          <h4>Shield Regions</h4>
          <table>${shields}</table>
        </div>
        <div class="boss-modal-center">
          ${progressTrackHTML(sb)}
          ${pendingTiers.length ? `<div style="margin-top:4px;color:#ff9d8a">Tier ${pendingTiers.join(", ")} powers up next round!</div>` : ""}
          ${spawnNotes ? `<div class="opt-sub">${esc(spawnNotes)}</div>` : ""}
        </div>
        <div class="boss-modal-side">
          <h4>Legend</h4>
          <div class="bmb-legend">
            <span>☄ attack</span><span>➤ move</span><span>⬢ base</span>
            <span>★n tier n</span><span>▣ fleet</span><span>🛡 shield gen</span><span>◉ core</span>
          </div>
        </div>
      </div>
      <button class="btn ghost picker-cancel" id="boss-modal-close">Close</button>`;
    overlay.appendChild(box);
    wireBossCircuitHover(box);
    const drawProgressLinks = wireBossProgressLinks(box);
    wireBossMapZoom(box.querySelector(".boss-modal-map"), drawProgressLinks);
    decorateBossTrackWrap(box);
    box.querySelector("#boss-modal-close").addEventListener("click", hidePicker);
    overlay.addEventListener("click", function onOverlay(event) {
      if (event.target === overlay) { hidePicker(); overlay.removeEventListener("click", onOverlay); }
    });
  }

  /* Draw circuit lines from each progression-track box down to the action chip
     it powers. Track boxes are HTML and the chips live in the SVG board, so the
     link is an absolutely-positioned overlay computed from on-screen rects and
     kept in sync as the modal resizes or the map scrolls. */
  function wireBossProgressLinks(box) {
    const map = box.querySelector(".boss-modal-map");
    const link = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    link.setAttribute("class", "boss-progress-links");
    box.style.position = "relative";
    box.appendChild(link);
    const draw = () => {
      if (!box.isConnected) {
        window.removeEventListener("resize", draw);
        if (map) map.removeEventListener("scroll", draw);
        return;
      }
      const boxRect = box.getBoundingClientRect();
      link.setAttribute("viewBox", `0 0 ${boxRect.width.toFixed(1)} ${boxRect.height.toFixed(1)}`);
      link.setAttribute("width", boxRect.width.toFixed(1));
      link.setAttribute("height", boxRect.height.toFixed(1));
      const mapRect = map ? map.getBoundingClientRect() : boxRect;
      let inner = "";
      box.querySelectorAll(".bmb-track [data-tier]").forEach((trackBox) => {
        const tier = trackBox.dataset.tier;
        const sel = window.CSS && CSS.escape ? CSS.escape(tier) : tier;
        const chip = box.querySelector(`.boss-battle-circuit [data-tier="${sel}"]`);
        if (!chip) return;
        const tr = trackBox.getBoundingClientRect();
        const cr = chip.getBoundingClientRect();
        const color = chip.querySelector("rect")?.getAttribute("stroke") || "#d9a6ff";
        const x1 = tr.left + tr.width / 2 - boxRect.left, y1 = tr.top - boxRect.top;
        // When the chip is panned/zoomed out of the map viewport it's clipped
        // away — truncate the connector at the map edge (faded, no arrowhead)
        // so the link still reads without pointing at empty space.
        const chipCx = cr.left + cr.width / 2, chipCy = cr.top + cr.height / 2;
        const visible = chipCx >= mapRect.left && chipCx <= mapRect.right
          && chipCy >= mapRect.top && chipCy <= mapRect.bottom;
        const x2 = (visible ? chipCx : Math.min(mapRect.right - 8, Math.max(mapRect.left + 8, chipCx))) - boxRect.left;
        const y2 = (visible ? cr.bottom : mapRect.bottom - 2) - boxRect.top;
        const midY = (y1 + y2) / 2;
        inner += `<path d="M ${x2.toFixed(1)} ${y2.toFixed(1)} C ${x2.toFixed(1)} ${midY.toFixed(1)}, ${x1.toFixed(1)} ${midY.toFixed(1)}, ${x1.toFixed(1)} ${y1.toFixed(1)}"
            fill="none" stroke="${color}" stroke-width="1.4" stroke-dasharray="4 3" opacity="${visible ? ".7" : ".35"}"/>
          <circle cx="${x1.toFixed(1)}" cy="${y1.toFixed(1)}" r="2.4" fill="${color}"/>
          ${visible ? `<polygon points="${(x2 - 3).toFixed(1)},${(y2 + 4.5).toFixed(1)} ${(x2 + 3).toFixed(1)},${(y2 + 4.5).toFixed(1)} ${x2.toFixed(1)},${(y2 + 0.5).toFixed(1)}" fill="${color}"/>` : ""}`;
      });
      link.innerHTML = inner;
    };
    requestAnimationFrame(draw);
    window.addEventListener("resize", draw);
    if (map) map.addEventListener("scroll", draw);
    return draw;
  }

  /* Zoom + pan for the boss battle-board map. Works by shrinking/shifting the
     SVG viewBox — the browser re-renders the vectors at every zoom level, so
     the board stays razor sharp (a CSS transform would scale a rasterized
     bitmap and blur). Wheel zooms toward the cursor, dragging pans, and
     two-finger pinch zooms/pans on touch devices. */
  function wireBossMapZoom(map, onChange) {
    const svg = map && map.querySelector("svg");
    if (!svg) return;
    const base = (svg.getAttribute("viewBox") || "0 0 100 100").split(/[\s,]+/).map(Number);
    const MIN_SCALE = 1, MAX_SCALE = 8;
    let scale = 1;
    let cx = base[0] + base[2] / 2, cy = base[1] + base[3] / 2; // view center, board coords
    const apply = () => {
      const w = base[2] / scale, h = base[3] / scale;
      // Keep the window inside the base board — no panning into the void.
      cx = Math.min(base[0] + base[2] - w / 2, Math.max(base[0] + w / 2, cx));
      cy = Math.min(base[1] + base[3] - h / 2, Math.max(base[1] + h / 2, cy));
      svg.setAttribute("viewBox", `${(cx - w / 2).toFixed(2)} ${(cy - h / 2).toFixed(2)} ${w.toFixed(2)} ${h.toFixed(2)}`);
      if (onChange) onChange();
    };
    // Client px → board coords (getScreenCTM handles the meet letterboxing).
    const toBoard = (clientX, clientY) => {
      const ctm = svg.getScreenCTM();
      if (!ctm) return { x: cx, y: cy };
      return new DOMPoint(clientX, clientY).matrixTransform(ctm.inverse());
    };
    // Board units per client pixel, for converting drag deltas.
    const unitsPerPx = () => {
      const ctm = svg.getScreenCTM();
      return ctm ? 1 / ctm.a : 1;
    };
    const zoomAt = (clientX, clientY, factor) => {
      const before = toBoard(clientX, clientY);
      scale = Math.min(MAX_SCALE, Math.max(MIN_SCALE, scale * factor));
      apply();
      // One correction pass keeps the point under the cursor fixed (exact,
      // since the letterbox offset moves linearly with the viewBox).
      const after = toBoard(clientX, clientY);
      cx += before.x - after.x;
      cy += before.y - after.y;
      apply();
    };
    map.addEventListener("wheel", (event) => {
      event.preventDefault();
      zoomAt(event.clientX, event.clientY, event.deltaY < 0 ? 1.15 : 1 / 1.15);
    }, { passive: false });
    // Dragging must never start a text selection (a selection swallows
    // subsequent drags until it's cleared).
    map.addEventListener("dragstart", (event) => event.preventDefault());
    const pointers = new Map();
    let pinchDist = 0;
    map.addEventListener("pointerdown", (event) => {
      event.preventDefault();
      map.setPointerCapture(event.pointerId);
      pointers.set(event.pointerId, { x: event.clientX, y: event.clientY });
      pinchDist = 0;
    });
    map.addEventListener("pointermove", (event) => {
      const pointer = pointers.get(event.pointerId);
      if (!pointer) return;
      if (pointers.size === 1) {
        const k = unitsPerPx();
        cx -= (event.clientX - pointer.x) * k;
        cy -= (event.clientY - pointer.y) * k;
        pointer.x = event.clientX; pointer.y = event.clientY;
        apply();
      } else if (pointers.size === 2) {
        const other = Array.from(pointers.entries()).find(([id]) => id !== event.pointerId)[1];
        const prevMid = { x: (pointer.x + other.x) / 2, y: (pointer.y + other.y) / 2 };
        pointer.x = event.clientX; pointer.y = event.clientY;
        const mid = { x: (pointer.x + other.x) / 2, y: (pointer.y + other.y) / 2 };
        const dist = Math.hypot(pointer.x - other.x, pointer.y - other.y) || 1;
        const k = unitsPerPx();
        cx -= (mid.x - prevMid.x) * k;
        cy -= (mid.y - prevMid.y) * k;
        if (pinchDist) zoomAt(mid.x, mid.y, dist / pinchDist);
        else apply();
        pinchDist = dist;
      }
    });
    const release = (event) => { pointers.delete(event.pointerId); pinchDist = 0; };
    map.addEventListener("pointerup", release);
    map.addEventListener("pointercancel", release);
  }

  /* When the progress track wraps, mark the last box of each row with a small
     loop arrow so it reads as "continues on the next row". */
  function decorateBossTrackWrap(box) {
    const track = box.querySelector(".bmb-track");
    if (!track) return;
    const update = () => {
      if (!box.isConnected) { window.removeEventListener("resize", update); return; }
      const boxes = Array.from(track.querySelectorAll(".bmb-box"));
      boxes.forEach((node) => node.classList.remove("bmb-wrap-end"));
      for (let i = 0; i < boxes.length - 1; i++) {
        // A new row starts when the next box jumps back to the left. (offsetTop
        // won't do — centered boxes of differing heights shift it within a row.)
        if (boxes[i + 1].offsetLeft < boxes[i].offsetLeft) boxes[i].classList.add("bmb-wrap-end");
      }
    };
    requestAnimationFrame(update);
    window.addEventListener("resize", update);
  }

  /* Hovering a component hex or an action chip lights up the whole circuit:
     the trace, the chip, the hull component, and (for progression actions)
     the box on the progress track. */
  function wireBossCircuitHover(root) {
    const links = Array.from(root.querySelectorAll(".boss-circuit-link"));
    const hotspots = Array.from(root.querySelectorAll(".boss-circuit-hotspot"));
    const cssEscape = (value) => (window.CSS && CSS.escape ? CSS.escape(String(value)) : String(value));
    const setHot = (target, on) => {
      const linkId = target.dataset.linkId;
      const stackKey = target.dataset.stackKey;
      const matches = (el) => (linkId
        ? el.dataset.linkId === linkId
        : stackKey && el.dataset.stackKey === stackKey);
      for (const link of links) {
        if (matches(link)) link.classList.toggle("hot", on);
      }
      for (const spot of hotspots) {
        if (!matches(spot)) continue;
        spot.classList.toggle("hot", on);
        if (spot.dataset.componentId) {
          root.querySelectorAll(`.boss-component-node[data-component-id="${cssEscape(spot.dataset.componentId)}"]`)
            .forEach((node) => node.classList.toggle("hot", on));
        }
        if (spot.dataset.tier != null) {
          root.querySelectorAll(`.bmb-track [data-tier="${cssEscape(spot.dataset.tier)}"]`)
            .forEach((node) => node.classList.toggle("hot", on));
        }
      }
    };
    hotspots.forEach((target) => {
      target.addEventListener("mouseenter", () => setHot(target, true));
      target.addEventListener("mouseleave", () => setHot(target, false));
    });
    // The whole hull hex is a hover target too (the trace hotspot circle only
    // covers its center).
    root.querySelectorAll(".boss-component-node").forEach((node) => {
      const spot = hotspots.find((s) => s.dataset.componentId === node.dataset.componentId);
      if (!spot) return;
      node.addEventListener("mouseenter", () => setHot(spot, true));
      node.addEventListener("mouseleave", () => setHot(spot, false));
    });
  }

  /* Pick a shield region on the boss hull (with confirm), and — for the
     Fighting Ace — optionally call a preferred damage lane in that region.
     Resolves {target: "boss:<area>", lane: <2-8>|null} or null. */
  function showBossRegionPicker({ preselect = null } = {}) {
    return new Promise((resolve) => {
      const sb = view.star_breach;
      if (!sb || !sb.boss_layout) return resolve(null);
      const alive = bossAliveAreas();
      const isAce = myRoles().includes("fighting_ace");
      let selected = preselect && alive[preselect] ? preselect : null;
      let lanePref = null;
      const overlay = els["picker-overlay"];
      overlay.innerHTML = "";
      overlay.classList.remove("hidden");
      const box = document.createElement("div");
      box.className = "picker boss-region-picker";
      overlay.appendChild(box);
      const finish = (value) => { hidePicker(); resolve(value); };
      const render = () => {
        const parts = bossHullParts(sb, {
          lanes: !!selected,
          laneAreaFilter: selected,
          laneClickable: isAce && !!selected,
          highlightLane: lanePref,
          shields: true,
          clickableAreas: alive,
          selectedArea: selected,
        });
        const palette = parts.palette;
        const regionChips = (sb.boss_layout.areas || []).filter((area) => alive[area]).map((area) => {
          const hp = sb.shield_hp?.[area] ?? 0, max = sb.shield_max?.[area] ?? hp;
          return `<button type="button" class="brp-region ${selected === area ? "picked" : ""}" data-area="${esc(area)}"
            style="border-color:${palette.stroke(area)};${selected === area ? `background:${palette.stroke(area)}33` : ""}">
            <span class="bmb-swatch" style="background:${palette.stroke(area)}"></span>${esc(areaDisplayName(area))} 🛡${hp}/${max}</button>`;
        }).join("");
        const lanes = selected ? Object.keys((sb.boss_layout.damage_lanes || {})[selected] || {}).sort((a, b) => a - b) : [];
        const aceRow = isAce && selected ? `
          <div class="brp-lanes">
            <span class="opt-sub">Fighting Ace — preferred damage lane (the ±1 shift steers toward it):</span>
            <button type="button" class="brp-lane ${lanePref == null ? "picked" : ""}" data-lane="">auto</button>
            ${lanes.map((roll) => `<button type="button" class="brp-lane ${String(lanePref) === String(roll) ? "picked" : ""}" data-lane="${esc(roll)}">${esc(roll)}</button>`).join("")}
          </div>` : "";
        box.innerHTML = `
          <h3>☄ Target the ${esc(sb.boss_name || "StarBreacher")}</h3>
          <div class="opt-sub">Click a shield region on the hull (or a button), then confirm.</div>
          <div class="boss-region-map">
            <svg viewBox="${parts.minX} ${parts.minY} ${parts.maxX - parts.minX} ${parts.maxY - parts.minY}" style="width:100%;max-height:300px">
              <defs><marker id="bossLaneArrow" markerWidth="7" markerHeight="7" refX="5" refY="2.5" orient="auto">
                <polygon points="0 0, 6 2.5, 0 5" fill="#e8e0cc"/></marker></defs>
              <g class="boss-detail-lanes">${parts.laneSvg}</g>
              <g class="boss-detail-hull">${parts.hullSvg}</g>
              <g class="boss-detail-shields">${parts.shieldSvg}</g>
            </svg>
          </div>
          <div class="brp-regions">${regionChips}</div>
          ${aceRow}
          <div class="brp-actions">
            <button class="btn ghost" id="brp-cancel">Belay that</button>
            <button class="btn gold" id="brp-confirm" ${selected ? "" : "disabled"}>
              ${selected ? `⚔ Fire on ${esc(areaDisplayName(selected))}${lanePref != null ? ` (lane ${lanePref})` : ""}` : "Pick a region"}
            </button>
          </div>`;
        box.querySelectorAll("[data-area]").forEach((node) => {
          node.addEventListener("click", () => {
            const area = node.dataset.area;
            if (!alive[area]) return;
            if (selected !== area) { selected = area; lanePref = null; }
            render();
          });
        });
        box.querySelectorAll("[data-lane]").forEach((node) => {
          node.addEventListener("click", () => {
            const value = node.dataset.lane;
            lanePref = value === "" || String(lanePref) === String(value) ? null : parseInt(value, 10);
            render();
          });
        });
        box.querySelector("#brp-cancel").addEventListener("click", () => finish(null));
        box.querySelector("#brp-confirm").addEventListener("click", () => {
          if (selected) finish({ target: "boss:" + selected, lane: lanePref });
        });
      };
      render();
    });
  }

  /* Co-op target list: the boss (region picked on its hull board), living
     hunter-killers, and (for the Engineer) crew ships to repair. */
  function coopTargetOptions() {
    const sb = view.star_breach;
    if (!sb) return [];
    const options = [];
    const areaAlive = bossAliveAreas();
    if (Object.keys(areaAlive).length) {
      const shields = (sb.boss_layout?.areas || [])
        .filter((area) => areaAlive[area])
        .map((area) => `${sb.shield_hp?.[area] ?? 0}`)
        .join("/");
      options.push({
        icon: "☄", value: "__boss__",
        label: sb.boss_name || "The StarBreacher",
        sub: `pick a shield region · shields ${shields}`,
      });
    }
    for (const craft of sb.fleet || []) {
      if (craft.destroyed) continue;
      options.push({
        icon: "▣", value: "craft:" + craft.id,
        label: `${craft.color} Hunter-Killer`,
        sub: `${craft.hp}/${craft.max_hp} HP`,
      });
    }
    if (myRoles().includes("engineer")) {
      for (const pid of seatOrder()) {
        const player = view.players[pid];
        if (!player || player.eliminated || (player.ship || {}).destroyed) continue;
        const damage = (player.ship.destroyed_components || []).length;
        options.push({
          icon: "🔧", value: pid,
          label: `Repair ${displayName(pid)}`,
          sub: damage ? `${damage} damaged` : `${player.ship.shields} shields`,
        });
      }
    }
    return options;
  }

  function showPicker(title, options, allowCancel = true) {
    return new Promise((resolve) => {
      const overlay = els["picker-overlay"];
      overlay.innerHTML = "";
      overlay.classList.remove("hidden");
      const box = document.createElement("div");
      box.className = "picker";
      box.innerHTML = `<h3>${esc(title)}</h3>`;
      const row = document.createElement("div");
      row.className = "picker-options";
      for (const option of options) {
        const button = document.createElement("div");
        button.className = "picker-option" + (option.desperate ? " desperate" : "");
        button.innerHTML = `<div class="opt-icon">${option.icon || ""}</div>
          <div class="opt-label">${esc(option.label)}</div>
          ${option.sub ? `<div class="opt-sub">${esc(option.sub)}</div>` : ""}`;
        button.addEventListener("click", () => { hidePicker(); resolve(option.value); });
        row.appendChild(button);
      }
      box.appendChild(row);
      if (allowCancel) {
        const cancel = document.createElement("button");
        cancel.className = "btn ghost picker-cancel";
        cancel.textContent = "Belay that";
        cancel.addEventListener("click", () => { hidePicker(); targetResolver = null; resolve(null); });
        box.appendChild(cancel);
      }
      overlay.appendChild(box);
    });
  }

  function hidePicker() {
    els["picker-overlay"].classList.add("hidden");
    els["picker-overlay"].innerHTML = "";
  }

  function myShipComponents() {
    return ((myPlayer() || {}).ship || {}).component_layout || [];
  }

  function destroyedComponentIds() {
    return (((myPlayer() || {}).ship || {}).destroyed_components || []);
  }

  function damagedComponents() {
    const destroyed = new Set(destroyedComponentIds());
    return myShipComponents().filter((component) => destroyed.has(component.id));
  }

  function intactComponents() {
    const destroyed = new Set(destroyedComponentIds());
    return myShipComponents().filter((component) => !destroyed.has(component.id));
  }

  function componentDistance(a, b) {
    const as = -a.q - a.r;
    const bs = -b.q - b.r;
    return Math.max(Math.abs(a.q - b.q), Math.abs(a.r - b.r), Math.abs(as - bs));
  }

  function isAdjacentToIntact(component, destroyedSet) {
    return myShipComponents().some((other) => other.id !== component.id
      && !destroyedSet.has(other.id)
      && componentDistance(component, other) === 1);
  }

  async function pickComponents(title, components, count) {
    const picked = [];
    for (let index = 0; index < count; index++) {
      const options = components
        .filter((component) => !picked.includes(component.id))
        .map((component) => ({
          icon: picked.length + 1,
          label: component.name,
          sub: component.type,
          value: component.id,
        }));
      if (!options.length) {
        App.toast("No valid hull tiles for that repair.");
        return null;
      }
      const choice = await showPicker(`${title} (${index + 1}/${count})`, options);
      if (!choice) return null;
      picked.push(choice);
    }
    return picked;
  }

  async function beginPlacement(card, presetSlot = null) {
    orderTrace("placement_started", {
      card_id: card.id,
      card_name: card.name,
      preset_slot: presetSlot,
      family: card.family || card.effect?.family || null,
      has_desperate: !!card.desperate_face,
      no_basic_face: !!card.no_basic_face,
    });
    const selection = {
      card_id: card.id,
      face: "front",
      orientation: "up",
      mode: null,
      target_player_id: null,
      repair_component_ids: [],
      reconfigure_from_component_ids: [],
      reconfigure_to_component_ids: [],
      ace_lane_preference: null,
      card,
      family: null,
    };

    // 1. face
    if (card.no_basic_face) selection.face = "desperate";
    else if (card.desperate_face) {
      const face = await showPicker(card.name, [
        { icon: "⚓", label: "Basic side", sub: Cards.describeBasic(card), value: "front" },
        { icon: "☄", label: "DESPERATE", sub: Cards.describeDesperate(card.desperate_face), value: "desperate", desperate: true },
      ]);
      orderTrace(face ? "face_selected" : "face_cancelled", { card_id: card.id, face });
      if (!face) return;
      selection.face = face;
    }

    // 2. family / mode / orientation options
    let orientationOptions = [];
    if (selection.face === "front") {
      if (card.is_hybrid) {
        const mode = await showPicker("Use it for…", [
          { icon: "➤", label: "Move " + (card.effect.value || card.value), value: "move" },
          { icon: "☄", label: "Cannons +1 dmg", value: "attack" },
        ]);
        orderTrace(mode ? "front_hybrid_mode_selected" : "front_hybrid_mode_cancelled", { card_id: card.id, mode });
        if (!mode) return;
        selection.mode = mode;
        selection.family = mode;
      } else {
        selection.family = card.effect.family;
      }
      orientationOptions = card.effect.orientation_options || ["forward"];
    } else {
      const face = card.desperate_face;
      const opts = face.orientation_options || ["forward"];
      if (face.family === "hybrid") {
        const mode = await showPicker("Desperate gambit", [
          { icon: "➤", label: "As a move", value: "move" },
          { icon: "☄", label: "As an attack", value: "attack" },
        ]);
        orderTrace(mode ? "desperate_hybrid_mode_selected" : "desperate_hybrid_mode_cancelled", { card_id: card.id, mode });
        if (!mode) return;
        selection.mode = mode;
        selection.family = mode;
        orientationOptions = opts;
      } else if (face.repair_components || face.reconfigure_components) {
        const mode = await showPicker("Patch it during...", [
          { icon: "M", label: "Move stack", value: "move" },
          { icon: "A", label: "Attack stack", value: "attack" },
        ]);
        orderTrace(mode ? "patch_mode_selected" : "patch_mode_cancelled", { card_id: card.id, mode });
        if (!mode) return;
        selection.mode = mode;
        selection.family = mode;
        orientationOptions = opts;
      } else if (opts.includes("u_turn_move") || opts.includes("u_turn_attack")) {
        const pick = await showPicker("Crazy Ivan!", opts.map((option) => ({
          icon: option === "u_turn_attack" ? "☄" : "➤",
          label: Cards.orientationLabel(option),
          value: option,
        })));
        orderTrace(pick ? "crazy_ivan_selected" : "crazy_ivan_cancelled", { card_id: card.id, orientation: pick });
        if (!pick) return;
        selection.orientation = pick;
        selection.family = pick === "u_turn_attack" ? "attack" : "move";
        orientationOptions = [pick];
      } else {
        selection.family = face.family;
        orientationOptions = opts;
      }
    }

    // 3. move orientation
    if (selection.family === "move" && !selection.orientation.startsWith("u_turn")) {
      if (orientationOptions.length > 1) {
        const orientation = await showPicker("Set yer heading", orientationOptions.map((option) => ({
          icon: Cards.orientationLabel(option).split(" ")[0],
          label: Cards.orientationLabel(option).split(" ").slice(1).join(" ") || option,
          value: option,
        })));
        orderTrace(orientation ? "orientation_selected" : "orientation_cancelled", { card_id: card.id, orientation });
        if (!orientation) return;
        selection.orientation = orientation;
      } else {
        selection.orientation = orientationOptions[0] || "forward";
      }
    }

    if (selection.face === "desperate" && card.desperate_face) {
      if (card.desperate_face.repair_components) {
        const picked = await pickComponents("Restore which hull tile?", damagedComponents(), card.desperate_face.repair_components);
        orderTrace(picked ? "repair_components_selected" : "repair_components_cancelled", { card_id: card.id, component_ids: picked || [] });
        if (!picked) return;
        selection.repair_component_ids = picked;
      }
      if (card.desperate_face.reconfigure_components) {
        const count = card.desperate_face.reconfigure_components;
        const from = await pickComponents("Move damage from...", damagedComponents(), count);
        orderTrace(from ? "reconfigure_from_selected" : "reconfigure_from_cancelled", { card_id: card.id, component_ids: from || [] });
        if (!from) return;
        const interimDestroyed = new Set(destroyedComponentIds());
        from.forEach((id) => interimDestroyed.delete(id));
        const to = await pickComponents(
          "Move damage to...",
          intactComponents().filter((component) => !from.includes(component.id) && isAdjacentToIntact(component, interimDestroyed)),
          count
        );
        orderTrace(to ? "reconfigure_to_selected" : "reconfigure_to_cancelled", { card_id: card.id, component_ids: to || [] });
        if (!to) return;
        selection.reconfigure_from_component_ids = from;
        selection.reconfigure_to_component_ids = to;
      }
    }

    // 4. attack target. Untargeted attacks (e.g. hybrid "+1 damage" cannons)
    // fire straight ahead on their own — the engine only targets the volley
    // when a Targeted card in the same stack marks a ship.
    if (selection.family === "attack") {
      const needsTarget = selection.face === "desperate"
        ? (selection.orientation === "u_turn_attack" ? false : !!card.desperate_face.requires_target)
        : (card.is_hybrid ? false : !!card.requires_target);
      if (!needsTarget) {
        selection.untargeted = true;
      }
      if (needsTarget && view.star_breach) {
        const options = coopTargetOptions();
        if (!options.length) {
          orderTrace("target_options_empty", { card_id: card.id, star_breach: true });
          App.toast("Nothing left to shoot at.");
          return;
        }
        let chosen = await new Promise((resolve) => {
          targetResolver = resolve;
          showPicker("Mark yer target (or click the boss)", options)
            .then((value) => { if (targetResolver) { targetResolver = null; resolve(value); } });
        });
        if (chosen === "__boss__" || (chosen && chosen.startsWith && chosen.startsWith("boss:"))) {
          // Second step: pick (or confirm) the shield region on the hull board.
          const pick = await showBossRegionPicker({
            preselect: chosen === "__boss__" ? null : chosen.split(":")[1],
          });
          if (!pick) {
            orderTrace("target_cancelled", { card_id: card.id, star_breach: true, stage: "region" });
            return;
          }
          chosen = pick.target;
          selection.ace_lane_preference = pick.lane ?? null;
        }
        if (!chosen) {
          orderTrace("target_cancelled", { card_id: card.id, star_breach: true });
          return;
        }
        orderTrace("target_selected", { card_id: card.id, target: chosen, star_breach: true, ace_lane: selection.ace_lane_preference ?? null });
        selection.target_player_id = chosen;
      } else if (needsTarget) {
        const enemies = seatOrder().filter((pid) => {
          const player = view.players[pid];
          return pid !== you && player && !player.eliminated && !(player.ship || {}).destroyed;
        });
        if (!enemies.length) {
          orderTrace("target_options_empty", { card_id: card.id, star_breach: false });
          App.toast("No targets left afloat.");
          return;
        }
        const chosen = await new Promise((resolve) => {
          targetResolver = resolve;
          showPicker("Mark yer target (or click a ship)", enemies.map((pid) => ({
            icon: "☠", label: displayName(pid), value: pid,
          }))).then((value) => { if (targetResolver) { targetResolver = null; resolve(value); } });
        });
        if (!chosen) {
          orderTrace("target_cancelled", { card_id: card.id, star_breach: false });
          return;
        }
        orderTrace("target_selected", { card_id: card.id, target: chosen, star_breach: false });
        selection.target_player_id = chosen;
      }
    }

    // 5. slot choice (skipped when the card was dropped on / armed to a slot)
    const allowMixed = !!view.rules_config?.allow_mixed_card_type_stacks;
    const canTake = (slot) => slot.cards.length < 2
      && (allowMixed || !slot.cards.length || slot.cards[0].family === selection.family);
    let slotIndex = presetSlot;
    if (slotIndex !== null && slotIndex !== undefined && !canTake(draft.slots[slotIndex])) {
      App.toast("That stack can't take this card — same type, max two.");
      return;
    }
    if (slotIndex === null || slotIndex === undefined) {
      const eligible = draft.slots
        .map((slot, index) => ({ slot, index }))
        .filter(({ slot }) => canTake(slot));
      if (!eligible.length) { App.toast("No stack can take that card — same type, max two."); return; }
      slotIndex = await showPicker("Assign to which action?", eligible.map(({ index, slot }) => ({
        icon: ["Ⅰ", "Ⅱ", "Ⅲ"][index],
        label: "Action " + (index + 1),
        sub: slot.cards.length ? "stack with " + slot.cards[0].card.name : "empty",
        value: index,
      })));
      orderTrace(slotIndex === null || slotIndex === undefined ? "slot_cancelled" : "slot_selected", { card_id: card.id, slot_index: slotIndex });
      if (slotIndex === null || slotIndex === undefined) return;
    }
    const slot = draft.slots[slotIndex];
    // Targeted attacks in one stack must agree on the target.
    if (selection.family === "attack" && slot.cards.length) {
      const existing = slot.cards[0].target_player_id;
      if (existing && selection.target_player_id && existing !== selection.target_player_id) {
        selection.target_player_id = existing;
        App.toast("Both cannons aim at " + targetLabel(existing) + " — one volley, one target.", true);
      }
    }
    slot.cards.push(selection);
    orderTrace("card_placed", {
      card_id: selection.card_id,
      face: selection.face,
      family: selection.family,
      orientation: selection.orientation,
      mode: selection.mode,
      target: selection.target_player_id,
      slot_index: slotIndex,
    });
    saveDraft();
    renderOrdersPanel();
  }

  async function submitOrders() {
    const payload = {
      stacks: draft.slots.map((slot, index) => ({
        action_number: index + 1,
        seal_mode: slot.seal,
        cards: slot.cards.map((selection) => ({
          card_id: selection.card_id,
          face: selection.face,
          orientation: selection.orientation,
          mode: selection.mode,
          target_player_id: selection.target_player_id,
          repair_component_ids: selection.repair_component_ids || [],
          reconfigure_from_component_ids: selection.reconfigure_from_component_ids || [],
          reconfigure_to_component_ids: selection.reconfigure_to_component_ids || [],
          ace_lane_preference: selection.ace_lane_preference ?? null,
        })),
      })),
    };
    orderTrace("submit_started", {
      stack_sizes: payload.stacks.map((stack) => stack.cards.length),
      cards: payload.stacks.flatMap((stack) => stack.cards.map((card) => card.card_id)),
    });
    els["btn-submit-orders"].disabled = true;
    try {
      const response = await API.submitOrders(gameId, payload);
      draft = emptyDraft();
      armedSlot = null;
      orderTrace("submit_succeeded");
      saveDraft();
      Board.clearPreview();
      App.toast("Orders sealed. Fair winds!", true);
      applyPayload(response, false);
    } catch (error) {
      orderTrace("submit_failed", { message: error.message || String(error), status: error.status || null });
      App.toast(error.message);
      els["btn-submit-orders"].disabled = false;
    }
  }

  // ── order preview (movement paths + shot arrows with hit odds) ────────
  function pDiceAtLeast(dice, needed) {
    if (needed <= dice) return 1;
    if (needed > dice * 6) return 0;
    let count = 0;
    let total = 0;
    const roll = (remaining, sum) => {
      if (!remaining) {
        total++;
        if (sum >= needed) count++;
        return;
      }
      for (let value = 1; value <= 6; value++) roll(remaining - 1, sum + value);
    };
    roll(dice, 0);
    return count / total;
  }

  function activeStarfall(id) {
    return view && view.active_starfall_id === id && view.active_starfall_round === view.round_number;
  }

  function captainId(player) {
    return player && (player.captain_id || (player.captain && player.captain.id));
  }

  function modifiedMoveValue(face, player) {
    let value = face.value || 0;
    if (!face.warp_destination && !face.movement_disabled) {
      if (captainId(player) === "riley_rounder") value += 1;
      if (activeStarfall("gusty_winds")) value += 1;
    }
    return value;
  }

  function expectedTargetMove(targetId) {
    const totals = [];
    for (const event of view.event_log || []) {
      if (event.type === "movement_resolved" && event.player_id === targetId && !event.overdrive_copy) {
        totals.push(event.movement_this_action || 0);
      }
    }
    const recent = totals.slice(-6);
    if (!recent.length) return 2;
    return recent.reduce((sum, value) => sum + value, 0) / recent.length;
  }

  function clampHex(q, r) {
    const radius = Board.RADIUS;
    const s = -q - r;
    const dist = Math.max(Math.abs(q), Math.abs(r), Math.abs(s));
    if (dist <= radius) return [q, r];
    const factor = radius / dist;
    const fq = q * factor, fr = r * factor, fs = s * factor;
    let iq = Math.round(fq), ir = Math.round(fr), is = Math.round(fs);
    const dq = Math.abs(iq - fq), dr = Math.abs(ir - fr), ds = Math.abs(is - fs);
    if (dq > dr && dq > ds) iq = -ir - is;
    else if (dr > ds) ir = -iq - is;
    return [iq, ir];
  }

  /* Mirror of the engine's per-card movement (see rules/engine.py). */
  function simMove(pos, selection) {
    const card = selection.card;
    const me = myPlayer();
    const desperate = selection.face === "desperate";
    const face = desperate ? card.desperate_face : card.effect;
    const value = modifiedMoveValue(face, me);
    let { q, r, facing } = pos;
    const choice = selection.orientation === "up" ? "forward" : selection.orientation;
    const step = (heading, distance) => {
      const [dq, dr] = Board.DIRECTIONS[((heading % 6) + 6) % 6];
      q += dq * distance; r += dr * distance;
    };
    if (desperate && card.desperate_face.warp_destination) {
      return { pos, moved: 0 };  // warp destination is board-state dependent; no path preview
    }
    if (desperate && card.desperate_face.double_turn_after_move) {
      step(facing, value);
      facing = choice === "turn_left" ? (facing + 2) % 6 : (facing + 4) % 6;
    } else if (choice === "u_turn_move" || (desperate && card.desperate_face.u_turn_move)) {
      facing = (facing + 3) % 6;
      step(facing, value);
    } else if (choice === "slip_right" || choice === "slip_left") {
      step((facing + (choice === "slip_right" ? 5 : 1)) % 6, value);
    } else {
      if (choice === "turn_left") facing = (facing + 1) % 6;
      else if (choice === "turn_right") facing = (facing + 5) % 6;
      step(facing, value);
    }
    [q, r] = clampHex(q, r);
    return { pos: { q, r, facing }, moved: value };
  }

  function previewPositionBeforeSlot(slotIndex) {
    let pos = { q: myPlayer().ship.q, r: myPlayer().ship.r, facing: myPlayer().ship.facing };
    for (let index = 0; index < slotIndex; index++) {
      pos = previewPositionAfterSlot(pos, draft.slots[index]);
    }
    return pos;
  }

  function previewPositionAfterSlot(startPos, slot) {
    let pos = { ...startPos };
    const actionCopy = slot.seal === "overdrive" && overdriveCopiesAction();
    const cardCopy = slot.seal === "overdrive" && overdriveCopiesCards();
    const passes = actionCopy || cardCopy ? 2 : 1;
    for (let pass = 0; pass < passes; pass++) {
      for (const selection of slot.cards.filter((s) => s.family === "move")) {
        if (
          pass > 0
          && actionCopy
          && selection.face === "desperate"
          && !view.rules_config?.allow_overdrive_desperation
        ) continue;
        pos = simMove(pos, selection).pos;
      }
    }
    return pos;
  }

  function attackProjectionsForSlot(slotIndex, startPos = null) {
    const me = myPlayer();
    if (!view || !me || !me.ship) return [];
    const slot = draft.slots[slotIndex];
    if (!slot) return [];
    const pos = startPos ? { ...startPos } : previewPositionAfterSlot(previewPositionBeforeSlot(slotIndex), slot);
    const attackSelections = slot.cards.filter((s) => s.family === "attack");
    if (!attackSelections.length) return [];
    const primary = attackProjectionsForSelections(slotIndex, pos, attackSelections, false, slot.seal === "overdrive" && overdriveCopiesCards());
    if (slot.seal !== "overdrive") return primary;
    if (overdriveCopiesCards()) return primary;
    const copySelections = attackSelections.filter((selection) => (
      selection.face !== "desperate" || view.rules_config?.allow_overdrive_desperation
    ));
    return primary.concat(attackProjectionsForSelections(slotIndex, pos, copySelections, true, false));
  }

  function attackProjectionsForSelections(slotIndex, pos, attackSelections, overdriveCopy, combineCards) {
    if (!attackSelections.length) return [];
    let target = null;
    for (const selection of attackSelections) {
      if (selection.target_player_id) target = selection.target_player_id;
    }
    let ahead = false;
    if (!target) {
      target = forwardTarget(pos);
      ahead = true;
    }
    if (!target) {
      if (!ahead) return [];
      const [dq, dr] = Board.DIRECTIONS[((pos.facing % 6) + 6) % 6];
      return [{
        label: `A${["I", "II", "III"][slotIndex]} ⇢`,
        from: { q: pos.q, r: pos.r },
        to: { q: pos.q + dq * 4, r: pos.r + dr * 4 },
        summary: "No ship ahead",
        noTarget: true,
      }];
    }
    let enemy = view.players[target];
    if ((!enemy || !enemy.ship) && view.star_breach) enemy = coopTargetStub(target, pos);
    if (!enemy || !enemy.ship) return [];
    return [attackProjection(slotIndex, pos, target, enemy, attackSelections, ahead, overdriveCopy, combineCards)];
  }

  /* Stand-in "enemy" so attack previews can point at the boss or a craft. */
  function coopTargetStub(target, pos) {
    const sb = view.star_breach;
    if (!sb || !target || !target.startsWith) return null;
    if (target.startsWith("craft:")) {
      const craft = (sb.fleet || []).find((candidate) => candidate.id === target.split(":")[1]);
      if (!craft || craft.destroyed) return null;
      return { ship: { q: craft.q, r: craft.r, defense_bonus_this_action: 0, shields: 0 } };
    }
    if (target.startsWith("boss:")) {
      // Distance always counts to the boss's nearest board hex.
      let best = null, bestDistance = Infinity;
      for (const cell of sb.board_hexes || []) {
        const distance = Board.hexDistance(pos.q, pos.r, cell.q, cell.r);
        if (distance < bestDistance) { bestDistance = distance; best = cell; }
      }
      if (!best) return null;
      return { ship: { q: best.q, r: best.r, defense_bonus_this_action: 0, shields: 0 } };
    }
    return null;
  }

  function attackProjection(slotIndex, pos, targetId, enemy, attackSelections, ahead, overdriveCopy, combineCards) {
    const me = myPlayer();
    let aim = 0, damageBonus = 0, baseDamage = 1;
    let always = false, lead = false, maxRange = null, fixedDefense = null;
    for (const selection of attackSelections) {
      if (selection.face === "desperate") {
        const face = selection.card.desperate_face || {};
        aim += face.aim_bonus || 0;
        damageBonus += face.damage_bonus || 0;
        baseDamage = Math.max(baseDamage, face.base_damage || face.value || 1);
        always = always || face.always_hits || (face.aim_bonus || 0) >= 99;
        lead = lead || !!face.lead_the_target;
        if (face.max_range != null && maxRange == null) maxRange = face.max_range;
        if (face.fixed_defense_threshold != null && fixedDefense == null) fixedDefense = face.fixed_defense_threshold;
      } else {
        const aimMatch = /aim \+?(\d+)/i.exec(selection.card.name || "");
        const damageMatch = /damage \+?(\d+)/i.exec(selection.card.name || "");
        if (aimMatch) aim += parseInt(aimMatch[1], 10);
        if (damageMatch || selection.card.is_hybrid) damageBonus += damageMatch ? parseInt(damageMatch[1], 10) : 1;
      }
    }
    if (combineCards) {
      aim *= 2;
      damageBonus *= 2;
    }
    if (captainId(me) === "malcolm_manderly") aim += 2;
    const distance = Board.hexDistance(pos.q, pos.r, enemy.ship.q, enemy.ship.r);
    const targetMove = 0;
    const targetDefense = enemy.ship.defense_bonus_this_action || 0;
    const defense = fixedDefense ?? (distance + targetMove + targetDefense);
    const needed = defense - aim;
    const attackDice = activeStarfall("clear_skies") ? 3 : 2;
    const inRange = maxRange == null || distance <= maxRange;
    const naturalAutoHitChance = 1 / (6 ** attackDice);
    const hitChance = inRange ? (always ? 1 : Math.max(naturalAutoHitChance, pDiceAtLeast(attackDice, needed))) : 0;
    const labelBase = `A${["I", "II", "III"][slotIndex]}${ahead ? " ⇢" : ""}${overdriveCopy ? " OD" : ""}`;
    return {
      aim,
      always,
      attackDice,
      baseDamage,
      damage: baseDamage + damageBonus,
      defense,
      distance,
      fixedDefense,
      from: { q: pos.q, r: pos.r },
      hitChance,
      inRange,
      label: labelBase,
      lead,
      maxRange,
      needed,
      target: targetId,
      targetDefense,
      targetMove,
      targetMoveHidden: !lead,
      to: { q: enemy.ship.q, r: enemy.ship.r },
      overdriveCopy,
    };
  }

  function projectionSummary(projection) {
    if (projection.noTarget) return projection.summary;
    const roll = !projection.inRange
      ? `out of range ${projection.distance}/${projection.maxRange}`
      : projection.always
        ? "always hits"
        : projection.needed > projection.attackDice * 6
          ? `natural ${projection.attackDice * 6} (${Math.round(projection.hitChance * 100)}%)`
          : `${Math.max(projection.attackDice, projection.needed)}+ (${Math.round(projection.hitChance * 100)}%)`;
    const parts = [
      `${displayName(projection.target)}: ${roll}`,
      `${projection.damage} dmg`,
      `+${projection.aim} Aim`,
      `Defense ${projection.defense}`,
    ];
    if (projection.targetMove) parts.push(`${projection.targetMove} move`);
    if (projection.targetDefense) parts.push(`+${projection.targetDefense} defense`);
    if (projection.lead) parts.push("ignores movement");
    if (projection.fixedDefense != null) parts.push("fixed defense");
    return parts.join(" · ");
  }

  function computePreview() {
    if (!view || view.phase !== "give_orders") { Board.clearPreview(); return; }
    const me = myPlayer();
    if (!me || me.has_submitted_orders || !me.ship || me.ship.destroyed) { Board.clearPreview(); return; }
    let pos = { q: me.ship.q, r: me.ship.r, facing: me.ship.facing };
    const items = [];
    const color = Board.colorOf(you);
    const numerals = ["I", "II", "III"];
    draft.slots.forEach((slot, index) => {
      const overdriven = slot.seal === "overdrive";
      const actionCopy = overdriven && overdriveCopiesAction();
      const cardCopy = overdriven && overdriveCopiesCards();
      const moveSelections = slot.cards.filter((s) => s.family === "move");
      const attackSelections = slot.cards.filter((s) => s.family === "attack");
      if (moveSelections.length) {
        const points = [{ q: pos.q, r: pos.r }];
        const passes = actionCopy || cardCopy ? 2 : 1;
        for (let pass = 0; pass < passes; pass++) {
          for (const selection of moveSelections) {
            if (
              pass > 0
              && actionCopy
              && selection.face === "desperate"
              && !view.rules_config?.allow_overdrive_desperation
            ) continue;
            const result = simMove(pos, selection);
            pos = result.pos;
            points.push({ q: pos.q, r: pos.r });
          }
        }
        items.push({ kind: "path", points, color });
        items.push({
          kind: "ghost", q: pos.q, r: pos.r, facing: pos.facing,
          label: "A" + numerals[index] + (overdriven ? " 🔥" : ""), color,
        });
      }
      if (attackSelections.length) {
        for (const projection of attackProjectionsForSlot(index, pos)) {
          items.push({
            kind: "shot",
            from: projection.from,
            to: projection.to,
            label: projection.noTarget
              ? `A${numerals[index]} ⇢ no ship ahead!`
              : `${projection.label} · ${Math.round(projection.hitChance * 100)}% · ${projection.damage} dmg`,
            title: projectionSummary(projection),
          });
        }
      }
    });
    Board.renderPreview(items);
  }

  // ── replay animation ──────────────────────────────────────────────────
  let skipReplay = false;
  let replaySpeed = 1;
  const wait = (ms) => (skipReplay
    ? Promise.resolve()
    : new Promise((resolve) => setTimeout(resolve, ms / replaySpeed)));

  function replayControls(show) {
    let node = document.getElementById("replay-controls");
    if (show && !node) {
      node = document.createElement("div");
      node.id = "replay-controls";
      node.className = "replay-controls";
      node.innerHTML = `
        <span class="rc-label">⏱ Replay</span>
        <input id="replay-speed" type="range" min="0.5" max="4" step="0.5" value="${replaySpeed}">
        <span id="replay-speed-label">${replaySpeed}×</span>
        <button class="btn gold small" id="replay-skip-end">⏭ Skip to end</button>`;
      els["board-wrap"].appendChild(node);
      node.querySelector("#replay-speed").addEventListener("input", (event) => {
        replaySpeed = parseFloat(event.target.value) || 1;
        node.querySelector("#replay-speed-label").textContent = replaySpeed + "×";
      });
      node.querySelector("#replay-skip-end").addEventListener("click", () => {
        skipReplay = true;
        node.remove();
      });
    } else if (!show && node) {
      node.remove();
    }
  }

  function callout(text, crimson) {
    const node = els["board-callout"];
    node.textContent = text;
    node.className = "board-callout" + (crimson ? " crimson" : "");
    node.classList.remove("hidden");
    clearTimeout(callout._timer);
    callout._timer = setTimeout(() => node.classList.add("hidden"), 1400);
  }

  /* Rich boss-phase banner: total actions, where each charge came from, and
     the current progress track. */
  async function showBossPhaseCallout(event) {
    const sb = view.star_breach || {};
    const names = {};
    for (const component of (sb.boss_layout || {}).components || []) {
      // Numbered names ("Cannon 2") show whole; stock ones keep the last word.
      const words = component.name.split(" ");
      names[component.id] = words.length > 2 ? words[words.length - 1] : component.name;
    }
    const sources = (event.slots || []).map((slot) => {
      if (slot.slot === "base") return "Base";
      if (slot.slot === "tier") return `Tier ${slot.tier}`;
      return names[slot.component_id] || slot.component_id;
    });
    const maxTrack = progressMax(sb);
    const label = event.boss_phase === "starbreach" ? "STARBREACH" : `Action ${event.boss_phase}`;
    document.getElementById("boss-phase-callout")?.remove();
    const node = document.createElement("div");
    node.id = "boss-phase-callout";
    node.className = "boss-callout";
    node.innerHTML = `
      <b>☄ Boss ${esc(label)} — ${event.total_actions} ${esc(event.kind)}${event.total_actions === 1 ? "" : "s"}</b>
      <div class="bc-sources">${sources.map((source) => `<span class="bc-source">${esc(source)}</span>`).join("")}</div>
      <div class="bc-bar"><div class="bc-bar-fill" style="width:${Math.min(100, ((event.progress || 0) / maxTrack) * 100)}%"></div></div>`;
    els["board-wrap"].appendChild(node);
    await wait(1500);
    node.remove();
  }

  /* "Pause after each player action": wait for the captain to click on. */
  function continueGate() {
    return new Promise((resolve) => {
      const button = document.createElement("button");
      button.className = "btn gold sb-continue";
      button.textContent = "▶ Continue";
      button.addEventListener("click", () => { button.remove(); resolve(); });
      els["board-wrap"].appendChild(button);
      const poll = setInterval(() => {
        if (skipReplay) { clearInterval(poll); button.remove(); resolve(); }
      }, 200);
      button.addEventListener("click", () => clearInterval(poll));
    });
  }

  function bossRenderOptions() {
    return {
      pose: replayBossPose || undefined,
      preyPos: preyPosition(),
      fleetPose: replayFleetPose || undefined,
    };
  }

  /* Rewind fleet craft to where they stood when this batch of events began,
     using the first recorded position per craft (move `before`, boss-push
     `from`, or a recorded attack position). Craft destroyed during the batch
     start alive so the replay can sink them at the recorded moment. */
  function buildReplayFleetPose(events) {
    const sb = view.star_breach;
    if (!sb || !(sb.fleet || []).length) return null;
    const destroyedDuring = new Set();
    const spawnedDuring = new Set();
    for (const event of events) {
      if (event.type === "craft_volley_resolved" && event.craft_destroyed) {
        destroyedDuring.add(String(event.target_id || "").replace("craft:", ""));
      }
      if (event.type === "boss_fleet_spawned") {
        for (const craft of event.craft || []) spawnedDuring.add(craft.id);
      }
    }
    const pose = {};
    for (const craft of sb.fleet) {
      // Craft spawned during this batch stay hidden until the spawn plays.
      pose[craft.id] = {
        q: craft.q,
        r: craft.r,
        destroyed: spawnedDuring.has(craft.id) || (craft.destroyed && !destroyedDuring.has(craft.id)),
      };
    }
    const seen = new Set();
    const seed = (id, q, r) => {
      if (!id || seen.has(id) || !(id in pose) || q === undefined || r === undefined) return;
      seen.add(id);
      pose[id].q = q;
      pose[id].r = r;
    };
    for (const event of events) {
      if (event.type === "boss_phase_resolved") {
        for (const entry of event.fleet || []) {
          if (entry.before) seed(entry.craft_id, entry.before[0], entry.before[1]);
          else if (entry.attacker_position) seed(entry.craft_id, entry.attacker_position.q, entry.attacker_position.r);
        }
      } else if (event.type === "craft_volley_resolved" && event.target_position) {
        seed(String(event.target_id || "").replace("craft:", ""), event.target_position.q, event.target_position.r);
      }
    }
    return pose;
  }

  /* Rewind the boss battle-board state (progress, tiers, hull damage, shields)
     to the moment this batch of events began; playEvent rolls it forward so
     the progression board mirrors the replay instead of the final state. */
  function buildReplayBossState(events) {
    const sb = view.star_breach;
    if (!sb) return null;
    const state = {
      progress: sb.progress || 0,
      active_tiers: [...(sb.active_tiers || [])],
      destroyed_hexes: (sb.destroyed_hexes || []).map((hex) => [...hex]),
      destroyed_component_ids: [...(sb.destroyed_component_ids || [])],
      shield_hp: { ...(sb.shield_hp || {}) },
      phaseCursor: null,
      phaseResolving: null,
    };
    for (const event of events) {
      if (event.type === "boss_progress_advanced") {
        state.progress = Math.max(0, Math.min(state.progress, (event.progress || 0) - (event.amount || 0)));
      } else if (event.type === "boss_tiers_activated") {
        state.active_tiers = state.active_tiers.filter((tier) => !(event.tiers || []).includes(tier));
      } else if (event.type === "boss_volley_resolved" && event.hit) {
        const area = String(event.target_id || "").replace("boss:", "");
        if (event.shields_absorbed) {
          const max = sb.shield_max?.[area];
          state.shield_hp[area] = (state.shield_hp[area] || 0) + event.shields_absorbed;
          if (max != null) state.shield_hp[area] = Math.min(max, state.shield_hp[area]);
        }
        for (const shot of event.shots || []) {
          if (shot.result !== "hull_destroyed") continue;
          if (shot.hex) {
            state.destroyed_hexes = state.destroyed_hexes.filter(([q, r]) => !(q === shot.hex[0] && r === shot.hex[1]));
          }
          if (shot.component_id) {
            state.destroyed_component_ids = state.destroyed_component_ids.filter((id) => id !== shot.component_id);
          }
        }
      }
    }
    return state;
  }

  /* Roll the boss board forward as a boss volley lands during the replay. */
  function applyReplayBossVolley(event) {
    if (!replayBossState || !event.hit) return;
    const area = String(event.target_id || "").replace("boss:", "");
    if (event.shields_absorbed) {
      replayBossState.shield_hp[area] = Math.max(0, (replayBossState.shield_hp[area] || 0) - event.shields_absorbed);
    }
    for (const shot of event.shots || []) {
      if (shot.result !== "hull_destroyed") continue;
      if (shot.hex) replayBossState.destroyed_hexes.push([shot.hex[0], shot.hex[1]]);
      if (shot.component_id && !replayBossState.destroyed_component_ids.includes(shot.component_id)) {
        replayBossState.destroyed_component_ids.push(shot.component_id);
      }
    }
    refreshBossWidgets();
  }

  function refreshBossWidgets() {
    if (view.star_breach) renderBossBattleBoardMini();
  }

  /* Your revealed order stacks per round, rebuilt from the event log so the
     panel can keep showing them (and highlight them) while they play out. */
  function buildReplayOrdersByRound(events) {
    const byRound = {};
    for (const event of events) {
      if (event.type !== "action_revealed" || event.player_id !== you) continue;
      const round = event.round || view.round_number;
      if (!byRound[round]) byRound[round] = { round, active: null, slots: [null, null, null] };
      byRound[round].slots[(event.action_number || 1) - 1] = {
        seal: event.seal_mode === "overdrive" ? "overdrive" : "sealed",
        cards: event.cards || [],
      };
    }
    return byRound;
  }

  async function playEvents(events) {
    animating = true;
    skipReplay = false;
    replayShipStates = buildReplayShipStates(events);
    replayBossPose = buildReplayBossPose(events);
    replayFleetPose = buildReplayFleetPose(events);
    replayBossState = buildReplayBossState(events);
    replayOrdersByRound = buildReplayOrdersByRound(events);
    const orderRounds = Object.keys(replayOrdersByRound).map(Number).sort((a, b) => a - b);
    replayOrders = orderRounds.length ? replayOrdersByRound[orderRounds[0]] : null;
    refreshBossWidgets();
    renderOrdersPanel();
    replayControls(events.length >= 4);
    try {
      // Every ship sails alive at the start of the tale; the replay itself
      // sinks (or strikes) them at the recorded moment. Also rewind movers to
      // their positions before the first recorded move.
      const destroyedDuring = new Set();
      for (const event of events) {
        if (event.type === "volley_resolved" && event.target_destroyed) destroyedDuring.add(event.target_id);
      }
      for (const playerId of seatOrder()) {
        const player = view.players[playerId];
        if (!player) continue;
        const finallyDead = player.ship.destroyed || player.eliminated;
        // Alive during the replay if this replay covers their demise, or they survive.
        Board.setShipDead(playerId, finallyDead && !destroyedDuring.has(playerId)
          && !events.some((e) => e.type === "player_forfeited" && e.player_id === playerId));
      }
      // Rewind each player ship to its first recorded move in this batch.
      const positions = {};
      for (const event of events) {
        if (event.type === "movement_resolved" && event.steps && event.steps.length && !(event.player_id in positions)) {
          positions[event.player_id] = { ...event.steps[0].before };
        }
      }
      for (const playerId of Object.keys(positions)) {
        const start = positions[playerId];
        Board.placeShip(playerId, start.q, start.r, start.facing);
      }
      if (view.star_breach) {
        Board.renderStarBreach(effectiveStarBreach(), bossRenderOptions());
      }
      renderFleet();
      for (let index = 0; index < events.length; index++) {
        const event = events[index];
        // StarBreach: let the crew study the board after each player action.
        if (
          view.star_breach
          && event.type === "phase_changed"
          && ["action_2", "action_3", "award_baubles"].includes(event.phase)
          && pauseAfterActions()
          && !skipReplay
        ) {
          await continueGate();
        }
        if (event.type === "movement_resolved") {
          const movementEvents = [event];
          while (
            index + 1 < events.length
            && events[index + 1].type === "movement_resolved"
            && events[index + 1].action_number === event.action_number
          ) {
            movementEvents.push(events[index + 1]);
            index += 1;
          }
          await playMovementEvents(movementEvents);
        } else {
          await playEvent(event);
        }
      }
    } finally {
      animating = false;
      skipReplay = false;
      replayShipStates = null;
      replayBossPose = null;
      replayFleetPose = null;
      replayBossState = null;
      replayOrders = null;
      replayOrdersByRound = null;
      replayControls(false);
    }
  }

  function buildReplayBossPose(events) {
    if (!view.star_breach) return null;
    for (const event of events) {
      if (event.type !== "boss_phase_resolved") continue;
      for (const slot of event.slots || []) {
        const move = slot.movement;
        if (move && move.moved && move.before) {
          return { q: move.before.anchor_q, r: move.before.anchor_r, facing: move.before.facing };
        }
      }
    }
    return { q: view.star_breach.anchor_q, r: view.star_breach.anchor_r, facing: view.star_breach.facing || 0 };
  }

  function displayShipFor(playerId) {
    return (replayShipStates && replayShipStates[playerId]) || view.players[playerId]?.ship || {};
  }

  function buildReplayShipStates(events) {
    const ships = {};
    for (const playerId of seatOrder()) {
      const ship = view.players[playerId]?.ship;
      if (ship) ships[playerId] = JSON.parse(JSON.stringify(ship));
    }
    for (let index = events.length - 1; index >= 0; index--) {
      reverseShipEvent(ships, events[index]);
    }
    return ships;
  }

  function reverseShipEvent(ships, event) {
    if (event.type === "volley_resolved" || event.type === "enemy_volley_resolved") {
      const ship = ships[event.target_id];
      if (!ship) return;
      if (event.shielded) ship.shields = (ship.shields || 0) + 1;
      reverseDamageResult(ship, event);
      if (event.target_destroyed) {
        ship.destroyed = false;
        ship.knocked_out_round = null;
        ship.knocked_out_action_number = null;
        ship.knocked_out_phase = null;
      }
    } else if (event.type === "repair_volley_resolved" && event.hit) {
      const ship = ships[event.target_id];
      if (!ship) return;
      if (event.restored_component_id) {
        const destroyed = new Set(ship.destroyed_components || []);
        destroyed.add(event.restored_component_id);
        ship.destroyed_components = Array.from(destroyed);
        ship.damage_taken = (ship.damage_taken || 0) + 1;
      } else if (event.shield_restored) {
        ship.shields = Math.max(0, (ship.shields || 0) - 1);
      }
    } else if (event.type === "ramming_resolved") {
      reverseDamageResult(ships[event.target_id], event.target_damage || {});
      reverseDamageResult(ships[event.attacker_id], event.attacker_damage || {});
    } else if (event.type === "starfall_take_cover_damage" || event.type === "starfall_revealed") {
      for (const result of event.targets || []) {
        const ship = ships[result.player_id];
        if (!ship) continue;
        if (result.shield_hits) ship.shields = (ship.shields || 0) + result.shield_hits;
        reverseDamageResult(ship, result);
        if (result.target_destroyed) ship.destroyed = false;
      }
    }
  }

  function reverseDamageResult(ship, result) {
    if (!ship || !result) return;
    const destroyed = new Set(ship.destroyed_components || []);
    let restored = 0;
    for (const shot of result.damage_shots || []) {
      if (!shot.destroyed) continue;
      if (shot.component_id && destroyed.delete(shot.component_id)) restored++;
      for (const detachedId of shot.detached_component_ids || []) {
        if (destroyed.delete(detachedId)) restored++;
      }
    }
    ship.destroyed_components = Array.from(destroyed);
    ship.damage_taken = Math.max(0, (ship.damage_taken || 0) - restored);
  }

  function applyShipEvent(event) {
    if (!replayShipStates) return;
    if (event.type === "volley_resolved" && event.shielded) {
      const ship = replayShipStates[event.target_id];
      if (ship) ship.shields = Math.max(0, (ship.shields || 0) - 1);
    } else if (event.type === "starfall_take_cover_damage" || event.type === "starfall_revealed") {
      for (const result of event.targets || []) applyDamageResult(result.player_id, result);
    } else if (event.type === "ramming_resolved") {
      applyDamageResult(event.target_id, event.target_damage || {});
      applyDamageResult(event.attacker_id, event.attacker_damage || {});
    }
    renderFleet();
  }

  function applyDamageResult(playerId, result) {
    const ship = replayShipStates && replayShipStates[playerId];
    if (!ship || !result) return;
    if (result.shield_hits) ship.shields = Math.max(0, (ship.shields || 0) - result.shield_hits);
    for (const shot of result.damage_shots || []) applyDamageShot(playerId, shot);
    if (result.target_destroyed) ship.destroyed = true;
  }

  function applyDamageShot(playerId, shot) {
    const ship = replayShipStates && replayShipStates[playerId];
    if (!ship || !shot || !shot.destroyed) return;
    const destroyed = new Set(ship.destroyed_components || []);
    if (shot.component_id) destroyed.add(shot.component_id);
    for (const detachedId of shot.detached_component_ids || []) destroyed.add(detachedId);
    ship.destroyed_components = Array.from(destroyed);
    ship.damage_taken = destroyed.size;
  }

  async function playMovementEvents(events) {
    const pathsByPlayer = new Map();
    for (const event of events) {
      if (!pathsByPlayer.has(event.player_id)) pathsByPlayer.set(event.player_id, []);
      pathsByPlayer.get(event.player_id).push(...(event.steps || []));
    }

    await Promise.all(Array.from(pathsByPlayer.entries()).map(async ([playerId, steps]) => {
      for (const step of steps) {
        const from = step.before, to = step.after;
        const frames = 9;
        for (let frame = 1; frame <= frames; frame++) {
          const q = from.q + (to.q - from.q) * (frame / frames);
          const r = from.r + (to.r - from.r) * (frame / frames);
          Board.placeShip(playerId, q, r, to.facing);
          FX.trail(Board.hexToScreen(q, r), Board.colorOf(playerId));
          await wait(26);
        }
        if (step.warp_destination) FX.warp(Board.hexToScreen(to.q, to.r));
      }
    }));
    await wait(120);
  }

  function playStarfallFx(event) {
    const center = Board.hexToScreen(0, 0);
    const animation = event.animation || "";
    if (animation === "storm") {
      FX.explosion(center);
      for (const target of event.targets || []) {
        const player = view.players[target.player_id];
        if (player) FX.impact(Board.hexToScreen(player.ship.q, player.ship.r), true);
      }
    } else if (animation === "gravity") {
      FX.warp(center);
      FX.floatText(center, "GRAVITY BURST", "#9ee7ff", 18);
    } else if (animation === "harbor") {
      FX.shield(center);
      FX.floatText(center, "SAFE HARBOR", "#7ed8ff", 18);
    } else if (animation === "gold") {
      FX.loot(center);
    } else if (animation === "wind") {
      FX.floatText(center, "GUSTY WINDS", "#cfe8ff", 18);
      FX.warp(center);
    } else {
      FX.floatText(center, String(event.starfall || "STARFALL").toUpperCase(), "#ffd76a", 18);
      FX.warp(center);
    }
  }

  async function playEvent(event) {
    switch (event.type) {
      case "phase_changed":
        if (event.phase === "action_1") callout("⚔ Battle Stations!");
        else if (event.phase === "action_2") callout("Action II");
        else if (event.phase === "action_3") callout("Action III");
        else if (event.phase === "award_baubles") {
          callout("✦ Claim the Loot");
          if (replayOrders && replayOrders.active !== null) {
            replayOrders.active = null;
            renderOrdersPanel();
          }
        }
        return;
      case "round_advanced":
        callout(`Round ${event.round}`);
        if (replayOrdersByRound) {
          replayOrders = replayOrdersByRound[event.round] || null;
          if (replayOrders) replayOrders.active = null;
        }
        if (replayBossState) {
          replayBossState.phaseCursor = null;
          replayBossState.phaseResolving = null;
        }
        if (event.round === view.round_number) {
          // The replay has caught up to the live round: stop leaning on
          // interpolated/replay positions and snap the board straight to
          // the server's truth, so nothing looks stale once give-orders
          // opens (even before this replay call finishes winding down).
          Board.renderShips(view.players, seatOrder(), you);
        }
        renderOrdersPanel();
        refreshBossWidgets();
        await wait(700);
        return;
      case "action_revealed":
        if (event.player_id === you && replayOrdersByRound) {
          replayOrders = replayOrdersByRound[event.round] || replayOrders;
          if (replayOrders) {
            replayOrders.active = (event.action_number || 1) - 1;
            renderOrdersPanel();
          }
        }
        if (event.seal_mode === "overdrive") {
          callout(`🔥 ${Board.shortName(event.player_id)} OVERDRIVES!`, true);
          await wait(500);
        }
        return;
      case "movement_resolved": {
        await playMovementEvents([event]);
        return;
      }
      case "captain_cleanup_movement": {
        await playMovementEvents((event.movements || []).map((movement) => ({
          player_id: movement.player_id,
          steps: [{ before: movement.before, after: movement.after, distance: 2 }],
        })));
        return;
      }
      case "starfall_revealed": {
        callout(`Starfall: ${event.starfall}`, true);
        playStarfallFx(event);
        applyShipEvent(event);
        await wait(1200);
        return;
      }
      case "boss_phase_started": {
        if (replayBossState) {
          replayBossState.phaseResolving = event.boss_phase;
          refreshBossWidgets();
        }
        await showBossPhaseCallout(event);
        return;
      }
      case "boss_phase_resolved": {
        if (replayBossState) {
          replayBossState.phaseCursor = event.boss_phase;
          replayBossState.phaseResolving = null;
          refreshBossWidgets();
        }
        // Designed bosses can mix moves and attacks in one stack, so always
        // animate whatever movement the slots and fleet actually recorded.
        for (const slot of event.slots || []) {
          const move = slot.movement;
          if (!move || !move.moved) continue;
          const from = move.before;
          const to = move.after;
          const frames = 10;
          for (let frame = 1; frame <= frames; frame++) {
            const t = frame / frames;
            replayBossPose = {
              q: from.anchor_q + (to.anchor_q - from.anchor_q) * t,
              r: from.anchor_r + (to.anchor_r - from.anchor_r) * t,
              facing: to.facing,
            };
            Board.renderStarBreach(effectiveStarBreach(), bossRenderOptions());
            FX.trail(Board.hexToScreen(replayBossPose.q, replayBossPose.r), "#a86ad1");
            await wait(28);
          }
          replayBossPose = { q: to.anchor_q, r: to.anchor_r, facing: to.facing };
          await wait(90);
        }
        for (const entry of event.fleet || []) {
          const pose = replayFleetPose && replayFleetPose[entry.craft_id];
          if (!pose || !entry.before || !entry.after) continue;
          if (!entry.moved) {
            pose.q = entry.after[0];
            pose.r = entry.after[1];
            continue;
          }
          const frames = 7;
          for (let frame = 1; frame <= frames; frame++) {
            const t = frame / frames;
            pose.q = entry.before[0] + (entry.after[0] - entry.before[0]) * t;
            pose.r = entry.before[1] + (entry.after[1] - entry.before[1]) * t;
            Board.renderStarBreach(effectiveStarBreach(), bossRenderOptions());
            await wait(26);
          }
        }
        Board.renderStarBreach(effectiveStarBreach(), bossRenderOptions());
        return;
      }
      case "enemy_volley_resolved": {
        const from = Board.hexToScreen(event.attacker_position?.q ?? 0, event.attacker_position?.r ?? 0);
        const targetShip = displayShipFor(event.target_id);
        const to = Board.hexToScreen(event.target_position?.q ?? targetShip.q, event.target_position?.r ?? targetShip.r);
        FX.laser(from, to, "#a86ad1");
        await wait(240);
        const rollText = `🎲 ${event.roll}${event.aim_bonus ? "+" + event.aim_bonus : ""} vs ${event.defense_threshold}`;
        if (event.shielded) {
          FX.shield(to);
          const ship = replayShipStates && replayShipStates[event.target_id];
          if (ship) ship.shields = Math.max(0, (ship.shields || 0) - 1);
          FX.floatText(to, rollText + " — SHIELDED", "#7ed8ff");
        } else if (event.hit) {
          FX.impact(to, false);
          applyDamageResult(event.target_id, event);
          FX.floatText(to, rollText + " — HIT", "#ff8d7a");
        } else {
          FX.floatText(to, rollText + " — miss", "#8fa3bd");
        }
        renderFleet();
        await wait(430);
        return;
      }
      case "boss_volley_resolved": {
        const from = Board.hexToScreen(event.attacker_position?.q ?? 0, event.attacker_position?.r ?? 0);
        const to = Board.hexToScreen(event.target_position?.q ?? 0, event.target_position?.r ?? 0);
        FX.laser(from, to, Board.colorOf(event.attacker_id));
        await wait(240);
        if (!event.hit) {
          FX.floatText(to, `🎲 ${event.roll} vs ${event.defense_threshold} — miss`, "#8fa3bd");
        } else {
          FX.impact(to, (event.hexes_destroyed || 0) > 0);
          const bits = [];
          if (event.shields_absorbed) bits.push("SHIELD -" + event.shields_absorbed);
          if (event.hexes_destroyed) bits.push("HULL -" + event.hexes_destroyed);
          if ((event.components_destroyed || []).length) bits.push(event.components_destroyed.join(", ").toUpperCase() + " DESTROYED");
          if (event.desperation_cards_drawn) bits.push("glancing blow: desperate card to deck");
          FX.floatText(to, bits.join(" · ") || "no effect", "#d9a6ff");
          applyReplayBossVolley(event);
          Board.renderStarBreach(effectiveStarBreach(), bossRenderOptions());
        }
        await wait(430);
        return;
      }
      case "craft_volley_resolved": {
        const from = Board.hexToScreen(event.attacker_position?.q ?? 0, event.attacker_position?.r ?? 0);
        const to = Board.hexToScreen(event.target_position?.q ?? 0, event.target_position?.r ?? 0);
        FX.laser(from, to, Board.colorOf(event.attacker_id));
        await wait(240);
        if (event.hit) {
          FX.impact(to, event.craft_destroyed);
          FX.floatText(to, event.craft_destroyed ? "HUNTER DESTROYED ☠" : `HIT — ${event.craft_hp_left} HP left`, "#ffb27a");
          if (event.craft_destroyed && replayFleetPose) {
            const craftId = String(event.target_id || "").replace("craft:", "");
            if (replayFleetPose[craftId]) {
              replayFleetPose[craftId].destroyed = true;
              Board.renderStarBreach(effectiveStarBreach(), bossRenderOptions());
            }
          }
        } else {
          FX.floatText(to, `🎲 ${event.roll} vs ${event.defense_threshold} — miss`, "#8fa3bd");
        }
        await wait(430);
        return;
      }
      case "repair_volley_resolved": {
        const from = Board.hexToScreen(event.attacker_position?.q ?? 0, event.attacker_position?.r ?? 0);
        const to = Board.hexToScreen(event.target_position?.q ?? 0, event.target_position?.r ?? 0);
        FX.laser(from, to, "#3ea86b");
        await wait(240);
        const outcome = event.hit
          ? (event.restored_component_id ? "REPAIRED " + event.restored_component_id.replace(/_/g, " ").toUpperCase()
            : event.shield_restored ? "SHIELD RESTORED" : "nothing to fix")
          : "repair fumbled";
        FX.floatText(to, "🔧 " + outcome, "#8fe3a5");
        if (event.hit && event.restored_component_id && replayShipStates && replayShipStates[event.target_id]) {
          const ship = replayShipStates[event.target_id];
          ship.destroyed_components = (ship.destroyed_components || []).filter((id) => id !== event.restored_component_id);
          renderFleet();
        }
        await wait(430);
        return;
      }
      case "boss_progress_advanced": {
        if (replayBossState) {
          replayBossState.progress = event.progress ?? replayBossState.progress;
          refreshBossWidgets();
        }
        return;
      }
      case "boss_tiers_activated": {
        if (replayBossState) {
          for (const tier of event.tiers || []) {
            if (!replayBossState.active_tiers.includes(tier)) replayBossState.active_tiers.push(tier);
          }
          refreshBossWidgets();
        }
        callout(`☄ Boss Tier ${event.tiers.join(", ")} online!`, true);
        await wait(700);
        return;
      }
      case "boss_fleet_spawned": {
        callout(`☄ Reinforcements warp in!`, true);
        for (const craft of event.craft || []) {
          if (replayFleetPose && replayFleetPose[craft.id]) {
            replayFleetPose[craft.id] = { q: craft.q, r: craft.r, destroyed: false };
          }
          FX.warp(Board.hexToScreen(craft.q, craft.r));
        }
        Board.renderStarBreach(effectiveStarBreach(), bossRenderOptions());
        await wait(800);
        return;
      }
      case "starfall_take_cover_damage": {
        callout("Take Cover!", true);
        for (const target of event.targets || []) {
          const player = view.players[target.player_id];
          if (!player) continue;
          const at = Board.hexToScreen(player.ship.q, player.ship.r);
          FX.impact(at, true);
        }
        applyShipEvent(event);
        await wait(700);
        return;
      }
      case "volley_resolved": {
        const from = Board.hexToScreen(event.attacker_position.q, event.attacker_position.r);
        const to = Board.hexToScreen(event.target_position.q, event.target_position.r);
        FX.laser(from, to, Board.colorOf(event.attacker_id));
        await wait(300);
        const rollText = `🎲 ${event.roll}${event.aim_bonus ? "+" + event.aim_bonus : ""} vs ${event.defense_threshold}`;
        if (event.shielded) {
          FX.shield(to);
          applyShipEvent(event);
          FX.floatText(to, rollText + " — SHIELDED", "#7ed8ff");
        } else if (event.hit) {
          FX.impact(to, (event.damage_applied || 0) > 1);
          FX.floatText(to, rollText + ` — HIT ${event.damage_applied ? "(" + event.damage_applied + " dmg)" : ""}`, "#ffb27a");
          // Name what the d12 lane rolls tore off the ship.
          const layout = {};
          for (const component of (view.players[event.target_id]?.ship?.component_layout) || []) {
            layout[component.id] = component.name;
          }
          for (const shot of event.damage_shots || []) {
            if (!shot.destroyed) continue;
            await wait(340);
            applyDamageShot(event.target_id, shot);
            renderFleet();
            FX.floatText(to, `⚀${shot.lane} → ${layout[shot.component_id] || shot.component_id} destroyed!`, "#ff8d7a", 12);
            for (const detachedId of shot.detached_component_ids || []) {
              await wait(280);
              FX.floatText(to, `${layout[detachedId] || detachedId} torn away!`, "#ffab8a", 11);
            }
          }
        } else {
          FX.miss(to);
          FX.floatText(to, rollText, "#9fb2d8");
        }
        if (event.target_destroyed) {
          await wait(350);
          if (replayShipStates && replayShipStates[event.target_id]) {
            replayShipStates[event.target_id].destroyed = true;
            renderFleet();
          }
          FX.explosion(to);
          Board.setShipDead(event.target_id, true);
          callout(`☠ ${Board.shortName(event.target_id)} IS SUNK!`, true);
          await wait(600);
        }
        await wait(420);
        return;
      }
      case "bauble_awarded": {
        const bauble = event.bauble || {};
        const at = Board.hexToScreen(bauble.q || 0, bauble.r || 0);
        FX.loot(at);
        for (const award of event.awards || []) {
          FX.floatText(at, `${Board.shortName(award.player_id)} +${award.vp_awarded} VP`, "#ffd76a", 15);
          await wait(420);
        }
        return;
      }
      case "desperation_consequence": {
        const ship = displayShipFor(event.player_id);
        if (ship) {
          const at = Board.hexToScreen(ship.q, ship.r);
          FX.floatText(at, "☄ DESPERATE", "#c9a3f0");
        }
        return;
      }
      case "player_forfeited":
        callout(`🏳 ${Board.shortName(event.player_id)} abandons the battle!`, true);
        Board.setShipDead(event.player_id, true);
        await wait(900);
        return;
      default:
        return;
    }
  }

  // ── endgame ───────────────────────────────────────────────────────────
  function battleStats() {
    const stats = {};
    for (const playerId of seatOrder()) {
      stats[playerId] = {
        shots: 0, hits: 0, loot: 0, baubleVp: 0, attackVp: 0,
        damageDealt: 0, kills: [], killedBy: null, shieldBlocks: 0,
      };
    }
    for (const event of view.event_log || []) {
      if (event.type === "volley_resolved" && stats[event.attacker_id]) {
        const attacker = stats[event.attacker_id];
        attacker.shots++;
        if (event.hit) attacker.hits++;
        attacker.attackVp += event.vp_awarded || 0;
        attacker.damageDealt += event.damage_applied || 0;
        if (event.shielded && stats[event.target_id]) stats[event.target_id].shieldBlocks++;
        if (event.target_destroyed) {
          attacker.kills.push(event.target_id);
          if (stats[event.target_id]) stats[event.target_id].killedBy = event.attacker_id;
        }
      }
      if (event.type === "bauble_awarded") {
        for (const award of event.awards || []) {
          if (!stats[award.player_id]) continue;
          stats[award.player_id].loot++;
          stats[award.player_id].baubleVp += award.vp_awarded || 0;
        }
      }
    }
    return stats;
  }

  const RESULT_REASONS = {
    last_ship_standing: "Last ship still flying",
    all_ships_destroyed: "Every ship destroyed — mutual annihilation",
    round_six_victory_points: "Most plunder after six rounds",
    star_breach_victory: "The Prey reached The Fang — the StarBreacher is denied!",
    star_breach_prey_destroyed: "The Prey was destroyed — the StarBreacher feeds",
    star_breach_objective_failed: "Round 6 ended with The Prey outside The Fang",
  };

  function showEndgame() {
    endgameShown = true;
    const overlay = els["endgame-overlay"];
    const winners = new Set((view.result && view.result.winner_ids) || []);
    const stats = battleStats();
    const rows = seatOrder()
      .map((playerId) => ({ playerId, player: view.players[playerId] }))
      .filter((row) => row.player)
      .sort((a, b) => b.player.victory_points - a.player.victory_points);
    const youWon = winners.has(you);
    const forfeits = (view.event_log || [])
      .filter((event) => event.type === "player_forfeited")
      .map((event) => `${displayName(event.player_id)} struck their colors in round ${event.round}`);
    const reason = view.result && RESULT_REASONS[view.result.reason]
      ? RESULT_REASONS[view.result.reason]
      : (view.result && view.result.reason) || "";
    overlay.innerHTML = "";
    overlay.classList.remove("hidden");
    const box = document.createElement("div");
    box.className = "endgame";
    box.innerHTML = `
      <h2>${you === null ? "Battle Report" : youWon ? "🏴‍☠ VICTORY!" : winners.size ? "Defeat…" : view.star_breach ? "☄ The StarBreacher Prevails…" : "Stalemate"}</h2>
      <div class="eg-sub">${esc([...winners].map(displayName).join(" & ") || "No captain")} rules this stretch of the void
        ${view.result && view.result.is_tie ? " (a tie, settled over grog)" : ""}<br>
        <b>How it ended:</b> ${esc(reason)} · ${view.round_number > 6 ? 6 : view.round_number} round${view.round_number > 1 ? "s" : ""} fought
        ${forfeits.length ? `<br>🏳 ${esc(forfeits.join("; "))}` : ""}</div>
      <div class="eg-grid">
        ${rows.map((row, index) => {
          const s = stats[row.playerId];
          const ship = row.player.ship || {};
          const fate = row.player.eliminated && !ship.destroyed ? "🏳 fled"
            : ship.destroyed ? `☠ sunk${s.killedBy ? " by " + esc(displayName(s.killedBy)) : ""}${ship.knocked_out_round ? ` (round ${ship.knocked_out_round})` : ""}`
            : "⚓ afloat";
          const hitPct = s.shots ? Math.round((s.hits / s.shots) * 100) : 0;
          return `
          <div class="eg-card ${winners.has(row.playerId) ? "winner" : ""}" style="border-left-color:${Board.colorOf(row.playerId)}">
            <div class="eg-card-head">
              <span class="eg-rank">${winners.has(row.playerId) ? "👑" : "#" + (index + 1)}</span>
              <b>${esc(displayName(row.playerId))}</b>${row.playerId === you ? ' <span class="badge-you">YOU</span>' : ""}
            </div>
            <div class="eg-card-body">
              <div class="eg-mini">${ShipView.miniShipSVG(ship, 92)}</div>
              <div class="eg-stats">
                <div><b>${row.player.victory_points} VP</b> <span class="eg-dim">(✦ ${s.baubleVp} loot · ☄ ${s.attackVp} combat)</span></div>
                <div>Gunnery: <b>${s.hits}/${s.shots}</b> hits (${hitPct}%) · <b>${s.damageDealt}</b> dmg dealt</div>
                <div>Hull: <b>${ship.damage_taken || 0}</b> damage taken · ${s.shieldBlocks} shield block${s.shieldBlocks === 1 ? "" : "s"}</div>
                <div>Baubles claimed: <b>${s.loot}</b></div>
                ${s.kills.length ? `<div>Sank: <b>${esc(s.kills.map(displayName).join(", "))}</b></div>` : ""}
                <div class="eg-fate">${fate}</div>
              </div>
            </div>
          </div>`;
        }).join("")}
      </div>
      <div class="feedback-spot">
        <h3>Feedback and Bugs</h3>
        <p>We're in playtest, and would appreciate your feedback immensely. You'll even get a badge for sharing your thoughts!</p>
        <button class="btn gold" id="btn-endgame-feedback">Feedback and Bugs</button>
      </div>
      <div style="display:flex;gap:10px;justify-content:center;flex-wrap:wrap">
        <button class="btn ghost" id="btn-endgame-view">👁 View Battlefield</button>
        <button class="btn crimson" id="btn-endgame-replay">▶ Replay the Battle</button>
        <button class="btn gold big" id="btn-endgame-port">⚓ Return to Port</button>
      </div>`;
    overlay.appendChild(box);
    document.getElementById("btn-endgame-port").addEventListener("click", () => {
      overlay.classList.add("hidden");
      leave();
      Lobby.enter();
    });
    document.getElementById("btn-endgame-view").addEventListener("click", () => {
      overlay.classList.add("hidden");
    });
    document.getElementById("btn-endgame-feedback").addEventListener("click", () => {
      window.Feedback?.open({ gameId, matchId: match && match.id });
    });
    document.getElementById("btn-endgame-replay").addEventListener("click", async () => {
      overlay.classList.add("hidden");
      await playEventsSafely(view.event_log || []);
      renderAll();
      showEndgame();
    });
  }

  /* Reopen the battle report after closing it (📜 button on the board). */
  function updateReportButton() {
    let node = document.getElementById("btn-battle-report");
    const wanted = view && view.phase === "complete";
    if (wanted && !node) {
      node = document.createElement("button");
      node.id = "btn-battle-report";
      node.className = "btn gold small";
      node.textContent = "📜 Report";
      node.title = "Battle report";
      node.addEventListener("click", showEndgame);
      document.querySelector(".board-controls").appendChild(node);
    } else if (!wanted && node) {
      node.remove();
    }
    let exportButton = document.getElementById("btn-export-log");
    if (view && gameId && !exportButton) {
      exportButton = document.createElement("button");
      exportButton.id = "btn-export-log";
      exportButton.className = "btn ghost small";
      exportButton.textContent = "Export Log";
      exportButton.title = "Copy a debugging log to the clipboard";
      exportButton.addEventListener("click", exportDebugLog);
      document.querySelector(".log-actions")?.appendChild(exportButton);
    } else if ((!view || !gameId) && exportButton) {
      exportButton.remove();
    }
    let feedbackButton = document.getElementById("btn-game-feedback");
    if (view && gameId && !feedbackButton) {
      feedbackButton = document.createElement("button");
      feedbackButton.id = "btn-game-feedback";
      feedbackButton.className = "btn gold small";
      feedbackButton.textContent = "Feedback and Bugs";
      feedbackButton.title = "Send playtest feedback or report a bug with this battle log";
      feedbackButton.addEventListener("click", () => {
        window.Feedback?.open({ gameId, matchId: match && match.id });
      });
      document.querySelector(".board-controls").appendChild(feedbackButton);
    } else if ((!view || !gameId) && feedbackButton) {
      feedbackButton.remove();
    }
  }

  async function copyText(text) {
    if (navigator.clipboard && window.isSecureContext) {
      await navigator.clipboard.writeText(text);
      return;
    }
    const textarea = document.createElement("textarea");
    textarea.value = text;
    textarea.setAttribute("readonly", "");
    textarea.style.position = "fixed";
    textarea.style.left = "-9999px";
    document.body.appendChild(textarea);
    textarea.select();
    const ok = document.execCommand("copy");
    textarea.remove();
    if (!ok) throw new Error("Clipboard copy failed.");
  }

  async function exportDebugLog() {
    const button = document.getElementById("btn-export-log");
    if (!gameId || !button) return;
    const oldText = button.textContent;
    button.disabled = true;
    button.textContent = "Copying...";
    try {
      const result = await API.debugLog(gameId);
      await copyText(result.log || "");
      App.toast("Debug log copied to clipboard.", true);
    } catch (error) {
      App.toast(error.message || "Could not export log.");
    } finally {
      button.disabled = false;
      button.textContent = oldText;
    }
  }

  // ── wire up ───────────────────────────────────────────────────────────
  document.addEventListener("DOMContentLoaded", () => {
    grab();
    applyMobileMode();
    window.addEventListener("resize", applyMobileMode);
    window.addEventListener("orientationchange", () => {
      window.setTimeout(() => {
        applyMobileMode();
        if (document.documentElement.dataset.device === "phone") Board.resetView?.();
      }, 150);
    });
    els["btn-submit-orders"].addEventListener("click", submitOrders);
    els["btn-clear-orders"].addEventListener("click", () => {
      orderTrace("draft_cleared");
      draft = emptyDraft();
      saveDraft();
      renderOrdersPanel();
    });
    document.getElementById("btn-back-lobby").addEventListener("click", () => { leave(); Lobby.enter(); });
    document.getElementById("btn-replay-sofar").addEventListener("click", async () => {
      if (!view || animating) return;
      animating = true;
      renderAll();
      await playEventsSafely(view.event_log || []);
      renderAll();
    });
  });

  window.Game = { enter, leave };
})();
