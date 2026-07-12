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
  }

  function isPhoneUser() {
    const coarsePointer = window.matchMedia?.("(pointer: coarse)")?.matches;
    const narrow = window.matchMedia?.("(max-width: 760px)")?.matches;
    const compactHeight = window.matchMedia?.("(max-height: 620px)")?.matches;
    const mobileAgent = /Android|iPhone|iPod|IEMobile|Mobile/i.test(navigator.userAgent || "");
    return Boolean((coarsePointer && narrow) || (mobileAgent && (narrow || compactHeight)));
  }

  function applyMobileMode() {
    const phone = isPhoneUser();
    document.documentElement.dataset.device = phone ? "phone" : "desktop";
    if (!phone) {
      document.body.classList.remove("mobile-orders-open");
      return;
    }
    ensureMobileHud();
  }

  function ensureMobileHud() {
    if (!document.getElementById("mobile-game-hud")) {
      const hud = document.createElement("nav");
      hud.id = "mobile-game-hud";
      hud.className = "mobile-game-hud";
      hud.setAttribute("aria-label", "Mobile game controls");
      hud.innerHTML = `
        <button class="btn gold" type="button" data-mobile-action="orders">Orders</button>
        <button class="btn ghost" type="button" data-mobile-action="fleet">Fleet</button>
        <button class="btn ghost" type="button" data-mobile-action="center">Center</button>
      `;
      hud.addEventListener("click", (event) => {
        const action = event.target.closest("[data-mobile-action]")?.dataset.mobileAction;
        if (action === "orders") toggleMobileOrders();
        if (action === "fleet") showMyShipOrFleet();
        if (action === "center") Board.resetView?.();
      });
      document.body.appendChild(hud);
    }
    if (!document.getElementById("mobile-orders-close") && els["orders-panel"]) {
      const close = document.createElement("button");
      close.id = "mobile-orders-close";
      close.className = "btn ghost small mobile-orders-close";
      close.type = "button";
      close.textContent = "Map";
      close.addEventListener("click", () => setMobileOrdersOpen(false));
      els["orders-panel"].prepend(close);
    }
  }

  function toggleMobileOrders() {
    setMobileOrdersOpen(!document.body.classList.contains("mobile-orders-open"));
  }

  function setMobileOrdersOpen(open) {
    document.body.classList.toggle("mobile-orders-open", Boolean(open));
  }

  function showMyShipOrFleet() {
    if (!view) return;
    if (you && view?.players?.[you]) {
      showShipModal(you);
      return;
    }
    const first = seatOrder()[0];
    if (first) showShipModal(first);
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
    Board.build();
    Board.setShipClickHandler(handleShipClick);
    if (document.documentElement.dataset.device === "phone") Board.resetView?.();
    await fetchView(true);
    if (pollTimer) clearInterval(pollTimer);
    pollTimer = setInterval(() => fetchView(false), POLL_MS);
  }

  function leave() {
    if (pollTimer) clearInterval(pollTimer);
    pollTimer = null;
    gameId = null;
    document.body.classList.remove("mobile-orders-open");
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
      for (const seat of match.seat_list) names[seat.player_id] = seat.display_name;
      Board.setNameMap(names);
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
      if (events.some(isVisualEvent)) {
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
      "desperation_consequence", "player_forfeited"].includes(event.type);
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

  function renderAll() {
    if (!view) return;
    els["game-banner"].textContent = `Round ${view.round_number} of 6 · ${PHASE_LABELS[view.phase] || view.phase}`;
    Board.renderBaubles(view.baubles, view.round_number);
    Board.renderShips(view.players, seatOrder(), you);
    renderFleet();
    renderLog();
    renderOrdersPanel();
    updateReportButton();
    if (view.phase === "complete" && !endgameShown && !animating) showEndgame();
  }

  function renderFleet() {
    const container = els["fleet-list"];
    container.innerHTML = "";
    for (const playerId of seatOrder()) {
      const player = view.players[playerId];
      if (!player) continue;
      const ship = player.ship || {};
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
            ${seat && seat.is_ai ? `<span class="badge-ai">${esc(seat.ai_label || "AI")}</span>` : ""}
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
    const ship = player.ship || {};
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
    els["btn-submit-orders"].disabled = !ordering;
    els["btn-clear-orders"].disabled = !ordering;

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

  function slotEl(index, ordering) {
    const slot = draft.slots[index];
    const node = document.createElement("div");
    node.className = "order-slot" + (armedSlot === index ? " armed" : "");
    node.dataset.slot = index;
    if (ordering) {
      // Click the slot itself (not a card/seal) to arm it for slot-first picking.
      node.addEventListener("click", (event) => {
        if (event.target.closest(".card") || event.target.closest(".seal-toggle")) return;
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
    seal.innerHTML = `<div class="seal-toggle ${slot.seal === "overdrive" ? "overdrive" : ""}" title="Toggle Sealed / Overdrive">${slot.seal === "overdrive" ? "🔥" : "☠"}</div>
      <div class="seal-note">${slot.seal === "overdrive" ? "OVERDRIVE ×2" : "sealed"}</div>`;
    if (ordering) {
      seal.querySelector(".seal-toggle").addEventListener("click", () => {
        slot.seal = slot.seal === "overdrive" ? "sealed" : "overdrive";
        renderOrdersPanel();
      });
    }
    const label = document.createElement("div");
    label.className = "slot-label";
    label.innerHTML = `Action<br>${["I", "II", "III"][index]}`;
    node.appendChild(label);
    node.appendChild(cardsHtml);
    node.appendChild(seal);
    return node;
  }

  function useTag(selection) {
    if (selection.family === "attack") {
      return selection.target_player_id ? "→ " + Board.shortName(selection.target_player_id) : "→ ahead";
    }
    return Cards.orientationLabel(selection.orientation).split(" ")[0];
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

  async function beginPlacement(card, presetSlot = null) {
    const selection = { card_id: card.id, face: "front", orientation: "up", mode: null, target_player_id: null, card, family: null };

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
      if (needsTarget) {
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
    const canTake = (slot) => slot.cards.length < 2
      && (!slot.cards.length || slot.cards[0].family === selection.family);
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
        App.toast("Both cannons aim at " + displayName(existing) + " — one volley, one target.", true);
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
  function p2d6AtLeast(needed) {
    if (needed <= 2) return 1;
    if (needed > 12) return 0;
    let count = 0;
    for (let a = 1; a <= 6; a++) for (let b = 1; b <= 6; b++) if (a + b >= needed) count++;
    return count / 36;
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
    const desperate = selection.face === "desperate";
    const face = desperate ? card.desperate_face : card.effect;
    const value = face.value || 0;
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
      const moveSelections = slot.cards.filter((s) => s.family === "move");
      const attackSelections = slot.cards.filter((s) => s.family === "attack");
      if (moveSelections.length) {
        const points = [{ q: pos.q, r: pos.r }];
        const passes = overdriven ? 2 : 1;
        for (let pass = 0; pass < passes; pass++) {
          for (const selection of moveSelections) {
            if (pass > 0 && selection.face === "desperate") continue; // not copied
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
        let aim = 0, always = false, lead = false, target = null;
        for (const selection of attackSelections) {
          if (selection.target_player_id) target = selection.target_player_id;
          if (selection.face === "desperate") {
            const face = selection.card.desperate_face;
            aim += face.aim_bonus || 0;
            always = always || face.always_hits || (face.aim_bonus || 0) >= 99;
            lead = lead || face.lead_the_target;
          } else {
            const match_ = /aim \+?(\d+)/i.exec(selection.card.name);
            if (match_) aim += parseInt(match_[1], 10);
          }
        }
        // Untargeted volley: it will hit whatever sits dead ahead after we move.
        let ahead = false;
        if (!target) {
          target = forwardTarget(pos);
          ahead = true;
        }
        const enemy = target && view.players[target];
        if (enemy && enemy.ship) {
          const distance = Board.hexDistance(pos.q, pos.r, enemy.ship.q, enemy.ship.r);
          const predictedMove = lead ? 0 : Math.round(expectedTargetMove(target));
          const needed = distance + predictedMove - aim;
          const pct = Math.round((always ? 1 : p2d6AtLeast(needed)) * 100);
          items.push({
            kind: "shot", from: { q: pos.q, r: pos.r }, to: { q: enemy.ship.q, r: enemy.ship.r },
            label: `A${numerals[index]}${ahead ? " ⇢ ahead" : ""} · ${pct}% to hit${overdriven ? " ×2" : ""}`,
          });
        } else if (ahead) {
          // Nothing on the line right now — show the wasted shot honestly.
          const [dq, dr] = Board.DIRECTIONS[((pos.facing % 6) + 6) % 6];
          items.push({
            kind: "shot", from: { q: pos.q, r: pos.r },
            to: { q: pos.q + dq * 4, r: pos.r + dr * 4 },
            label: `A${numerals[index]} ⇢ no ship ahead!`,
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

  async function playEvents(events) {
    animating = true;
    skipReplay = false;
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
      for (const event of events) {
        await playEvent(event);
      }
    } finally {
      animating = false;
      skipReplay = false;
      replayControls(false);
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
        for (const step of event.steps || []) {
          const from = step.before, to = step.after;
          const frames = 9;
          for (let frame = 1; frame <= frames; frame++) {
            const q = from.q + (to.q - from.q) * (frame / frames);
            const r = from.r + (to.r - from.r) * (frame / frames);
            Board.placeShip(event.player_id, q, r, to.facing);
            FX.trail(Board.hexToScreen(q, r), Board.colorOf(event.player_id));
            await wait(26);
          }
          if (step.warp_destination) FX.warp(Board.hexToScreen(to.q, to.r));
        }
        await wait(120);
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
      <h2>${you === null ? "Battle Report" : youWon ? "🏴‍☠ VICTORY!" : winners.size ? "Defeat…" : "Stalemate"}</h2>
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
