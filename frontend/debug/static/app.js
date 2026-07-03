const state = {
  games: [],
  selectedGameId: null,
  selectedState: null,
};

const redOrders = {
  stacks: [
    { action_number: 1, seal_mode: "sealed", cards: [{ card_id: "move_1_a" }] },
    { action_number: 2, seal_mode: "sealed", cards: [{ card_id: "move_1_b" }] },
    { action_number: 3, seal_mode: "overdrive", cards: [{ card_id: "move_2_a" }] },
  ],
};

const blueOrders = {
  stacks: [
    {
      action_number: 1,
      seal_mode: "sealed",
      cards: [{ card_id: "attack_1_a", target_player_id: "red" }],
    },
    {
      action_number: 2,
      seal_mode: "sealed",
      cards: [{ card_id: "attack_1_b", target_player_id: "red" }],
    },
    {
      action_number: 3,
      seal_mode: "sealed",
      cards: [{ card_id: "attack_2_a", target_player_id: "red" }],
    },
  ],
};

const elements = {
  createButton: document.querySelector("#createButton"),
  refreshButton: document.querySelector("#refreshButton"),
  gamesList: document.querySelector("#gamesList"),
  gameCount: document.querySelector("#gameCount"),
  selectedGameId: document.querySelector("#selectedGameId"),
  roundValue: document.querySelector("#roundValue"),
  phaseValue: document.querySelector("#phaseValue"),
  startingPlayerValue: document.querySelector("#startingPlayerValue"),
  redOrdersButton: document.querySelector("#redOrdersButton"),
  blueOrdersButton: document.querySelector("#blueOrdersButton"),
  revealOrdersToggle: document.querySelector("#revealOrdersToggle"),
  playersView: document.querySelector("#playersView"),
  eventsView: document.querySelector("#eventsView"),
  stateJson: document.querySelector("#stateJson"),
};

async function api(path, options = {}) {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
    ...options,
  });
  const payload = await response.json();
  if (!response.ok) {
    throw new Error(payload.detail || `Request failed: ${response.status}`);
  }
  return payload;
}

async function refreshGames() {
  const payload = await api("/api/games");
  state.games = payload.games;
  renderGames();
  if (!state.selectedGameId && state.games.length > 0) {
    await selectGame(state.games[0].id);
  } else if (state.selectedGameId) {
    await selectGame(state.selectedGameId);
  }
}

async function createGame() {
  const payload = await api("/api/games", {
    method: "POST",
    body: JSON.stringify({ player_ids: ["red", "blue"], seed: 3 }),
  });
  state.selectedGameId = payload.game_id;
  await refreshGames();
}

async function selectGame(gameId) {
  const revealOrders = elements.revealOrdersToggle.checked;
  const payload = await api(`/api/games/${gameId}?reveal_orders=${revealOrders}`);
  state.selectedGameId = gameId;
  state.selectedState = payload.state;
  renderAll();
}

async function submitOrders(playerId, orders) {
  if (!state.selectedGameId) return;
  const payload = await api(`/api/games/${state.selectedGameId}/orders`, {
    method: "POST",
    body: JSON.stringify({ player_id: playerId, orders }),
  });
  state.selectedState = payload.state;
  await refreshGames();
}

function renderGames() {
  elements.gameCount.textContent = state.games.length.toString();
  elements.gamesList.replaceChildren(
    ...state.games.map((game) => {
      const button = document.createElement("button");
      button.className = "game-row";
      if (game.id === state.selectedGameId) button.classList.add("selected");
      button.type = "button";
      button.innerHTML = `
        <span>${game.id.slice(0, 8)}</span>
        <small>Round ${game.round_number} · ${game.phase}</small>
      `;
      button.addEventListener("click", () => selectGame(game.id));
      return button;
    }),
  );
}

function renderAll() {
  renderGames();
  const game = state.selectedState;
  elements.selectedGameId.textContent = state.selectedGameId ? state.selectedGameId.slice(0, 12) : "None";
  elements.roundValue.textContent = game?.round_number ?? "-";
  elements.phaseValue.textContent = game?.phase ?? "-";
  elements.startingPlayerValue.textContent = game?.starting_player_id ?? "-";
  elements.redOrdersButton.disabled = !canSubmit("red");
  elements.blueOrdersButton.disabled = !canSubmit("blue");
  renderPlayers(game);
  renderEvents(game);
  elements.stateJson.textContent = JSON.stringify(game || {}, null, 2);
}

function canSubmit(playerId) {
  const player = state.selectedState?.players?.[playerId];
  return Boolean(player && state.selectedState.phase === "give_orders" && !player.has_submitted_orders);
}

function renderPlayers(game) {
  if (!game) {
    elements.playersView.replaceChildren();
    return;
  }
  const rows = Object.values(game.players).map((player) => {
    const row = document.createElement("article");
    row.className = "player-row";
    row.innerHTML = `
      <div>
        <h3>${player.id}</h3>
        <p>${player.has_submitted_orders ? "Orders submitted" : "Waiting for orders"}</p>
      </div>
      <dl>
        <div><dt>VP</dt><dd>${player.victory_points}</dd></div>
        <div><dt>Deck</dt><dd>${player.deck.length}</dd></div>
        <div><dt>Overheat</dt><dd>${player.overheat.length}</dd></div>
        <div><dt>Shields</dt><dd>${player.ship.shields}</dd></div>
      </dl>
    `;
    return row;
  });
  elements.playersView.replaceChildren(...rows);
}

function renderEvents(game) {
  const events = game?.event_log || [];
  elements.eventsView.replaceChildren(
    ...events.map((event) => {
      const item = document.createElement("li");
      item.innerHTML = `<strong>${event.type}</strong><pre>${JSON.stringify(event, null, 2)}</pre>`;
      return item;
    }),
  );
}

elements.createButton.addEventListener("click", () => createGame().catch(showError));
elements.refreshButton.addEventListener("click", () => refreshGames().catch(showError));
elements.redOrdersButton.addEventListener("click", () => submitOrders("red", redOrders).catch(showError));
elements.blueOrdersButton.addEventListener("click", () => submitOrders("blue", blueOrders).catch(showError));
elements.revealOrdersToggle.addEventListener("change", () => {
  if (state.selectedGameId) selectGame(state.selectedGameId).catch(showError);
});

function showError(error) {
  alert(error.message);
}

refreshGames().catch(showError);
