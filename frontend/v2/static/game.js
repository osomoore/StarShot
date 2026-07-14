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
  let endgameShown = false;
  let draft = null;
  let pendingFetch = false;

  const els = {};
  function grab() {
    for (const id of ["game-banner", "fleet-list", "action-log", "order-slots", "hand-area",
      "btn-submit-orders", "btn-clear-orders", "orders-hint", "deck-count", "discard-count",
      "picker-overlay", "endgame-overlay", "board-callout", "board-wrap", "orders-panel"]) {
      els[id] = document.getElementById(id);
    }
    els["fleet-panel"] = document.querySelector(".fleet-panel");
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
      playEvents(fresh).then(renderAll);
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
      await playEvents(view.event_log || []);
      renderAll();
    });
  }

  function isVisualEvent(event) {
    return ["movement_resolved", "volley_resolved", "bauble_awarded", "round_advanced",
      "desperation_consequence", "player_forfeited", "starfall_revealed",
      "starfall_take_cover_damage", "captain_cleanup_movement",
      "boss_phase_started", "boss_phase_resolved", "enemy_volley_resolved",
      "boss_volley_resolved", "craft_volley_resolved", "repair_volley_resolved",
      "boss_progress_advanced", "boss_tiers_activated"].includes(event.type);
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
    els["game-banner"].textContent = `Round ${view.round_number} of 6 · ${PHASE_LABELS[view.phase] || view.phase}`;
    Board.renderBaubles(view.baubles, view.round_number, { activeNumbers: extraActiveBaubleNumbers() });
    Board.renderStarBreach(view.star_breach, { preyPos: preyPosition() });
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
      if (node) node.remove();
      return;
    }
    if (!node) {
      node = document.createElement("div");
      node.id = "starfall-status";
      node.className = "starfall-status";
      statusStack().appendChild(node);
    }
    const sf = view.active_starfall;
    node.innerHTML = `<b>${esc(sf.name)}</b><span>${esc(sf.text)}</span>`;
  }

  function renderCaptainStatus() {
    let node = document.getElementById("captain-status");
    const me = view.players[you];
    const captain = me && me.captain;
    if (!captain) {
      if (node) node.remove();
      return;
    }
    if (!node) {
      node = document.createElement("div");
      node.id = "captain-status";
      node.className = "captain-status";
      statusStack().appendChild(node);
    }
    node.innerHTML = `<b>${esc(captain.callsign || captain.name)}</b><span>${esc(captain.text)}</span>`;
  }

  function preyPosition() {
    const sb = view && view.star_breach;
    if (!sb) return null;
    const prey = view.players[sb.prey_player_id];
    return prey && prey.ship && !prey.ship.destroyed ? { q: prey.ship.q, r: prey.ship.r } : null;
  }

  function myRoles() {
    const me = myPlayer();
    return (me && me.roles) || [];
  }

  function renderStarBreachStatus() {
    let node = document.getElementById("starbreach-status");
    const sb = view.star_breach;
    if (!sb) {
      if (node) node.remove();
      document.getElementById("boss-progress-rail")?.remove();
      document.getElementById("sb-pause-toggle")?.remove();
      return;
    }
    if (!node) {
      node = document.createElement("div");
      node.id = "starbreach-status";
      node.className = "starfall-status";
      node.style.cursor = "pointer";
      node.addEventListener("click", showBossModal);
      statusStack().appendChild(node);
    }
    const shields = ["forward", "port", "rear", "starboard"]
      .map((area) => `${area[0].toUpperCase()}${sb.shield_hp?.[area] ?? 0}`)
      .join(" ");
    const fleetAlive = (sb.fleet || []).filter((craft) => !craft.destroyed).length;
    const roleNames = myRoles().map((role) => (sb.roles && sb.roles[role] ? sb.roles[role].name : role)).join(" + ");
    node.innerHTML = `<b>☄ StarBreacher</b>
      <span>Prey: ${esc(displayName(sb.prey_player_id))} · Progress ${sb.progress}
      · Shields ${esc(shields)} · Hunters ${fleetAlive}${roleNames ? ` · You: ${esc(roleNames)}` : ""}
      · <u>damage board</u></span>`;
    node.title = "Click for the StarBreacher's damage board.";
    renderBossProgressRail();
    renderPauseToggle();
  }

  function renderBossProgressRail() {
    const sb = view.star_breach;
    let rail = document.getElementById("boss-progress-rail");
    if (!sb) { rail?.remove(); return; }
    if (!rail) {
      rail = document.createElement("div");
      rail.id = "boss-progress-rail";
      rail.className = "boss-progress-rail";
      rail.title = "Boss Progress Track — hits on The Prey fill it; tiers power up at the next round's start.";
      els["board-wrap"].appendChild(rail);
    }
    const maxTrack = Math.max(...Object.values(sb.tier_progress || { x: 12 }).map(Number), sb.progress || 0);
    const ticks = Object.entries(sb.tier_progress || {}).map(([tier, threshold]) => {
      const active = (sb.active_tiers || []).includes(Number(tier));
      return `<div class="bpr-tick ${active ? "active" : ""}" style="bottom:${(threshold / maxTrack) * 100}%"></div>`;
    }).join("");
    rail.innerHTML = `<div class="bpr-label">☄ ${sb.progress}</div>
      <div class="bpr-fill" style="height:${Math.min(100, (sb.progress / maxTrack) * 100)}%"></div>${ticks}`;
  }

  function pauseAfterActions() {
    try { return (localStorage.getItem("ss_sb_pause") ?? "1") === "1"; } catch (err) { return true; }
  }

  function renderPauseToggle() {
    if (document.getElementById("sb-pause-toggle")) return;
    const label = document.createElement("label");
    label.id = "sb-pause-toggle";
    label.className = "sb-pause-toggle";
    label.innerHTML = `<input type="checkbox" ${pauseAfterActions() ? "checked" : ""}> ⏸ Pause after each player action`;
    label.querySelector("input").addEventListener("change", (event) => {
      try { localStorage.setItem("ss_sb_pause", event.target.checked ? "1" : "0"); } catch (err) {}
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
      card.title = "Click for the full ship board and damage lanes";
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
        const who = (event.awards || []).map((award) => `${name(award.player_id)} +${award.vp_awarded} VP`).join(", ");
        return { cls: "loot", text: `✦ Loot claimed: ${who}` };
      }
      case "desperation_consequence": return { cls: "hit", text: `${name(event.player_id)} grows desperate…` };
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
      case "enemy_volley_resolved": {
        const result = event.shielded ? "shield takes it" : event.hit ? `HIT for ${event.damage_applied || 1}` : "misses";
        return { cls: event.hit ? "hit" : "", text: `${targetLabel(event.attacker)} fires on ${name(event.target_id)} — 🎲${event.roll}${event.aim_bonus ? "+" + event.aim_bonus : ""} vs ${event.defense_threshold}: ${result}${event.target_destroyed ? " — SHIP DESTROYED ☠" : ""}` };
      }
      case "boss_volley_resolved": {
        let result = "misses";
        if (event.hit) {
          const bits = [];
          if (event.shields_absorbed) bits.push(`${event.shields_absorbed} soaked by shields`);
          if (event.hexes_destroyed) bits.push(`${event.hexes_destroyed} hull hex${event.hexes_destroyed > 1 ? "es" : ""} destroyed`);
          if ((event.components_destroyed || []).length) bits.push(`${event.components_destroyed.join(", ")} DESTROYED`);
          if (event.desperation_cards_drawn) bits.push("glancing blow — desperation card");
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
    container.scrollTop = container.scrollHeight;
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
      });
      details.appendChild(shotPreview);
      seal.appendChild(details);
    }
    node.appendChild(seal);
    return node;
  }

  function slotShotPreviewEl(index) {
    const projections = attackProjectionsForSlot(index);
    if (!projections.length) return null;
    const node = document.createElement("div");
    node.className = "slot-shot-preview";
    node.innerHTML = `
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
    return node;
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

  /* The StarBreacher's damage board: internal hull, components, shields,
     expected actions per boss step, and the progress track. */
  function showBossModal() {
    const sb = view.star_breach;
    if (!sb || !sb.boss_layout) return;
    const destroyed = new Set((sb.destroyed_hexes || []).map(([q, r]) => q + "," + r));
    const componentsByHex = {};
    for (const component of sb.boss_layout.components || []) {
      componentsByHex[component.q + "," + component.r] = component;
    }
    const AREA_FILL = { forward: "217,166,255", port: "170,110,190", rear: "190,120,80", starboard: "110,170,120" };
    const BADGE = { shield_generator: "SG", firing_computer: "FC", fuel_tank: "FT", core: "◉" };
    const size = 13, sq = Math.sqrt(3);
    const cells = sb.boss_layout.footprint || [];
    let svgBody = "";
    for (const cell of cells) {
      const x = size * 1.5 * cell.q, y = size * sq * (cell.r + cell.q / 2);
      const dead = destroyed.has(cell.q + "," + cell.r);
      const tint = AREA_FILL[cell.area] || "150,150,150";
      const pts = [];
      for (let i = 0; i < 6; i++) {
        const a = (Math.PI / 180) * (60 * i);
        pts.push(`${(x + (size - 0.8) * Math.cos(a)).toFixed(1)},${(y + (size - 0.8) * Math.sin(a)).toFixed(1)}`);
      }
      const component = componentsByHex[cell.q + "," + cell.r];
      svgBody += `<polygon points="${pts.join(" ")}" fill="${dead ? "rgba(25,25,32,.9)" : `rgba(${tint},.5)`}"
        stroke="${dead ? "#333" : `rgb(${tint})`}" stroke-width="1"><title>${esc(component ? component.name : `${cell.area} hull`)}${dead ? " (destroyed)" : ""}</title></polygon>`;
      if (component) {
        svgBody += `<text x="${x}" y="${y + 3.5}" text-anchor="middle" font-size="8.5" font-weight="700"
          fill="${dead ? "#555" : "#0a0f1e"}" pointer-events="none">${BADGE[component.type] || "?"}</text>`;
      } else if (dead) {
        svgBody += `<text x="${x}" y="${y + 3.5}" text-anchor="middle" font-size="9" fill="#555" pointer-events="none">✕</text>`;
      }
    }
    const qs = cells.map((c) => c.q), rs = cells.map((c) => size * sq * (c.r + c.q / 2));
    const minX = Math.min(...qs) * size * 1.5 - size * 1.5, maxX = Math.max(...qs) * size * 1.5 + size * 1.5;
    const minY = Math.min(...rs) - size * 1.5, maxY = Math.max(...rs) + size * 1.5;
    const shields = ["forward", "port", "rear", "starboard"].map((area) => {
      const hp = sb.shield_hp?.[area] ?? 0, max = sb.shield_max?.[area] ?? hp;
      return `<td>${esc(area)}</td><td>${"🛡".repeat(hp) || "—"} ${hp}/${max}</td>`;
    }).map((row) => `<tr>${row}</tr>`).join("");
    const PHASE_NAMES = { "0.5": "Action 0.5 (attack)", "1.5": "Action 1.5 (move)", "2.5": "Action 2.5 (move)", "3.5": "Action 3.5 (attack)", starbreach: "StarBreach (attack)" };
    const expected = Object.entries(sb.expected_actions || {})
      .map(([phase, count]) => `<tr><td>${esc(PHASE_NAMES[phase] || phase)}</td><td><b>${count}</b> action${count === 1 ? "" : "s"}</td></tr>`)
      .join("");
    const maxTrack = Math.max(...Object.values(sb.tier_progress || { x: 12 }).map(Number), sb.progress || 0);
    const ticks = Object.entries(sb.tier_progress || {}).map(([tier, threshold]) => {
      const active = (sb.active_tiers || []).includes(Number(tier));
      const reached = (sb.tiers_unlocked || []).includes(Number(tier));
      return `<div class="bt-tick ${active ? "active" : ""}" style="left:${(threshold / maxTrack) * 100}%"
        title="Tier ${tier} at ${threshold}${active ? " (active)" : reached ? " (powers up next round)" : ""}"></div>`;
    }).join("");
    const pendingTiers = (sb.tiers_unlocked || []).filter((tier) => !(sb.active_tiers || []).includes(tier));
    const overlay = els["picker-overlay"];
    overlay.innerHTML = "";
    overlay.classList.remove("hidden");
    const box = document.createElement("div");
    box.className = "picker";
    box.style.maxWidth = "640px";
    box.innerHTML = `
      <h3>☄ The StarBreacher — Damage Board</h3>
      <div class="boss-modal-grid">
        <div class="boss-modal-map">
          <svg viewBox="${minX} ${minY} ${maxX - minX} ${maxY - minY}" style="width:100%;max-height:300px">${svgBody}</svg>
        </div>
        <div class="boss-modal-side">
          <h4>Progress Track — ${sb.progress}</h4>
          <div class="boss-track">
            <div class="bt-fill" style="width:${Math.min(100, (sb.progress / maxTrack) * 100)}%"></div>
            ${ticks}
          </div>
          ${pendingTiers.length ? `<div style="margin-top:4px;color:#ff9d8a">Tier ${pendingTiers.join(", ")} powers up next round!</div>` : ""}
          <h4>Shield Arcs</h4>
          <table>${shields}</table>
          <h4>Expected Actions</h4>
          <table>${expected}</table>
          <div style="margin-top:6px">SG = Shield Generator · FC = Firing Computer · FT = Fuel Tank.
            Destroying an FC or FT removes its action; hits on The Prey advance the track.</div>
        </div>
      </div>
      <button class="btn ghost picker-cancel" id="boss-modal-close">Close</button>`;
    overlay.appendChild(box);
    box.querySelector("#boss-modal-close").addEventListener("click", hidePicker);
    overlay.addEventListener("click", function onOverlay(event) {
      if (event.target === overlay) { hidePicker(); overlay.removeEventListener("click", onOverlay); }
    });
  }

  /* Co-op target list: intact boss areas, living hunter-killers, and (for
     the Engineer) crew ships to repair. */
  function coopTargetOptions() {
    const sb = view.star_breach;
    if (!sb) return [];
    const destroyed = new Set((sb.destroyed_hexes || []).map(([q, r]) => q + "," + r));
    const areaAlive = {};
    for (const cell of (sb.boss_layout || {}).footprint || []) {
      if (!destroyed.has(cell.q + "," + cell.r)) areaAlive[cell.area] = true;
    }
    const options = [];
    for (const area of ["forward", "port", "rear", "starboard"]) {
      if (!areaAlive[area]) continue;
      options.push({
        icon: "☄", value: "boss:" + area,
        label: `StarBreacher — ${area}`,
        sub: `shield ${sb.shield_hp?.[area] ?? 0}/${sb.shield_max?.[area] ?? 3}`,
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
    const selection = {
      card_id: card.id,
      face: "front",
      orientation: "up",
      mode: null,
      target_player_id: null,
      repair_component_ids: [],
      reconfigure_from_component_ids: [],
      reconfigure_to_component_ids: [],
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
        if (!mode) return;
        selection.mode = mode;
        selection.family = mode;
        orientationOptions = opts;
      } else if (face.repair_components || face.reconfigure_components) {
        const mode = await showPicker("Patch it during...", [
          { icon: "M", label: "Move stack", value: "move" },
          { icon: "A", label: "Attack stack", value: "attack" },
        ]);
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
        if (!orientation) return;
        selection.orientation = orientation;
      } else {
        selection.orientation = orientationOptions[0] || "forward";
      }
    }

    if (selection.face === "desperate" && card.desperate_face) {
      if (card.desperate_face.repair_components) {
        const picked = await pickComponents("Restore which hull tile?", damagedComponents(), card.desperate_face.repair_components);
        if (!picked) return;
        selection.repair_component_ids = picked;
      }
      if (card.desperate_face.reconfigure_components) {
        const count = card.desperate_face.reconfigure_components;
        const from = await pickComponents("Move damage from...", damagedComponents(), count);
        if (!from) return;
        const interimDestroyed = new Set(destroyedComponentIds());
        from.forEach((id) => interimDestroyed.delete(id));
        const to = await pickComponents(
          "Move damage to...",
          intactComponents().filter((component) => !from.includes(component.id) && isAdjacentToIntact(component, interimDestroyed)),
          count
        );
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
        if (!options.length) { App.toast("Nothing left to shoot at."); return; }
        const chosen = await new Promise((resolve) => {
          targetResolver = resolve;
          showPicker("Mark yer target (or click the boss)", options)
            .then((value) => { if (targetResolver) { targetResolver = null; resolve(value); } });
        });
        if (!chosen) return;
        selection.target_player_id = chosen;
      } else if (needsTarget) {
        const enemies = seatOrder().filter((pid) => {
          const player = view.players[pid];
          return pid !== you && player && !player.eliminated && !(player.ship || {}).destroyed;
        });
        if (!enemies.length) { App.toast("No targets left afloat."); return; }
        const chosen = await new Promise((resolve) => {
          targetResolver = resolve;
          showPicker("Mark yer target (or click a ship)", enemies.map((pid) => ({
            icon: "☠", label: displayName(pid), value: pid,
          }))).then((value) => { if (targetResolver) { targetResolver = null; resolve(value); } });
        });
        if (!chosen) return;
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
        })),
      })),
    };
    els["btn-submit-orders"].disabled = true;
    try {
      const response = await API.submitOrders(gameId, payload);
      draft = emptyDraft();
      armedSlot = null;
      Board.clearPreview();
      App.toast("Orders sealed. Fair winds!", true);
      applyPayload(response, false);
    } catch (error) {
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
      const words = component.name.split(" ");
      names[component.id] = words[words.length - 1];
    }
    const sources = (event.slots || []).map((slot) => {
      if (slot.slot === "base") return "Base";
      if (slot.slot === "tier") return `Tier ${slot.tier}`;
      return names[slot.component_id] || slot.component_id;
    });
    const maxTrack = Math.max(...Object.values(sb.tier_progress || { x: 12 }).map(Number), event.progress || 0);
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

  function updateProgressRail(progress) {
    const sb = view.star_breach;
    const rail = document.getElementById("boss-progress-rail");
    if (!sb || !rail) return;
    const maxTrack = Math.max(...Object.values(sb.tier_progress || { x: 12 }).map(Number), progress || 0);
    const fill = rail.querySelector(".bpr-fill");
    const label = rail.querySelector(".bpr-label");
    if (fill) fill.style.height = Math.min(100, (progress / maxTrack) * 100) + "%";
    if (label) label.textContent = "☄ " + progress;
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

  async function playEvents(events) {
    animating = true;
    skipReplay = false;
    replayShipStates = buildReplayShipStates(events);
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
      replayControls(false);
    }
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
        else if (event.phase === "award_baubles") callout("✦ Claim the Loot");
        return;
      case "round_advanced":
        callout(`Round ${event.round}`);
        await wait(700);
        return;
      case "action_revealed":
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
        await showBossPhaseCallout(event);
        return;
      }
      case "boss_phase_resolved": {
        if (event.kind !== "move") return;
        for (const slot of event.slots || []) {
          const move = slot.movement;
          if (!move || !move.moved) continue;
          Board.renderStarBreach(view.star_breach, {
            pose: { q: move.after.anchor_q, r: move.after.anchor_r, facing: move.after.facing },
            preyPos: preyPosition(),
          });
          FX.trail(Board.hexToScreen(move.after.anchor_q, move.after.anchor_r), "#a86ad1");
          for (const push of move.pushed || []) {
            const pushedPlayer = view.players[push.ship];
            if (pushedPlayer) Board.placeShip(push.ship, push.to[0], push.to[1], pushedPlayer.ship.facing);
          }
          await wait(340);
        }
        Board.renderStarBreach(view.star_breach, { preyPos: preyPosition() });
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
          if (event.desperation_cards_drawn) bits.push("glancing blow");
          FX.floatText(to, bits.join(" · ") || "no effect", "#d9a6ff");
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
        updateProgressRail(event.progress);
        return;
      }
      case "boss_tiers_activated": {
        callout(`☄ Boss Tier ${event.tiers.join(", ")} online!`, true);
        await wait(700);
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
        const player = view.players[event.player_id];
        if (player) {
          const at = Board.hexToScreen(player.ship.q, player.ship.r);
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
      await playEvents(view.event_log || []);
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
      document.querySelector(".board-controls").appendChild(exportButton);
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
    els["btn-clear-orders"].addEventListener("click", () => { draft = emptyDraft(); renderOrdersPanel(); });
    document.getElementById("btn-back-lobby").addEventListener("click", () => { leave(); Lobby.enter(); });
    document.getElementById("btn-replay-sofar").addEventListener("click", async () => {
      if (!view || animating) return;
      animating = true;
      renderAll();
      await playEvents(view.event_log || []);
      renderAll();
    });
  });

  window.Game = { enter, leave };
})();
