const state = {
  games: [],
  selectedGameId: null,
  selectedState: null,
  builderPlayerId: "red",
  builderDraft: createEmptyDraft(),
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

const BOARD_RADIUS = 12;
const HEX_SIZE = 14;
const SQRT3 = Math.sqrt(3);
const SHIP_COLORS = {
  red: "#c9433f",
  blue: "#2f6fce",
  green: "#2d8b57",
  yellow: "#c49b22",
};
const FACING_VECTORS = [
  [0.866, 0.5],
  [0.866, -0.5],
  [0, -1],
  [-0.866, -0.5],
  [-0.866, 0.5],
  [0, 1],
];

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
  resolveButton: document.querySelector("#resolveButton"),
  revealOrdersToggle: document.querySelector("#revealOrdersToggle"),
  builderPlayerSelect: document.querySelector("#builderPlayerSelect"),
  ordersBuilderView: document.querySelector("#ordersBuilderView"),
  ordersPreview: document.querySelector("#ordersPreview"),
  submitBuiltOrdersButton: document.querySelector("#submitBuiltOrdersButton"),
  boardSvg: document.querySelector("#boardSvg"),
  playersView: document.querySelector("#playersView"),
  eventsView: document.querySelector("#eventsView"),
  stateJson: document.querySelector("#stateJson"),
};

function createEmptyDraft() {
  return {
    stacks: [1, 2, 3].map((actionNumber) => ({
      action_number: actionNumber,
      seal_mode: "sealed",
      cards: ["", ""],
      targets: ["", ""],
      move_choices: ["forward", "forward"],
    })),
  };
}

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
  syncBuilderPlayer();
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

async function resolveNextStep() {
  if (!state.selectedGameId) return;
  const payload = await api(`/api/games/${state.selectedGameId}/resolve`, { method: "POST" });
  state.selectedState = payload.state;
  await refreshGames();
}

async function submitBuiltOrders() {
  if (!state.selectedGameId || !state.builderPlayerId) return;
  const validation = validateBuiltOrders();
  if (!validation.ok) {
    showError(new Error(validation.message));
    return;
  }
  await submitOrders(state.builderPlayerId, buildOrdersPayload());
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
  elements.resolveButton.disabled = !canResolve(game);
  renderOrdersBuilder(game);
  renderBoard(game);
  renderPlayers(game);
  renderEvents(game);
  elements.stateJson.textContent = JSON.stringify(game || {}, null, 2);
}

function canSubmit(playerId) {
  const player = state.selectedState?.players?.[playerId];
  return Boolean(player && state.selectedState.phase === "give_orders" && !player.has_submitted_orders);
}

function canResolve(game) {
  return Boolean(game && !["give_orders", "complete"].includes(game.phase));
}

function renderBoard(game) {
  const svg = elements.boardSvg;
  if (!svg) return;
  svg.replaceChildren();

  const margin = HEX_SIZE * 2.5;
  const extent = BOARD_RADIUS * HEX_SIZE * 2 + margin;
  svg.setAttribute("viewBox", `${-extent} ${-extent} ${extent * 2} ${extent * 2}`);

  for (let q = -BOARD_RADIUS; q <= BOARD_RADIUS; q += 1) {
    const rMin = Math.max(-BOARD_RADIUS, -q - BOARD_RADIUS);
    const rMax = Math.min(BOARD_RADIUS, -q + BOARD_RADIUS);
    for (let r = rMin; r <= rMax; r += 1) {
      const [x, y] = axialToPixel(q, r);
      const hex = svgEl("polygon");
      hex.setAttribute("points", hexPoints(x, y).map((point) => point.join(",")).join(" "));
      hex.setAttribute("class", q === 0 && r === 0 ? "board-hex center-hex" : "board-hex");
      svg.append(hex);
    }
  }

  Object.values(game?.players || {}).forEach((player) => {
    const [x, y] = axialToPixel(player.ship.q, player.ship.r);
    const group = svgEl("g");
    group.setAttribute("class", "ship-token");

    const circle = svgEl("circle");
    circle.setAttribute("cx", x);
    circle.setAttribute("cy", y);
    circle.setAttribute("r", HEX_SIZE * 0.58);
    circle.setAttribute("fill", SHIP_COLORS[player.id] || "#6f5ab8");

    const [fx, fy] = FACING_VECTORS[player.ship.facing % 6];
    const line = svgEl("line");
    line.setAttribute("x1", x);
    line.setAttribute("y1", y);
    line.setAttribute("x2", x + fx * HEX_SIZE * 0.9);
    line.setAttribute("y2", y + fy * HEX_SIZE * 0.9);
    line.setAttribute("class", "ship-facing");

    const label = svgEl("text");
    label.setAttribute("x", x);
    label.setAttribute("y", y + HEX_SIZE * 1.2);
    label.setAttribute("class", "ship-label");
    label.textContent = player.id;

    group.append(circle, line, label);
    svg.append(group);
  });
}

function axialToPixel(q, r) {
  return [HEX_SIZE * 1.5 * q, HEX_SIZE * SQRT3 * (r + q / 2)];
}

function hexPoints(x, y) {
  return Array.from({ length: 6 }, (_, index) => {
    const angle = (Math.PI / 180) * (60 * index);
    return [x + HEX_SIZE * Math.cos(angle), y + HEX_SIZE * Math.sin(angle)];
  });
}

function svgEl(name) {
  return document.createElementNS("http://www.w3.org/2000/svg", name);
}

function renderPlayers(game) {
  if (!game) {
    elements.playersView.replaceChildren();
    return;
  }
  const rows = Object.values(game.players).map((player) => {
    const row = document.createElement("article");
    row.className = player.has_submitted_orders ? "player-row orders-ready" : "player-row";
    const destroyedComponents = player.ship.destroyed_components.length
      ? player.ship.destroyed_components.join(", ")
      : "None";
    row.innerHTML = `
      <div>
        <h3>${player.id}</h3>
        <p>${player.has_submitted_orders ? "Orders submitted" : "Waiting for orders"}</p>
      </div>
      <dl>
        <div><dt>VP</dt><dd>${player.victory_points}</dd></div>
        <div><dt>Shields</dt><dd>${player.ship.shields}</dd></div>
        <div><dt>Deck</dt><dd>${player.deck.length}</dd></div>
        <div><dt>Overheat</dt><dd>${player.overheat.length}</dd></div>
        <div><dt>Hex</dt><dd>${player.ship.q}, ${player.ship.r}</dd></div>
        <div><dt>Facing</dt><dd>${player.ship.facing}</dd></div>
        <div><dt>Move</dt><dd>${player.ship.movement_this_action}</dd></div>
        <div><dt>Damage</dt><dd>${destroyedComponents}</dd></div>
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

function syncBuilderPlayer() {
  const players = Object.keys(state.selectedState?.players || {});
  if (!players.includes(state.builderPlayerId)) {
    state.builderPlayerId = players[0] || "";
    state.builderDraft = createEmptyDraft();
  }
}

function renderOrdersBuilder(game) {
  renderBuilderPlayerSelect(game);
  elements.ordersBuilderView.replaceChildren();
  if (!game || !state.builderPlayerId) {
    elements.ordersPreview.textContent = "{}";
    elements.submitBuiltOrdersButton.disabled = true;
    return;
  }

  const player = game.players[state.builderPlayerId];
  const availableCards = player?.deck || [];
  const validation = validateBuiltOrders();
  const stacks = state.builderDraft.stacks.map((stack, index) =>
    renderActionStack(stack, index, availableCards, game),
  );
  elements.ordersBuilderView.replaceChildren(...stacks);
  elements.ordersPreview.textContent = JSON.stringify(buildOrdersPayload(), null, 2);
  elements.submitBuiltOrdersButton.disabled = !canSubmit(state.builderPlayerId) || !validation.ok;
  elements.submitBuiltOrdersButton.title = validation.ok ? "" : validation.message;
}

function renderBuilderPlayerSelect(game) {
  const players = Object.keys(game?.players || {});
  elements.builderPlayerSelect.replaceChildren(
    ...players.map((playerId) => {
      const option = document.createElement("option");
      option.value = playerId;
      option.textContent = playerId;
      option.selected = playerId === state.builderPlayerId;
      return option;
    }),
  );
  elements.builderPlayerSelect.disabled = players.length === 0;
}

function renderActionStack(stack, stackIndex, availableCards, game) {
  const cardById = Object.fromEntries(availableCards.map((card) => [card.id, card]));
  const section = document.createElement("section");
  section.className = "order-stack";

  const header = document.createElement("div");
  header.className = "order-stack-header";
  header.innerHTML = `
    <h3>Action ${stack.action_number}</h3>
    <label>
      Seal
      <select data-stack="${stackIndex}" data-field="seal_mode">
        <option value="sealed"${stack.seal_mode === "sealed" ? " selected" : ""}>Sealed</option>
        <option value="overdrive"${stack.seal_mode === "overdrive" ? " selected" : ""}>Overdrive</option>
      </select>
    </label>
  `;
  section.append(header);

  for (let cardIndex = 0; cardIndex < 2; cardIndex += 1) {
    section.append(renderCardSlot(stack, stackIndex, cardIndex, availableCards, cardById, game));
  }
  return section;
}

function renderCardSlot(stack, stackIndex, cardIndex, availableCards, cardById, game) {
  const slot = document.createElement("div");
  slot.className = "card-slot";
  const selectedCard = cardById[stack.cards[cardIndex]];
  const opponents = Object.keys(game.players).filter((playerId) => playerId !== state.builderPlayerId);
  const selectedIds = selectedBuilderCardIds();

  const cardOptions = [
    `<option value="">Empty slot</option>`,
    ...availableCards.map((card) => {
      const isUsedElsewhere = selectedIds.includes(card.id) && stack.cards[cardIndex] !== card.id;
      const label = `${card.name} (${card.id})`;
      return `<option value="${card.id}"${stack.cards[cardIndex] === card.id ? " selected" : ""}${
        isUsedElsewhere ? " disabled" : ""
      }>${label}</option>`;
    }),
  ].join("");

  const targetOptions = [
    `<option value="">Choose target</option>`,
    ...opponents.map(
      (playerId) =>
        `<option value="${playerId}"${stack.targets[cardIndex] === playerId ? " selected" : ""}>${playerId}</option>`,
    ),
  ].join("");

  slot.innerHTML = `
    <label>
      Card ${cardIndex + 1}
      <select data-stack="${stackIndex}" data-card="${cardIndex}" data-field="card_id">
        ${cardOptions}
      </select>
    </label>
    <label>
      Move
      <select data-stack="${stackIndex}" data-card="${cardIndex}" data-field="move_choice"${
        selectedCard?.family === "move" ? "" : " disabled"
      }>
        <option value="forward"${stack.move_choices[cardIndex] === "forward" ? " selected" : ""}>Forward</option>
        <option value="turn_left"${stack.move_choices[cardIndex] === "turn_left" ? " selected" : ""}>Turn Left</option>
        <option value="turn_right"${stack.move_choices[cardIndex] === "turn_right" ? " selected" : ""}>Turn Right</option>
        <option value="u_turn"${stack.move_choices[cardIndex] === "u_turn" ? " selected" : ""}>U-Turn</option>
      </select>
    </label>
    <label>
      Target
      <select data-stack="${stackIndex}" data-card="${cardIndex}" data-field="target_player_id"${
        selectedCard?.family === "attack" ? "" : " disabled"
      }>
        ${targetOptions}
      </select>
    </label>
  `;
  return slot;
}

function buildOrdersPayload() {
  const player = state.selectedState?.players?.[state.builderPlayerId];
  const cardById = Object.fromEntries((player?.deck || []).map((card) => [card.id, card]));
  return {
    stacks: state.builderDraft.stacks.map((stack) => ({
      action_number: stack.action_number,
      seal_mode: stack.seal_mode,
      cards: stack.cards
        .map((cardId, cardIndex) => {
          if (!cardId) return null;
          const card = cardById[cardId];
          const selection = {
            card_id: cardId,
            face: "front",
            orientation: card?.family === "move" ? stack.move_choices[cardIndex] : "up",
          };
          if (card?.family === "attack") {
            selection.target_player_id = stack.targets[cardIndex];
          }
          return selection;
        })
        .filter(Boolean),
    })),
  };
}

function validateBuiltOrders() {
  const game = state.selectedState;
  const player = game?.players?.[state.builderPlayerId];
  if (!game || !player) return { ok: false, message: "Select a game and player first." };
  if (!canSubmit(state.builderPlayerId)) return { ok: false, message: "This player cannot submit orders now." };

  const cardById = Object.fromEntries(player.deck.map((card) => [card.id, card]));
  const used = new Set();
  for (const stack of state.builderDraft.stacks) {
    const families = new Set();
    const targets = new Set();
    for (let cardIndex = 0; cardIndex < stack.cards.length; cardIndex += 1) {
      const cardId = stack.cards[cardIndex];
      if (!cardId) continue;
      const card = cardById[cardId];
      if (!card) return { ok: false, message: `${cardId} is not available.` };
      if (used.has(cardId)) return { ok: false, message: `${cardId} is used more than once.` };
      used.add(cardId);
      families.add(card.family);
      if (card.family === "attack") {
        if (!stack.targets[cardIndex]) return { ok: false, message: `${cardId} needs a target.` };
        targets.add(stack.targets[cardIndex]);
      }
    }
    if (families.size > 1) return { ok: false, message: `Action ${stack.action_number} mixes move and attack cards.` };
    if (targets.size > 1) return { ok: false, message: `Action ${stack.action_number} has multiple attack targets.` };
  }
  return { ok: true, message: "" };
}

function selectedBuilderCardIds() {
  return state.builderDraft.stacks.flatMap((stack) => stack.cards).filter(Boolean);
}

function updateBuilderDraftFromControl(target) {
  const stackIndex = Number(target.dataset.stack);
  const cardIndex = target.dataset.card === undefined ? null : Number(target.dataset.card);
  const field = target.dataset.field;
  const stack = state.builderDraft.stacks[stackIndex];
  if (!stack || !field) return;

  if (field === "seal_mode") {
    stack.seal_mode = target.value;
  } else if (field === "card_id" && cardIndex !== null) {
    stack.cards[cardIndex] = target.value;
    stack.targets[cardIndex] = "";
    stack.move_choices[cardIndex] = "forward";
    applyDefaultAttackTarget(stack, cardIndex);
  } else if (field === "move_choice" && cardIndex !== null) {
    stack.move_choices[cardIndex] = target.value;
  } else if (field === "target_player_id" && cardIndex !== null) {
    stack.targets[cardIndex] = target.value;
  }
  renderAll();
}

function applyDefaultAttackTarget(stack, cardIndex) {
  const player = state.selectedState?.players?.[state.builderPlayerId];
  const card = player?.deck?.find((candidate) => candidate.id === stack.cards[cardIndex]);
  const opponents = Object.keys(state.selectedState?.players || {}).filter(
    (playerId) => playerId !== state.builderPlayerId,
  );
  if (card?.family === "attack" && opponents.length === 1) {
    stack.targets[cardIndex] = opponents[0];
  }
}

elements.createButton.addEventListener("click", () => createGame().catch(showError));
elements.refreshButton.addEventListener("click", () => refreshGames().catch(showError));
elements.redOrdersButton.addEventListener("click", () => submitOrders("red", redOrders).catch(showError));
elements.blueOrdersButton.addEventListener("click", () => submitOrders("blue", blueOrders).catch(showError));
elements.resolveButton.addEventListener("click", () => resolveNextStep().catch(showError));
elements.submitBuiltOrdersButton.addEventListener("click", () => submitBuiltOrders().catch(showError));
elements.builderPlayerSelect.addEventListener("change", (event) => {
  state.builderPlayerId = event.target.value;
  state.builderDraft = createEmptyDraft();
  renderAll();
});
elements.ordersBuilderView.addEventListener("change", (event) => {
  if (event.target.matches("select")) updateBuilderDraftFromControl(event.target);
});
elements.revealOrdersToggle.addEventListener("change", () => {
  if (state.selectedGameId) selectGame(state.selectedGameId).catch(showError);
});

function showError(error) {
  alert(error.message);
}

refreshGames().catch(showError);
