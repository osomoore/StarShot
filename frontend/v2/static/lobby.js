/* Lobby: quick match queue, crew builder, open raids, leaderboard, profile. */
(function () {
  const AI_META = {
    bauble_runner: { face: "💰", name: "Salvage Capt. Morrigan", blurb: "chases the loot" },
    hunter_killer: { face: "🗡", name: "Corsair Blackvane", blurb: "marks one prey" },
    blaster: { face: "💥", name: "Gunner Redbeard", blurb: "shoots what's near" },
  };

  let pollTimer = null;
  let queued = false;
  let crew = [];        // selected ai types
  const autoEntered = new Set();  // pairings/challenges already jumped into
  const esc = (value) => Cards.escapeHtml(value);

  async function enter() {
    App.showScreen("lobby");
    renderAiPickers();
    await refresh();
    if (pollTimer) clearInterval(pollTimer);
    pollTimer = setInterval(refresh, 3000);
    Tutorial.offerIfNew();
  }

  function leave() {
    if (pollTimer) clearInterval(pollTimer);
    pollTimer = null;
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
      renderProfile(me.user);
      renderLeaderboard(board.leaderboard);
      document.getElementById("lobby-user").textContent = "☠ " + me.user.username;
      document.getElementById("lobby-admin-link").classList.toggle("hidden", !me.is_admin);
    } catch (err) { /* transient */ }
  }

  function renderAiPickers() {
    const container = document.getElementById("ai-pickers");
    container.innerHTML = "";
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

  function updateCrewUI() {
    document.querySelectorAll(".ai-pick").forEach((node) => {
      const type = node.querySelector(".ai-count").dataset.type;
      const count = crew.filter((entry) => entry === type).length;
      node.querySelector(".ai-count").textContent = "×" + count;
      node.classList.toggle("picked", count > 0);
    });
    const openSeats = parseInt(document.getElementById("open-seats").value, 10) || 0;
    const total = 1 + crew.length + openSeats;
    const button = document.getElementById("btn-create-match");
    button.disabled = total < 2 || total > 4;
    button.textContent = total < 2 ? "🏴‍☠ Pick at least one foe" : `🏴‍☠ Launch Raid (${total} ships)`;
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
        <span class="player-record">${player.wins}W / ${player.losses}L</span>`;
      const button = document.createElement("button");
      button.className = "btn crimson small";
      button.textContent = "⚔ Challenge";
      button.addEventListener("click", async () => {
        try {
          await API.challenge(player.username);
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
      Victories: <b>${user.wins}</b> · Defeats: <b>${user.losses}</b> · Draws: <b>${user.draws}</b><br>
      Battles fought: <b>${total}</b> · Win rate: <b>${rate}%</b><br>
      Sailing since: <b>${formatDate(user.created_at)}</b>`;
  }

  function renderLeaderboard(entries) {
    const table = document.getElementById("leaderboard");
    table.innerHTML = "<tr><th>#</th><th>Captain</th><th>W</th><th>L</th><th>Battles</th></tr>" +
      (entries || []).map((entry, index) => `
        <tr><td>${index === 0 ? "👑" : index + 1}</td><td>${esc(entry.username)}</td>
        <td>${entry.wins}</td><td>${entry.losses}</td><td>${entry.games_played}</td></tr>`).join("");
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
    document.getElementById("btn-create-match").addEventListener("click", async () => {
      const openSeats = parseInt(document.getElementById("open-seats").value, 10) || 0;
      try {
        const result = await API.createMatch({ ai_types: crew, open_seats: openSeats });
        crew = [];
        updateCrewUI();
        if (result.game_id) { leave(); Game.enter(result.game_id); }
        else { App.toast("Raid posted — waiting for captains to join.", true); refresh(); }
      } catch (error) { App.toast(error.message); }
    });
    document.getElementById("btn-tutorial").addEventListener("click", () => Tutorial.start());
    document.getElementById("btn-logout").addEventListener("click", async () => {
      try { await API.logout(); } catch (err) {}
      leave();
      App.showScreen("auth");
    });
  });

  window.Lobby = { enter, leave };
})();
