/* Lobby: quick match queue, crew builder, open raids, leaderboard, profile. */
(function () {
  const AI_META = {
    vault_runner: { face: "📦", name: "Freebooter", blurb: "Booty Hunter" },
    hunter_killer: { face: "🎯", name: "Bloodthirsty", blurb: "Prey Hunter" },
    blaster: { face: "☄", name: "Cannoneer", blurb: "Chaotic Blaster" },
  };

  let pollTimer = null;
  let leaderboardTimer = null;
  let leaderboardCycle = null;
  let leaderboardIndex = 0;
  let leaderboardRendered = false;
  let queued = false;
  let crew = [];        // selected ai types
  let aiLevel = "deck_hand";
  let currentUser = null;
  let starBreachPreySelection = "__host__";
  let starBreachRoleSelection = "";
  let starBreachBossSelection = "";
  const STAR_BREACH_ROLES = [
    ["vault_runner", "Vault Runner"],
    ["tank", "Tank"],
    ["engineer", "Engineer"],
    ["fighting_ace", "Fighting Ace"],
  ];
  let bossDesignsLoaded = false;
  let shipDesignsLoaded = false;
  let shipDesignSelection = (() => {
    try { return localStorage.getItem("ss_preferred_ship") || ""; } catch (err) { return ""; }
  })();
  let starCommandActive = false;
  let starBreachActive = false;
  let starDockActive = false;
  const activeExpansions = () => [
    ...(starCommandActive ? ["star_command"] : []),
    ...(starBreachActive ? ["star_breach"] : []),
  ];
  const autoEntered = new Set();  // pairings/challenges already jumped into
  const esc = (value) => Cards.escapeHtml(value);
  const feedbackBadge = (count) => Number(count || 0) > 0
    ? `<span class="feedback-badge" title="Feedback shared ${Number(count)} time${Number(count) === 1 ? "" : "s"}">★ ${Number(count)}</span>`
    : "";
  const EXPANSION_META = {
    star_command: { label: "SC", name: "StarCommand" },
    star_breach: { label: "SB", name: "StarBreach" },
    stardock: { label: "SD", name: "StarDock" },
  };
  function expansionBadges(match) {
    const expansions = match.active_expansions || [];
    if (!expansions.length) return "";
    return `<span class="match-expansions">${expansions.map((id) => {
      const meta = EXPANSION_META[id] || { label: id.slice(0, 2).toUpperCase(), name: id };
      return `<span class="match-expansion" title="${esc(meta.name)}">${esc(meta.label)}</span>`;
    }).join("")}</span>`;
  }

  function ensureAdvancedFeaturesToggle() {
    const toggle = document.getElementById("advanced-features-toggle");
    const body = document.getElementById("advanced-features-body");
    if (!toggle || !body || toggle.dataset.wired === "1") return;
    toggle.dataset.wired = "1";
    toggle.addEventListener("click", () => {
      const expanded = toggle.getAttribute("aria-expanded") === "true";
      toggle.setAttribute("aria-expanded", String(!expanded));
      body.classList.toggle("hidden", expanded);
      toggle.querySelector(".advanced-features-arrow").textContent = expanded ? "▶" : "▼";
    });
  }

  async function enter() {
    App.showScreen("lobby");
    leaderboardRendered = false;
    renderAiPickers();
    renderExpansionToggle();
    ensureAdvancedFeaturesToggle();
    await refresh();
    if (pollTimer) clearInterval(pollTimer);
    pollTimer = setInterval(refresh, 3000);
    if (leaderboardTimer) clearInterval(leaderboardTimer);
    leaderboardTimer = setInterval(advanceLeaderboard, 10000);
    Tutorial.offerIfNew();
    window.BossDesigner?.offerBuildContentIntro?.();
  }

  function leave() {
    if (pollTimer) clearInterval(pollTimer);
    if (leaderboardTimer) clearInterval(leaderboardTimer);
    pollTimer = null;
    leaderboardTimer = null;
    leaderboardRendered = false;
  }

  async function refresh() {
    let lobby;
    try {
      lobby = await API.lobby();
    } catch (error) {
      if (error.status === 401) { leave(); App.showScreen("auth"); }
      return;
    }
    queued = lobby.queue.queued;
    document.getElementById("queue-status").classList.toggle("hidden", !queued);
    document.getElementById("btn-quickmatch").classList.toggle("hidden", queued);
    renderMaintenance(lobby.maintenance || "");

    // Your-turn battles first, then active, open, complete.
    const sorted = [...(lobby.my_matches || [])].sort((a, b) => {
      const rank = (match) => (match.turn && match.turn.your_turn ? 0
        : match.status === "active" ? 1 : match.status === "open" ? 2 : 3);
      return rank(a) - rank(b);
    });
    renderMatches("open-matches", lobby.open_matches, true);
    renderMatches("my-matches", sorted, false);
    renderActivePlayers(lobby.active_players || []);
    renderChallenges(lobby.challenges || { incoming: [], outgoing: [] });

    // If we were queued and a fresh active match with a game appears, jump in
    // (once per match — never bounce someone who deliberately came back).
    if (queued) {
      const active = lobby.my_matches.find(
        (match) => match.status === "active" && match.game_id && !autoEntered.has(match.game_id)
      );
      if (active) {
        autoEntered.add(active.game_id);
        leave();
        Game.enter(active.game_id);
        return;
      }
    }
    try {
      const [me, board] = await Promise.all([API.me(), API.leaderboard()]);
      currentUser = me.user;
      renderProfile(me.user);
      renderLeaderboardBundle(board);
      document.getElementById("lobby-user").textContent = me.user.display_name || me.user.username;
      if (me.user.must_rename) openNameModal(true);
      document.getElementById("lobby-admin-link").classList.toggle("hidden", !me.is_admin);
      document.querySelector(".topbar-admin-row")?.classList.toggle("hidden", !me.is_admin);
    } catch (err) { /* transient */ }
  }

  function renderAiPickers() {
    const container = document.getElementById("ai-pickers");
    container.innerHTML = "";
    ensureAiLevelPicker();
    ensureStarBreachPreyPicker();
    for (const type of Object.keys(AI_META)) {
      const meta = AI_META[type];
      const node = document.createElement("div");
      node.className = "ai-pick";
      node.innerHTML = `<div class="ai-name">${esc(meta.name)}</div>
        <div class="ai-face">${meta.face}</div>
        <div class="ai-blurb">${esc(meta.blurb)}</div>
        <div class="ai-count" data-type="${type}">×0</div>`;
      node.addEventListener("click", () => {
        const count = crew.filter((entry) => entry === type).length;
        if (crew.length >= 3 || count >= 3) {
          crew = crew.filter((entry) => entry !== type);
        } else {
          crew.push(type);
        }
        updateCrewUI();
      });
      container.appendChild(node);
    }
    updateCrewUI();
  }

  function ensureAiLevelPicker() {
    if (document.getElementById("ai-level")) return;
    const pickers = document.getElementById("ai-pickers");
    const label = document.createElement("label");
    label.className = "open-seats-label ai-level-label";
    label.innerHTML = `Experience level:
      <select id="ai-level">
        <option value="deck_hand">Deck Hand</option>
        <option value="buccaneer">Buccaneer</option>
        <option value="pirate_king">Pirate King</option>
      </select>
      <div class="choice-buttons" data-choice-for="ai-level" aria-label="Experience level"></div>`;
    pickers.after(label);
    label.querySelector("select").value = aiLevel;
    label.querySelector("select").addEventListener("change", (event) => {
      aiLevel = event.target.value || "deck_hand";
      syncChoiceButtons("ai-level");
    });
    buildChoiceButtons("ai-level");
    ensureOpenSeatsButtons();
  }

  function buildChoiceButtons(selectId) {
    const select = document.getElementById(selectId);
    const group = document.querySelector(`[data-choice-for="${selectId}"]`);
    if (!select || !group || group.dataset.boundChoiceButtons === "1") return;
    group.dataset.boundChoiceButtons = "1";
    group.innerHTML = "";
    [...select.options].forEach((option) => {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "choice-button";
      button.dataset.value = option.value;
      button.textContent = option.textContent;
      button.addEventListener("click", () => {
        select.value = option.value;
        select.dispatchEvent(new Event("change", { bubbles: true }));
      });
      group.appendChild(button);
    });
    syncChoiceButtons(selectId);
  }

  function syncChoiceButtons(selectId) {
    const select = document.getElementById(selectId);
    const group = document.querySelector(`[data-choice-for="${selectId}"]`);
    if (!select || !group) return;
    group.querySelectorAll(".choice-button").forEach((button) => {
      const active = button.dataset.value === select.value;
      button.classList.toggle("active", active);
      button.setAttribute("aria-pressed", String(active));
    });
  }

  function ensureOpenSeatsButtons() {
    const select = document.getElementById("open-seats");
    const label = select?.closest(".open-seats-label");
    if (!select || !label || label.querySelector('[data-choice-for="open-seats"]')) return;
    const group = document.createElement("div");
    group.className = "choice-buttons compact";
    group.dataset.choiceFor = "open-seats";
    group.setAttribute("aria-label", "Open seats for humans");
    label.appendChild(group);
    buildChoiceButtons("open-seats");
  }

  function updateCrewUI() {
    ensureOpenSeatsButtons();
    document.querySelectorAll(".ai-pick").forEach((node) => {
      const type = node.querySelector(".ai-count").dataset.type;
      const count = crew.filter((entry) => entry === type).length;
      node.querySelector(".ai-count").textContent = "×" + count;
      node.classList.toggle("picked", count > 0);
    });
    const openSeats = parseInt(document.getElementById("open-seats").value, 10) || 0;
    syncChoiceButtons("open-seats");
    syncChoiceButtons("ai-level");
    const total = 1 + crew.length + openSeats;
    const minShips = starBreachActive ? 1 : 2;
    ensureShipPicker();
    updateShipPicker();
    updateStarBreachPreyPicker();
    updateStarBreachBossPicker();
    const button = document.getElementById("btn-create-match");
    button.disabled = total < minShips || total > 4;
    button.textContent = total < minShips ? "🏴‍☠ Pick at least one foe" : `🏴‍☠ Launch Raid (${total} ships)`;
  }

  function renderExpansionToggle() {
    const toggle = document.getElementById("exp-star-command");
    if (toggle) {
      toggle.checked = starCommandActive;
      toggle.closest(".expansion-toggle")?.classList.toggle("active", starCommandActive);
    }
    const breachToggle = document.getElementById("exp-star-breach");
    if (breachToggle) {
      breachToggle.checked = starBreachActive;
      breachToggle.closest(".expansion-toggle")?.classList.toggle("active", starBreachActive);
    }
    const dockToggle = document.getElementById("exp-stardock");
    if (dockToggle) {
      dockToggle.checked = starDockActive;
      dockToggle.closest(".expansion-toggle")?.classList.toggle("active", starDockActive);
    }
    document.getElementById("star-breach-detail")?.classList.toggle("hidden", !starBreachActive);
    document.getElementById("stardock-detail")?.classList.toggle("hidden", !starDockActive);
  }

  /* "Your Ship" picker: the ship this captain flies in every raid they
     create or join. Battle-ready designs from /api/v2/ship-designs, plus the
     standard base ship. The choice persists in localStorage. */
  function ensureShipPicker() {
    if (document.getElementById("ship-pick")) return;
    const controls = document.getElementById("stardock-detail");
    if (!controls) return;
    const label = document.createElement("label");
    label.className = "open-seats-label ship-pick-label";
    label.innerHTML = `Your Ship:
      <select id="ship-pick"><option value="">Standard ship</option></select>
      <button type="button" class="btn ghost small builder-icon-btn" id="btn-my-ships" title="Build Player Ships" aria-label="Build Player Ships">🛠</button>`;
    controls.appendChild(label);
    label.querySelector("select").addEventListener("change", (event) => {
      shipDesignSelection = event.target.value || "";
      try { localStorage.setItem("ss_preferred_ship", shipDesignSelection); } catch (err) { /* private mode */ }
    });
    label.querySelector("#btn-my-ships").addEventListener("click", (event) => {
      event.preventDefault();
      window.ShipDesigner?.openPlayerDesigner();
    });
    document.addEventListener("shipdesigner-closed", () => {
      shipDesignsLoaded = false; // refresh the picker after designing
      updateShipPicker();
    });
  }

  async function updateShipPicker() {
    const select = document.getElementById("ship-pick");
    if (!select || shipDesignsLoaded) return;
    document.getElementById("stardock-detail")?.classList.toggle("hidden", !starDockActive);
    if (!starDockActive) return;
    shipDesignsLoaded = true;
    try {
      const data = await API.shipDesigns();
      const current = shipDesignSelection;
      select.innerHTML = '<option value="">Standard ship</option>';
      for (const entry of data.designs || []) {
        const option = document.createElement("option");
        option.value = entry.id;
        option.textContent = `${entry.name} (${entry.points} pts)`;
        select.appendChild(option);
      }
      if ([...select.options].some((option) => option.value === current)) {
        select.value = current;
      } else {
        select.value = "";
        shipDesignSelection = "";
      }
    } catch (err) { shipDesignsLoaded = false; /* transient; retry next refresh */ }
  }

  function ensureStarBreachPreyPicker() {
    if (document.getElementById("star-breach-prey")) return;
    const box = document.getElementById("star-breach-detail");
    if (!box) return;
    const label = document.createElement("label");
    label.className = "open-seats-label star-breach-prey-label hidden";
    label.innerHTML = `StarBreach Prey:
      <select id="star-breach-prey"></select>`;
    box.appendChild(label);
    label.querySelector("select").addEventListener("change", (event) => {
      starBreachPreySelection = event.target.value || "__host__";
    });
    ensureStarBreachRolePicker(box);
    ensureStarBreachBossPicker(box);
  }

  function ensureStarBreachRolePicker(box) {
    if (document.getElementById("star-breach-role")) return;
    const label = document.createElement("label");
    label.className = "open-seats-label star-breach-role-label hidden";
    label.innerHTML = `Your Role:
      <select id="star-breach-role">
        <option value="">Deal me one</option>
        ${STAR_BREACH_ROLES.map(([id, name]) => `<option value="${esc(id)}">${esc(name)}</option>`).join("")}
      </select>`;
    box.appendChild(label);
    label.querySelector("select").addEventListener("change", (event) => {
      starBreachRoleSelection = event.target.value || "";
    });
  }

  function ensureStarBreachBossPicker(box) {
    if (document.getElementById("star-breach-boss")) return;
    const label = document.createElement("label");
    label.className = "open-seats-label star-breach-boss-label hidden";
    label.innerHTML = `StarBreach Boss:
      <select id="star-breach-boss"><option value="">Loading boss designs...</option></select>
      <button type="button" class="btn ghost small builder-icon-btn" id="btn-my-bosses" title="Build Bosses" aria-label="Build Bosses">🛠</button>`;
    box.appendChild(label);
    label.querySelector("select").addEventListener("change", (event) => {
      starBreachBossSelection = event.target.value || "";
    });
    label.querySelector("#btn-my-bosses").addEventListener("click", (event) => {
      event.preventDefault();
      window.BossDesigner?.openPlayerDesigner();
      bossDesignsLoaded = false; // refresh the picker after designing
    });
  }

  async function updateStarBreachBossPicker() {
    const label = document.querySelector(".star-breach-boss-label");
    const select = document.getElementById("star-breach-boss");
    if (!label || !select) return;
    label.classList.toggle("hidden", !starBreachActive);
    if (!starBreachActive || bossDesignsLoaded) return;
    bossDesignsLoaded = true;
    try {
      const data = await API.bossDesigns();
      const current = starBreachBossSelection || data.default_design_id || "";
      select.innerHTML = "";
      for (const entry of data.designs || []) {
        const option = document.createElement("option");
        option.value = entry.id;
        option.textContent = entry.name.endsWith("(yours)") ? entry.name : entry.name;
        select.appendChild(option);
      }
      const options = [...select.options];
      if (options.some((option) => option.value === current)) {
        select.value = current;
        starBreachBossSelection = current;
      } else if (options.length) {
        select.value = options[0].value;
        starBreachBossSelection = options[0].value;
      } else {
        select.innerHTML = '<option value="">No public boss designs yet</option>';
        starBreachBossSelection = "";
      }
    } catch (err) { bossDesignsLoaded = false; /* transient; retry next toggle */ }
  }

  function updateStarBreachPreyPicker() {
    const label = document.querySelector(".star-breach-prey-label");
    const select = document.getElementById("star-breach-prey");
    document.querySelector(".star-breach-role-label")?.classList.toggle("hidden", !starBreachActive);
    if (!label || !select) return;
    label.classList.toggle("hidden", !starBreachActive);
    if (!starBreachActive) return;
    const options = [{ value: "__host__", text: currentUser ? `You (${currentUser.username})` : "You" }];
    crew.forEach((type, index) => {
      const meta = AI_META[type] || { name: type };
      options.push({ value: `__ai__:${index}`, text: `${meta.name} ${index + 1}` });
    });
    if (!options.some((option) => option.value === starBreachPreySelection)) {
      starBreachPreySelection = "__host__";
    }
    select.innerHTML = options.map((option) => `<option value="${esc(option.value)}">${esc(option.text)}</option>`).join("");
    select.value = starBreachPreySelection;
  }

  function maybeShowStarBreachTutorial() {
    try {
      if (localStorage.getItem("ss_star_breach_tutorial_seen") === "1") return;
      localStorage.setItem("ss_star_breach_tutorial_seen", "1");
    } catch (err) {}
    showStarBreachTutorial();
  }

  function showStarBreachTutorial() {
    const overlay = document.createElement("div");
    overlay.className = "overlay";
    overlay.innerHTML = `
      <div class="picker">
        <h3>StarBreach — Vault Breacher <span class="badge-alpha">ALPHA</span></h3>
        <p class="tutorial-alpha-note">StarBreach is still in Alpha — rules and balance may shift as it's tested. Bug reports and feedback are very welcome.</p>
        <div class="tutorial-steps">
          <div><b>1.</b> Everyone is on the same side against the StarBreacher and its Hunter-Killer fleet.</div>
          <div><b>2.</b> One captain is <b>The Prey</b>. Win by ending Round 6 inside The Fang. If The Prey is destroyed, everyone loses.</div>
          <div><b>3.</b> Each captain has a role, with its own ability:</div>
          <div class="tutorial-role"><b>Vault Runner</b> — Move distances are doubled on basic movement (not boosted further by Overdrive, and movement gives no defense bonus). When they collect a Vault, every player draws one bonus card.</div>
          <div class="tutorial-role"><b>Tank</b> — Starts with one extra Shield Charge. Proximity Jammer: when an enemy attacks an ally within 3 hexes of the Tank, the Tank steps in and takes the hit instead; attacks against the Tank roll one fewer die.</div>
          <div class="tutorial-role"><b>Engineer</b> — Draws two extra cards. Attack orders can target allies as repairs instead: 1d6, a hit restores one HP; each ship can only be repaired once per action.</div>
          <div class="tutorial-role"><b>Fighting Ace</b> — Each attack gets one extra die against fleet craft, or shifts the Boss Damage Lane roll by ±1. No Overdrive penalty on Attack-only orders.</div>
          <div><b>4.</b> The boss acts between your actions. Hitting The Prey advances its Progress Track — destroy Cannons and Engines to slow it down.</div>
        </div>
        <button class="btn gold picker-cancel" id="star-breach-tutorial-ok">Got it</button>
      </div>`;
    document.body.appendChild(overlay);
    overlay.querySelector("#star-breach-tutorial-ok").addEventListener("click", () => overlay.remove());
  }

  function maybeShowStarCommandTutorial() {
    try {
      if (localStorage.getItem("ss_star_command_tutorial_seen") === "1") return;
      localStorage.setItem("ss_star_command_tutorial_seen", "1");
    } catch (err) {}
    showStarCommandTutorial();
  }

  function showStarCommandTutorial() {
    const overlay = document.createElement("div");
    overlay.className = "overlay";
    overlay.innerHTML = `
      <div class="picker">
        <h3>StarCommand</h3>
        <div class="tutorial-steps">
          <div><b>1.</b> Each player gets three random Sunjammer Captains and chooses one before orders.</div>
          <div><b>2.</b> A Starfall event is revealed at the beginning of each round.</div>
          <div><b>3.</b> The Starfall effect stays active until cleanup, changing the board for everyone.</div>
        </div>
        <button class="btn gold picker-cancel" id="star-command-tutorial-ok">Got it</button>
      </div>`;
    document.body.appendChild(overlay);
    overlay.querySelector("#star-command-tutorial-ok").addEventListener("click", () => overlay.remove());
  }

  /* Ask a joining captain which StarBreach role they want. Resolves to a
     role id, null ("deal me one"), or undefined when the popup is closed. */
  function pickStarBreachRole(match) {
    return new Promise((resolve) => {
      const claimed = new Map();
      for (const seat of match.seat_list || []) {
        if (seat.star_breach_role) claimed.set(seat.star_breach_role, seat.display_name);
      }
      const overlay = document.createElement("div");
      overlay.className = "overlay";
      overlay.innerHTML = `
        <div class="picker">
          <h3>Choose Your Role</h3>
          <div class="tutorial-steps">
            <button class="btn gold sb-role-choice" data-role="">🎲 Deal me one</button>
            ${STAR_BREACH_ROLES.map(([id, name]) => {
              const takenBy = claimed.get(id);
              return `<button class="btn ${takenBy ? "ghost" : "gold"} sb-role-choice" data-role="${esc(id)}" ${takenBy ? "disabled" : ""}>
                ${esc(name)}${takenBy ? ` — claimed by ${esc(takenBy)}` : ""}</button>`;
            }).join("")}
          </div>
          <button class="btn ghost picker-cancel" id="sb-role-cancel">Never mind</button>
        </div>`;
      document.body.appendChild(overlay);
      overlay.querySelectorAll(".sb-role-choice").forEach((button) => {
        button.addEventListener("click", () => {
          overlay.remove();
          resolve(button.dataset.role || null);
        });
      });
      overlay.querySelector("#sb-role-cancel").addEventListener("click", () => {
        overlay.remove();
        resolve(undefined);
      });
    });
  }

  function renderMatches(containerId, matches, joinable) {
    const container = document.getElementById(containerId);
    container.innerHTML = "";
    const visibleMatches = joinable
      ? (matches || []).filter((match) => (match.seat_list || []).length < match.seats)
      : (matches || []);
    if (!visibleMatches.length) {
      container.innerHTML = `<div class="empty-note">${joinable ? "No open raids — start yer own." : "No battles yet."}</div>`;
      return;
    }
    for (const match of visibleMatches) {
      const row = document.createElement("div");
      const yourTurn = match.turn && match.turn.your_turn;
      row.className = "match-row" + (match.status === "complete" ? " complete" : "") + (yourTurn ? " your-turn" : "");
      const seatsTaken = match.seat_list.length;
      const roleName = (id) => (STAR_BREACH_ROLES.find(([roleId]) => roleId === id) || [])[1];
      const names = match.seat_list.map((seat) => seat.display_name
        + (seat.star_breach_role && roleName(seat.star_breach_role) ? ` (${roleName(seat.star_breach_role)})` : "")).join(", ");
      let turnBadge = "";
      if (match.status === "active" && match.turn) {
        turnBadge = yourTurn
          ? `<span class="badge-turn">⚔ YOUR TURN</span>`
          : match.turn.you_dead
            ? `<span class="badge-wait">☠ sunk — battle rages on</span>`
            : `<span class="badge-wait">⏳ waiting on rivals · round ${match.turn.round_number}</span>`;
      }
      // Rivals who struck their colors (forfeited), on active or finished battles.
      const fled = ((match.turn && match.turn.forfeited) || []).map((pid) => {
        const seat = match.seat_list.find((s) => s.player_id === pid);
        return seat ? seat.display_name : pid;
      });
      if (fled.length) {
        turnBadge += ` <span class="badge-fled">🏳 ${esc(fled.join(", "))} abandoned</span>`;
      }
      row.innerHTML = `<div>
          <div class="match-name">${esc(match.name)} ${expansionBadges(match)} ${turnBadge}</div>
          <div class="match-meta">${esc(names)} · ${seatsTaken}/${match.seats} ships · ${match.status}${match.turn && match.turn.round_number ? ` · round ${match.turn.round_number}` : ""}</div>
        </div>`;
      const actions = document.createElement("div");
      if (joinable) {
        const join = document.createElement("button");
        join.className = "btn gold small";
        join.textContent = "⚔ Join";
        join.addEventListener("click", async () => {
          let role = null;
          if ((match.active_expansions || []).includes("star_breach")) {
            role = await pickStarBreachRole(match);
            if (role === undefined) return; // cancelled
          }
          try {
            const joinBody = {};
            if (role) joinBody.star_breach_role = role;
            if (shipDesignSelection) joinBody.ship_design_id = shipDesignSelection;
            const result = await API.joinMatch(match.id, Object.keys(joinBody).length ? joinBody : undefined);
            if (result.game_id) { leave(); Game.enter(result.game_id); }
            else refresh();
          } catch (error) { App.toast(error.message); }
        });
        actions.appendChild(join);
      } else if (match.status === "active" && match.game_id) {
        const resume = document.createElement("button");
        resume.className = "btn gold small";
        resume.textContent = match.turn && match.turn.your_turn ? "⚔ Give Orders" : "▶ Resume";
        resume.addEventListener("click", () => { leave(); Game.enter(match.game_id); });
        actions.appendChild(resume);
        const strike = document.createElement("button");
        strike.className = "btn ghost small";
        strike.textContent = "🏳";
        strike.title = "Abandon this battle (forfeit)";
        strike.addEventListener("click", async () => {
          if (!confirm("Strike yer colors and abandon this battle? Yer ship forfeits and the fight sails on without you.")) return;
          try { await API.abandonMatch(match.id); refresh(); } catch (error) { App.toast(error.message); }
        });
        actions.appendChild(strike);
      } else if (match.status === "open") {
        const start = document.createElement("button");
        start.className = "btn crimson small";
        start.textContent = "Start now";
        start.addEventListener("click", async () => {
          try {
            const result = await API.startMatch(match.id);
            if (result.game_id) { leave(); Game.enter(result.game_id); }
          } catch (error) { App.toast(error.message); }
        });
        const abandon = document.createElement("button");
        abandon.className = "btn ghost small";
        abandon.textContent = "✕";
        abandon.title = "Disband";
        abandon.addEventListener("click", async () => {
          try { await API.leaveMatch(match.id); refresh(); } catch (error) { App.toast(error.message); }
        });
        actions.appendChild(start);
        actions.appendChild(abandon);
      } else if (match.status === "complete" && match.game_id) {
        const review = document.createElement("button");
        review.className = "btn ghost small";
        review.textContent = "Review";
        review.addEventListener("click", () => { leave(); Game.enter(match.game_id); });
        actions.appendChild(review);
        const dismiss = document.createElement("button");
        dismiss.className = "btn ghost small";
        dismiss.textContent = "✕";
        dismiss.title = "Remove from your battles list";
        dismiss.addEventListener("click", async () => {
          try { await API.abandonMatch(match.id); refresh(); } catch (error) { App.toast(error.message); }
        });
        actions.appendChild(dismiss);
      }
      row.appendChild(actions);
      container.appendChild(row);
    }
  }

  function renderMaintenance(message) {
    let banner = document.getElementById("maintenance-banner");
    if (message && !banner) {
      banner = document.createElement("div");
      banner.id = "maintenance-banner";
      banner.className = "maintenance-banner";
      document.querySelector("#screen-lobby .lobby-grid").before(banner);
    }
    if (banner) {
      if (!message) { banner.remove(); return; }
      banner.innerHTML = `🚧 <b>Under construction:</b> ${esc(message)} — battles are paused until the admiral reopens the seas.`;
    }
  }

  function renderActivePlayers(players) {
    const container = document.getElementById("active-players");
    container.innerHTML = "";
    if (!players.length) {
      container.innerHTML = '<div class="empty-note">No other captains on deck right now.</div>';
      return;
    }
    for (const player of players) {
      const row = document.createElement("div");
      row.className = "player-row";
      row.innerHTML = `<span class="player-dot">●</span>
        <span class="player-name">${esc(player.display_name || player.username)}</span>
        ${feedbackBadge(player.feedback_count)}
        <span class="player-record">${player.wins}W / ${player.losses}L</span>`;
      const button = document.createElement("button");
      button.className = "btn crimson small";
      button.textContent = "⚔ Challenge";
      button.addEventListener("click", async () => {
        try {
          await API.challenge(player.username, activeExpansions());
          App.toast(`Gauntlet thrown at ${player.display_name || player.username}!`, true);
          refresh();
        } catch (error) { App.toast(error.message); }
      });
      row.appendChild(button);
      container.appendChild(row);
    }
  }

  function renderChallenges(challenges) {
    const container = document.getElementById("challenge-banners");
    container.innerHTML = "";
    for (const challenge of challenges.incoming || []) {
      const banner = document.createElement("div");
      banner.className = "challenge-banner";
      banner.innerHTML = `<div>⚔ <b>${esc(challenge.from_username)}</b> challenges you to a duel!</div>`;
      const actions = document.createElement("div");
      actions.className = "challenge-actions";
      const accept = document.createElement("button");
      accept.className = "btn gold small";
      accept.textContent = "Accept";
      accept.addEventListener("click", async () => {
        try {
          const result = await API.respondChallenge(challenge.id, true);
          if (result.game_id) { leave(); Game.enter(result.game_id); }
        } catch (error) { App.toast(error.message); refresh(); }
      });
      const decline = document.createElement("button");
      decline.className = "btn ghost small";
      decline.textContent = "Decline";
      decline.addEventListener("click", async () => {
        try { await API.respondChallenge(challenge.id, false); refresh(); } catch (error) { App.toast(error.message); }
      });
      actions.appendChild(accept);
      actions.appendChild(decline);
      banner.appendChild(actions);
      container.appendChild(banner);
    }
    for (const challenge of challenges.outgoing || []) {
      if (challenge.status === "accepted" && challenge.game_id) {
        // Rival accepted while we waited — acknowledge and jump in, once.
        if (autoEntered.has(challenge.game_id)) continue;
        autoEntered.add(challenge.game_id);
        API.cancelChallenge(challenge.id).catch(() => {});
        leave();
        Game.enter(challenge.game_id);
        return;
      }
      if (challenge.status !== "pending") continue;
      const banner = document.createElement("div");
      banner.className = "challenge-banner outgoing";
      banner.innerHTML = `<div><span class="spinner"></span> Waiting on <b>${esc(challenge.to_username)}</b>…</div>`;
      const cancel = document.createElement("button");
      cancel.className = "btn ghost small";
      cancel.textContent = "Withdraw";
      cancel.addEventListener("click", async () => {
        try { await API.cancelChallenge(challenge.id); refresh(); } catch (error) { App.toast(error.message); }
      });
      banner.appendChild(cancel);
      container.appendChild(banner);
    }
  }

  function formatDate(iso) {
    const [year, month, day] = String(iso || "").slice(0, 10).split("-");
    return year && month && day ? `${month}-${day}-${year}` : "";
  }

  function renderProfile(user) {
    const total = user.games_played || 0;
    const rate = total ? Math.round((user.wins / total) * 100) : 0;
    const shownName = user.display_name || user.username;
    const flaggedNote = user.name_flagged
      ? `<br><span class="name-flagged-note">⚠ Yer name be hidden from leaderboards and ye won't face other captains until ye change it.</span>`
      : "";
    document.getElementById("profile-card").innerHTML = `
      <b>☠ ${esc(shownName)}</b>${shownName !== user.username ? ` <i class="profile-username">(${esc(user.username)})</i>` : ""}${flaggedNote}<br>
      ${feedbackBadge(user.feedback_count)}<br>
      Victories: <b>${user.wins}</b> · Defeats: <b>${user.losses}</b> · Draws: <b>${user.draws}</b><br>
      Battles fought: <b>${total}</b> · Win rate: <b>${rate}%</b><br>
      Sailing since: <b>${formatDate(user.created_at)}</b>`;
  }

  function ensureTitleList() {
    let node = document.getElementById("title-holders");
    if (node) return node;
    const heading = [...document.querySelectorAll(".lobby-side .panel-title")]
      .find((title) => title.textContent.includes("Most Feared"));
    node = document.createElement("div");
    node.id = "title-holders";
    node.className = "title-holders";
    if (heading) heading.before(node);
    return node;
  }

  function renderTitleList(titles) {
    const node = ensureTitleList();
    const rows = titles || [];
    if (!rows.length) {
      node.innerHTML = `<div class="title-row empty-note">No crowned captains yet.</div>`;
      return;
    }
    node.innerHTML = rows.map((entry) => `
      <div class="title-row">
        <span class="title-name">${esc(entry.title)}</span>
        <span>${esc(entry.display_name || entry.username)} ${feedbackBadge(entry.feedback_count)}</span>
        <b>${entry.points}</b>
      </div>`).join("");
  }

  function renderLeaderboardBundle(payload) {
    leaderboardCycle = payload && payload.boards
      ? payload.boards.filter((board) => board && (board.key === "humans" || board.key === "ai"))
      : null;
    renderInfamy(payload && payload.infamy);
    if (!leaderboardCycle || !leaderboardCycle.length) {
      renderLeaderboard({ key: "legacy", entries: payload && payload.leaderboard });
      paintLeaderboardExtras("Leaderboard");
      return;
    }
    if (leaderboardIndex >= leaderboardCycle.length) leaderboardIndex = 0;
    renderLeaderboardPage(!leaderboardRendered);
    leaderboardRendered = true;
  }

  function advanceLeaderboard() {
    if (!leaderboardCycle || leaderboardCycle.length < 2) return;
    leaderboardIndex = (leaderboardIndex + 1) % leaderboardCycle.length;
    renderLeaderboardPage(true);
  }

  function renderLeaderboardPage(resetTimer) {
    const board = leaderboardCycle[leaderboardIndex];
    renderLeaderboard(board);
    paintLeaderboardExtras(board.label, resetTimer);
  }

  function paintLeaderboardExtras(title, resetTimer = false) {
    const heading = [...document.querySelectorAll(".lobby-side .panel-title")]
      .find((node) => node.textContent.includes("Most Feared") || node.textContent.includes("Leaderboard"));
    if (heading) heading.textContent = title;
    let bar = document.getElementById("leaderboard-timer");
    if (!bar) {
      bar = document.createElement("div");
      bar.id = "leaderboard-timer";
      bar.className = "leaderboard-timer";
      document.getElementById("leaderboard").after(bar);
    }
    if (resetTimer || !bar.firstChild) bar.innerHTML = `<span></span>`;
  }

  function renderInfamy(infamy) {
    let node = document.getElementById("davey-locker");
    if (!node) {
      node = document.createElement("div");
      node.id = "davey-locker";
      node.className = "title-holders davey-locker";
      const timer = document.getElementById("leaderboard-timer");
      (timer || document.getElementById("leaderboard")).after(node);
    }
    node.innerHTML = infamy
      ? `<div class="title-row"><span class="title-name">Davey Jones Locker</span><span>${esc(infamy.display_name || infamy.username)}</span><b>${infamy.ship_losses}</b></div>`
      : `<div class="title-row empty-note">Davey Jones Locker is empty.</div>`;
  }

  function renderLeaderboard(board) {
    const entries = (board && board.entries) || [];
    const table = document.getElementById("leaderboard");
    if (board && board.key === "ai") {
      table.innerHTML = "<tr><th>#</th><th>Name</th><th>Score</th><th>Games Played</th><th>Avg Score</th></tr>" +
        entries.map((entry, index) => `
        <tr><td>${index === 0 ? "#" + 1 : index + 1}</td><td>${esc(entry.display_name || entry.username)} ${feedbackBadge(entry.feedback_count)}</td>
        <td>${entry.score}</td><td>${entry.games_played}</td><td>${Number(entry.average_score || 0).toFixed(2)}</td></tr>`).join("");
      return;
    }
    table.innerHTML = "<tr><th>#</th><th>Captain</th><th>W</th><th>L</th><th>Battles</th></tr>" +
      (entries || []).map((entry, index) => `
        <tr><td>${index === 0 ? "👑" : index + 1}</td><td>${esc(entry.display_name || entry.username)} ${feedbackBadge(entry.feedback_count)}</td>
        <td>${entry.wins}</td><td>${entry.losses}</td><td>${entry.games_played}</td></tr>`).join("");
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

  function currentFeedbackPayload(context, rating) {
    return {
      rating,
      liked: document.getElementById("feedback-liked").value.trim(),
      disliked: document.getElementById("feedback-disliked").value.trim(),
      thoughts: document.getElementById("feedback-thoughts").value.trim(),
      matchId: context.matchId || "",
      gameId: context.gameId || "",
      isBugReport: !!document.getElementById("feedback-bug-report")?.checked,
      gameLog: "",
      screenshotDataUrl: "",
    };
  }

  function feedbackScreenshotStyles() {
    const chunks = [];
    for (const sheet of document.styleSheets || []) {
      try {
        for (const rule of sheet.cssRules || []) chunks.push(rule.cssText);
      } catch (error) {
        // Cross-origin font sheets can refuse cssRules; the local app CSS is enough.
      }
    }
    chunks.push(`
      html,body{margin:0;width:100%;height:100%;overflow:hidden;background:#070b16;color:#e8e0cc}
      *{box-sizing:border-box}
    `);
    return chunks.join("\n");
  }

  function replaceCanvasesForScreenshot(cloneRoot) {
    const cloneCanvases = [...cloneRoot.querySelectorAll("canvas")];
    const liveCanvases = [...document.querySelectorAll("canvas")];
    cloneCanvases.forEach((cloneCanvas, index) => {
      const liveCanvas = cloneCanvas.id
        ? document.getElementById(cloneCanvas.id)
        : liveCanvases[index];
      if (!liveCanvas || !liveCanvas.toDataURL) return;
      try {
        const rect = liveCanvas.getBoundingClientRect();
        const image = document.createElement("img");
        image.src = liveCanvas.toDataURL("image/png");
        image.id = cloneCanvas.id || "";
        image.className = cloneCanvas.className || "";
        image.setAttribute("style", cloneCanvas.getAttribute("style") || "");
        image.style.width = `${Math.max(1, Math.round(rect.width || liveCanvas.width || 1))}px`;
        image.style.height = `${Math.max(1, Math.round(rect.height || liveCanvas.height || 1))}px`;
        cloneCanvas.replaceWith(image);
      } catch (error) {
        cloneCanvas.remove();
      }
    });
  }

  async function captureAppScreenshot() {
    const overlay = document.getElementById("feedback-overlay");
    const wasHidden = overlay?.classList.contains("hidden");
    overlay?.classList.add("hidden");
    await new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve)));
    try {
      const rawWidth = Math.max(1, Math.round(window.innerWidth || document.documentElement.clientWidth || 1));
      const rawHeight = Math.max(1, Math.round(window.innerHeight || document.documentElement.clientHeight || 1));
      const scale = Math.min(1, 1200 / Math.max(rawWidth, rawHeight));
      const width = Math.max(1, Math.round(rawWidth * scale));
      const height = Math.max(1, Math.round(rawHeight * scale));
      const canvas = document.createElement("canvas");
      canvas.width = width;
      canvas.height = height;
      const ctx = canvas.getContext("2d");
      ctx.setTransform(scale, 0, 0, scale, 0, 0);
      ctx.fillStyle = "#060a14";
      ctx.fillRect(0, 0, rawWidth, rawHeight);
      const bodyClone = document.body.cloneNode(true);
      bodyClone.querySelector("#feedback-overlay")?.remove();
      replaceCanvasesForScreenshot(bodyClone);
      const cssText = feedbackScreenshotStyles();
      const cssCdata = cssText.replace(/\]\]>/g, "]]]]><![CDATA[>");
      const html = new XMLSerializer().serializeToString(bodyClone);
      const svgText = `<svg xmlns="http://www.w3.org/2000/svg" width="${rawWidth}" height="${rawHeight}" viewBox="0 0 ${rawWidth} ${rawHeight}">
        <foreignObject x="0" y="0" width="${rawWidth}" height="${rawHeight}">
          <div xmlns="http://www.w3.org/1999/xhtml" style="width:${rawWidth}px;height:${rawHeight}px;overflow:hidden;background:#070b16;">
            <style><![CDATA[${cssCdata}]]></style>
            ${html}
          </div>
        </foreignObject>
      </svg>`;
      const blob = new Blob([svgText], { type: "image/svg+xml;charset=utf-8" });
      const url = URL.createObjectURL(blob);
      try {
        const image = await new Promise((resolve, reject) => {
          const img = new Image();
          img.onload = () => resolve(img);
          img.onerror = reject;
          img.src = url;
        });
        ctx.drawImage(image, 0, 0, rawWidth, rawHeight);
      } finally {
        URL.revokeObjectURL(url);
      }
      return canvas.toDataURL("image/png");
    } catch (error) {
      console.warn("[StarShot feedback screenshot]", error);
      return "";
    } finally {
      if (!wasHidden) overlay?.classList.remove("hidden");
    }
  }

  function feedbackPostText(payload) {
    const lines = [
      "StarShot Feedback and Bugs",
      "",
      `Rating: ${payload.rating}/5`,
      `Bug report: ${payload.isBugReport ? "yes" : "no"}`,
    ];
    if (payload.matchId) lines.push(`Match: ${payload.matchId}`);
    if (payload.gameId) lines.push(`Game: ${payload.gameId}`);
    lines.push(
      "",
      "What I liked:",
      payload.liked || "(blank)",
      "",
      "What I didn't like:",
      payload.disliked || "(blank)",
      "",
      "General thoughts:",
      payload.thoughts || "(blank)",
    );
    if (payload.gameLog) {
      lines.push(
        "",
        "Included Game Log:",
        "```",
        payload.gameLog,
        "```",
      );
    }
    return lines.join("\n");
  }

  /* Display-name modal. Forced mode (admiral banned the name) can't be
     dismissed until a new name is saved. */
  let nameModalOpen = false;
  function openNameModal(forced = false) {
    if (nameModalOpen) return;
    nameModalOpen = true;
    const overlay = document.createElement("div");
    overlay.className = "overlay";
    overlay.innerHTML = `
      <div class="picker name-modal">
        <h3>${forced ? "⚓ The Admiral Demands a New Name" : "✏ Change Yer Display Name"}</h3>
        ${forced
          ? `<p class="feedback-copy">Yer current name has been struck from the registry. Pick a new one to keep sailing.</p>`
          : `<p class="feedback-copy">This be the name other captains see. Yer sign-in name stays the same.</p>`}
        <form id="name-form" class="feedback-form">
          <label>Display name
            <input id="name-input" type="text" minlength="3" maxlength="24" required
              value="${esc((currentUser && (currentUser.display_name || currentUser.username)) || "")}">
          </label>
          <div class="feedback-actions">
            <button type="button" class="btn ghost" id="name-random">🎲 Random</button>
            ${forced ? "" : `<button type="button" class="btn ghost" id="name-cancel">Cancel</button>`}
            <button type="submit" class="btn gold">Hoist the Name</button>
          </div>
          <div id="name-status" class="auth-error"></div>
        </form>
      </div>`;
    document.body.appendChild(overlay);
    const close = () => { overlay.remove(); nameModalOpen = false; };
    if (!forced) {
      overlay.querySelector("#name-cancel").addEventListener("click", close);
      overlay.addEventListener("click", (event) => { if (event.target === overlay) close(); });
    }
    overlay.querySelector("#name-random").addEventListener("click", async () => {
      try {
        const result = await API.randomName();
        overlay.querySelector("#name-input").value = result.name || "";
      } catch (error) { overlay.querySelector("#name-status").textContent = error.message; }
    });
    overlay.querySelector("#name-form").addEventListener("submit", async (event) => {
      event.preventDefault();
      const status = overlay.querySelector("#name-status");
      status.textContent = "";
      try {
        const result = await API.setDisplayName(overlay.querySelector("#name-input").value.trim());
        currentUser = result.user;
        close();
        if (result.warning) {
          App.toast(result.warning);
        } else {
          App.toast(`Henceforth ye sail as ${result.user.display_name}!`, true);
        }
        refresh().catch(() => {});
      } catch (error) { status.textContent = error.message; }
    });
  }

  function openFeedback(context = {}) {
    let overlay = document.getElementById("feedback-overlay");
    if (!overlay) {
      overlay = document.createElement("div");
      overlay.id = "feedback-overlay";
      overlay.className = "overlay hidden";
      document.body.appendChild(overlay);
    }
    overlay.innerHTML = "";
    overlay.classList.remove("hidden");
    const box = document.createElement("div");
    box.className = "picker feedback-modal";
    box.innerHTML = `
      <h3>Feedback and Bugs</h3>
      <p class="feedback-copy">We're in playtest, and would appreciate your feedback immensely. You'll even get a badge for sharing your thoughts!</p>
      <form id="feedback-form" class="feedback-form">
        <label>Rating
          <div class="rating-stars" role="radiogroup" aria-label="Rating">
            ${[1, 2, 3, 4, 5].map((n) => `<button type="button" class="star-choice" data-rating="${n}" aria-label="${n} star${n === 1 ? "" : "s"}">★</button>`).join("")}
          </div>
        </label>
        <label>What I liked
          <textarea id="feedback-liked" rows="4" maxlength="2000"></textarea>
        </label>
        <label>What I didn't like
          <textarea id="feedback-disliked" rows="4" maxlength="2000"></textarea>
        </label>
        <label>General Thoughts
          <textarea id="feedback-thoughts" rows="5" maxlength="3000"></textarea>
        </label>
        ${context.gameId ? `
        <label class="feedback-bug-report">
          <input id="feedback-bug-report" type="checkbox">
          <span>report a bug - include the game log and board screenshot</span>
        </label>` : ""}
        <div class="feedback-actions">
          <button type="button" class="btn ghost" id="feedback-copy-reddit">Copy to clipboard for /r/StarShotBoardgame posting</button>
          <button type="button" class="btn ghost" id="feedback-cancel">Cancel</button>
          <button type="submit" class="btn gold">Submit Feedback and Bugs</button>
        </div>
        <div id="feedback-status" class="auth-error"></div>
      </form>`;
    overlay.appendChild(box);
    let rating = 5;
    const paintStars = () => {
      box.querySelectorAll(".star-choice").forEach((button) => {
        button.classList.toggle("selected", Number(button.dataset.rating) <= rating);
      });
    };
    box.querySelectorAll(".star-choice").forEach((button) => {
      button.addEventListener("click", () => {
        rating = Number(button.dataset.rating) || 5;
        paintStars();
      });
    });
    paintStars();
    document.getElementById("feedback-cancel").addEventListener("click", () => overlay.classList.add("hidden"));
    overlay.onclick = (event) => {
      if (event.target === overlay) overlay.classList.add("hidden");
    };
    document.getElementById("feedback-copy-reddit").addEventListener("click", async () => {
      const status = document.getElementById("feedback-status");
      const button = document.getElementById("feedback-copy-reddit");
      const oldText = button.textContent;
      status.textContent = "";
      button.disabled = true;
      button.textContent = "Copying...";
      try {
        const payload = currentFeedbackPayload(context, rating);
        if (payload.gameId) {
          const result = await API.debugLog(payload.gameId);
          payload.gameLog = result.log || "";
        }
        await copyText(feedbackPostText(payload));
        status.textContent = "Copied for posting to /r/StarShotBoardgame.";
        App.toast("Feedback copied to clipboard.", true);
      } catch (error) {
        status.textContent = error.message || "Could not copy feedback.";
      } finally {
        button.disabled = false;
        button.textContent = oldText;
      }
    });
    document.getElementById("feedback-form").addEventListener("submit", async (event) => {
      event.preventDefault();
      const status = document.getElementById("feedback-status");
      status.textContent = "";
      try {
        const payload = currentFeedbackPayload(context, rating);
        if (payload.isBugReport) {
          status.textContent = "Capturing app screenshot...";
          payload.screenshotDataUrl = await captureAppScreenshot();
          if (!payload.screenshotDataUrl) {
            status.textContent = "Screenshot capture failed; sending bug report with the game log only.";
          }
        }
        const result = await API.submitFeedback({
          rating: payload.rating,
          liked: payload.liked,
          disliked: payload.disliked,
          thoughts: payload.thoughts,
          match_id: payload.matchId || null,
          game_id: payload.gameId || null,
          is_bug_report: payload.isBugReport,
          screenshot_data_url: payload.screenshotDataUrl || "",
        });
        overlay.classList.add("hidden");
        App.toast(`Feedback sent - badge count: ${result.feedback_count}`, true);
        refresh().catch(() => {});
      } catch (error) {
        status.textContent = error.message;
      }
    });
  }

  document.addEventListener("DOMContentLoaded", () => {
    document.getElementById("btn-quickmatch").addEventListener("click", async () => {
      try {
        const result = await API.queue("join");
        if (result.matched) { leave(); Game.enter(result.game_id); }
        else refresh();
      } catch (error) { App.toast(error.message); }
    });
    document.getElementById("btn-queue-leave").addEventListener("click", async () => {
      try { await API.queue("leave"); refresh(); } catch (error) { App.toast(error.message); }
    });
    ensureOpenSeatsButtons();
    document.getElementById("open-seats").addEventListener("change", updateCrewUI);
    const expToggle = document.getElementById("exp-star-command");
    if (expToggle) {
      expToggle.addEventListener("change", (event) => {
        starCommandActive = !!event.target.checked;
        renderExpansionToggle();
        if (starCommandActive) maybeShowStarCommandTutorial();
      });
    }
    const breachToggle = document.getElementById("exp-star-breach");
    if (breachToggle) {
      breachToggle.addEventListener("change", (event) => {
        starBreachActive = !!event.target.checked;
        renderExpansionToggle();
        updateCrewUI();
        if (starBreachActive) maybeShowStarBreachTutorial();
      });
    }
    const dockToggle = document.getElementById("exp-stardock");
    if (dockToggle) {
      dockToggle.addEventListener("change", (event) => {
        starDockActive = !!event.target.checked;
        renderExpansionToggle();
        updateCrewUI();
      });
    }
    document.getElementById("btn-create-match").addEventListener("click", async () => {
      const openSeats = parseInt(document.getElementById("open-seats").value, 10) || 0;
      try {
        const result = await API.createMatch({
          ai_types: crew,
          ai_level: aiLevel,
          open_seats: openSeats,
          active_expansions: activeExpansions(),
          star_breach_prey_player_id: starBreachActive ? starBreachPreySelection : null,
          star_breach_role: starBreachActive ? (starBreachRoleSelection || null) : null,
          star_breach_boss_design_id: starBreachActive ? (starBreachBossSelection || null) : null,
          ship_design_id: starDockActive ? (shipDesignSelection || null) : null,
        });
        crew = [];
        updateCrewUI();
        if (result.game_id) { leave(); Game.enter(result.game_id); }
        else { App.toast("Raid posted — waiting for captains to join.", true); refresh(); }
      } catch (error) { App.toast(error.message); }
    });
    document.getElementById("btn-tutorial").addEventListener("click", () => Tutorial.start());
    document.getElementById("btn-feedback-lobby").addEventListener("click", () => openFeedback());
    const userMenu = document.getElementById("lobby-user-menu");
    const userPopup = document.getElementById("lobby-user-popup");
    userMenu?.addEventListener("click", (event) => {
      event.stopPropagation();
      const open = userPopup.classList.toggle("hidden") === false;
      userMenu.setAttribute("aria-expanded", String(open));
    });
    document.addEventListener("click", (event) => {
      if (!userPopup || userPopup.classList.contains("hidden")) return;
      if (event.target.closest("#lobby-user-popup") || event.target.closest("#lobby-user-menu")) return;
      userPopup.classList.add("hidden");
      userMenu?.setAttribute("aria-expanded", "false");
    });
    document.getElementById("btn-change-name")?.addEventListener("click", () => {
      userPopup?.classList.add("hidden");
      userMenu?.setAttribute("aria-expanded", "false");
      openNameModal(false);
    });
    document.getElementById("btn-logout").addEventListener("click", async () => {
      try { await API.logout(); } catch (err) {}
      userPopup?.classList.add("hidden");
      userMenu?.setAttribute("aria-expanded", "false");
      leave();
      App.showScreen("auth");
    });
  });

  window.Feedback = { open: openFeedback };
  window.Lobby = { enter, leave, showStarBreachTutorial, showStarCommandTutorial };
})();
