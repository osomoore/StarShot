/* Lobby: quick match queue, crew builder, open raids, leaderboard, profile. */
(function () {
  const AI_META = {
    bauble_runner: { face: "💰", name: "Salvage Capt. Morrigan", blurb: "chases the loot" },
    hunter_killer: { face: "🗡", name: "Corsair Blackvane", blurb: "marks one prey" },
    blaster: { face: "💥", name: "Gunner Redbeard", blurb: "shoots what's near" },
  };

  Object.keys(AI_META).forEach((key) => delete AI_META[key]);
  Object.assign(AI_META, {
    bauble_runner: { face: "SR", name: "Salvage Captain", blurb: "chases the loot" },
    hunter_killer: { face: "CS", name: "Corsair", blurb: "marks one prey" },
    blaster: { face: "GN", name: "Gunner", blurb: "shoots what's near" },
  });

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
  let starCommandActive = false;
  let starBreachActive = false;
  const activeExpansions = () => [
    ...(starCommandActive ? ["star_command"] : []),
    ...(starBreachActive ? ["star_breach"] : []),
  ];
  const autoEntered = new Set();  // pairings/challenges already jumped into
  const esc = (value) => Cards.escapeHtml(value);
  const feedbackBadge = (count) => Number(count || 0) > 0
    ? `<span class="feedback-badge" title="Feedback shared ${Number(count)} time${Number(count) === 1 ? "" : "s"}">★ ${Number(count)}</span>`
    : "";

  async function enter() {
    App.showScreen("lobby");
    leaderboardRendered = false;
    renderAiPickers();
    renderExpansionToggle();
    await refresh();
    if (pollTimer) clearInterval(pollTimer);
    pollTimer = setInterval(refresh, 3000);
    if (leaderboardTimer) clearInterval(leaderboardTimer);
    leaderboardTimer = setInterval(advanceLeaderboard, 10000);
    Tutorial.offerIfNew();
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
      document.getElementById("lobby-user").textContent = "☠ " + me.user.username;
      document.getElementById("lobby-admin-link").classList.toggle("hidden", !me.is_admin);
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
      node.innerHTML = `<div class="ai-face">${meta.face}</div>
        <div class="ai-name">${esc(meta.name)}<br><i>${esc(meta.blurb)}</i></div>
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
    label.innerHTML = `AI smartness:
      <select id="ai-level">
        <option value="deck_hand">Deck Hand</option>
        <option value="buccaneer">Buccaneer</option>
        <option value="pirate_king">Pirate King</option>
      </select>`;
    pickers.after(label);
    label.querySelector("select").value = aiLevel;
    label.querySelector("select").addEventListener("change", (event) => {
      aiLevel = event.target.value || "deck_hand";
    });
  }

  function updateCrewUI() {
    document.querySelectorAll(".ai-pick").forEach((node) => {
      const type = node.querySelector(".ai-count").dataset.type;
      const count = crew.filter((entry) => entry === type).length;
      node.querySelector(".ai-count").textContent = "×" + count;
      node.classList.toggle("picked", count > 0);
    });
    const openSeats = parseInt(document.getElementById("open-seats").value, 10) || 0;
    const total = 1 + crew.length + openSeats;
    const minShips = starBreachActive ? 1 : 2;
    updateStarBreachPreyPicker();
    const button = document.getElementById("btn-create-match");
    button.disabled = total < minShips || total > 4;
    button.textContent = total < minShips ? "🏴‍☠ Pick at least one foe" : `🏴‍☠ Launch Raid (${total} ships)`;
  }

  function renderExpansionToggle() {
    const toggle = document.getElementById("exp-star-command");
    if (toggle) toggle.checked = starCommandActive;
    const breachToggle = document.getElementById("exp-star-breach");
    if (breachToggle) breachToggle.checked = starBreachActive;
  }

  function ensureStarBreachPreyPicker() {
    if (document.getElementById("star-breach-prey")) return;
    const box = document.querySelector(".expansion-box");
    if (!box) return;
    const label = document.createElement("label");
    label.className = "open-seats-label star-breach-prey-label hidden";
    label.innerHTML = `StarBreach Prey:
      <select id="star-breach-prey"></select>`;
    box.appendChild(label);
    label.querySelector("select").addEventListener("change", (event) => {
      starBreachPreySelection = event.target.value || "__host__";
    });
  }

  function updateStarBreachPreyPicker() {
    const label = document.querySelector(".star-breach-prey-label");
    const select = document.getElementById("star-breach-prey");
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
    const overlay = document.createElement("div");
    overlay.className = "overlay";
    overlay.innerHTML = `
      <div class="picker">
        <h3>StarBreach — Bauble Breacher</h3>
        <div class="tutorial-steps">
          <div><b>1.</b> Everyone is on the same side against the StarBreacher and its Hunter-Killer fleet.</div>
          <div><b>2.</b> One captain is <b>The Prey</b>. Win by ending Round 6 inside The Fang. If The Prey is destroyed, everyone loses.</div>
          <div><b>3.</b> Each captain has a role: Treasure Hunter, Tank, Engineer, or Fighting Ace.</div>
          <div><b>4.</b> The boss acts between your actions. Hitting The Prey advances its Progress Track — destroy Firing Computers and Fuel Tanks to slow it down.</div>
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
      const names = match.seat_list.map((seat) => seat.display_name).join(", ");
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
          <div class="match-name">${esc(match.name)} ${turnBadge}</div>
          <div class="match-meta">${esc(names)} · ${seatsTaken}/${match.seats} ships · ${match.status}${match.turn && match.turn.round_number ? ` · round ${match.turn.round_number}` : ""}</div>
        </div>`;
      const actions = document.createElement("div");
      if (joinable) {
        const join = document.createElement("button");
        join.className = "btn gold small";
        join.textContent = "⚔ Join";
        join.addEventListener("click", async () => {
          try {
            const result = await API.joinMatch(match.id);
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
        <span class="player-name">${esc(player.username)}</span>
        ${feedbackBadge(player.feedback_count)}
        <span class="player-record">${player.wins}W / ${player.losses}L</span>`;
      const button = document.createElement("button");
      button.className = "btn crimson small";
      button.textContent = "⚔ Challenge";
      button.addEventListener("click", async () => {
        try {
          await API.challenge(player.username, activeExpansions());
          App.toast(`Gauntlet thrown at ${player.username}!`, true);
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
    document.getElementById("profile-card").innerHTML = `
      <b>☠ ${esc(user.username)}</b><br>
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
        <span>${esc(entry.username)} ${feedbackBadge(entry.feedback_count)}</span>
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
      paintLeaderboardExtras("Most Feared Captains");
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
    paintLeaderboardExtras(`${board.label} Leaderboard`, resetTimer);
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
      ? `<div class="title-row"><span class="title-name">Davey Jones Locker</span><span>${esc(infamy.username)}</span><b>${infamy.ship_losses}</b></div>`
      : `<div class="title-row empty-note">Davey Jones Locker is empty.</div>`;
  }

  function renderLeaderboard(board) {
    const entries = (board && board.entries) || [];
    const table = document.getElementById("leaderboard");
    if (board && board.key === "ai") {
      table.innerHTML = "<tr><th>#</th><th>Name</th><th>Score</th><th>Games Played</th><th>Avg Score</th></tr>" +
        entries.map((entry, index) => `
        <tr><td>${index === 0 ? "#" + 1 : index + 1}</td><td>${esc(entry.username)} ${feedbackBadge(entry.feedback_count)}</td>
        <td>${entry.score}</td><td>${entry.games_played}</td><td>${Number(entry.average_score || 0).toFixed(2)}</td></tr>`).join("");
      return;
    }
    table.innerHTML = "<tr><th>#</th><th>Captain</th><th>W</th><th>L</th><th>Battles</th></tr>" +
      (entries || []).map((entry, index) => `
        <tr><td>${index === 0 ? "👑" : index + 1}</td><td>${esc(entry.username)} ${feedbackBadge(entry.feedback_count)}</td>
        <td>${entry.wins}</td><td>${entry.losses}</td><td>${entry.games_played}</td></tr>`).join("");
  }

  const FEEDBACK_RENDER_WARNING = "If you're playing via starshot-1i2t.onrender.com, it is a free server that doesn't keep data between sessions. Please submit feedback via the /r/StarShotBoardgame subreddit instead. After making your feedback report, use the Copy to clipboard for /r/StarShotBoardgame posting button.";

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
    };
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

  function openFeedback(context = {}) {
    alert(FEEDBACK_RENDER_WARNING);
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
      <p class="feedback-host-warning">${FEEDBACK_RENDER_WARNING}</p>
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
          <span>report a bug - include the game log</span>
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
        const result = await API.submitFeedback({
          rating: payload.rating,
          liked: payload.liked,
          disliked: payload.disliked,
          thoughts: payload.thoughts,
          match_id: payload.matchId || null,
          game_id: payload.gameId || null,
          is_bug_report: payload.isBugReport,
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
    document.getElementById("open-seats").addEventListener("change", updateCrewUI);
    const expToggle = document.getElementById("exp-star-command");
    if (expToggle) {
      expToggle.addEventListener("change", (event) => {
        starCommandActive = !!event.target.checked;
        if (starCommandActive) maybeShowStarCommandTutorial();
      });
    }
    const breachToggle = document.getElementById("exp-star-breach");
    if (breachToggle) {
      breachToggle.addEventListener("change", (event) => {
        starBreachActive = !!event.target.checked;
        updateCrewUI();
        if (starBreachActive) maybeShowStarBreachTutorial();
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
        });
        crew = [];
        updateCrewUI();
        if (result.game_id) { leave(); Game.enter(result.game_id); }
        else { App.toast("Raid posted — waiting for captains to join.", true); refresh(); }
      } catch (error) { App.toast(error.message); }
    });
    document.getElementById("btn-tutorial").addEventListener("click", () => Tutorial.start());
    document.getElementById("btn-feedback-lobby").addEventListener("click", () => openFeedback());
    document.getElementById("btn-logout").addEventListener("click", async () => {
      try { await API.logout(); } catch (err) {}
      leave();
      App.showScreen("auth");
    });
  });

  window.Feedback = { open: openFeedback };
  window.Lobby = { enter, leave };
})();
