const state = {
  games: [],
  selectedGameId: null,
  selectedState: null,
  builderPlayerId: "red",
  builderDraft: createEmptyDraft(),
  knownCards: {},
};

const BOARD_RADIUS = 14;
const HEX_SIZE = 14;
const SQRT3 = Math.sqrt(3);
const DEMO_MOVE_CHOICES = ["forward", "turn_left", "turn_right"];
const MOVE_CHOICES = [
  { value: "forward", label: "Forward", mark: "F" },
  { value: "turn_left", label: "Turn Left", mark: "L" },
  { value: "turn_right", label: "Turn Right", mark: "R" },
  { value: "u_turn", label: "U-Turn", mark: "U" },
];
const PLAYER_ORDER = ["red", "blue", "green", "yellow"];
const SHIP_COLORS = {
  red: "#c9433f",
  blue: "#2f6fce",
  green: "#2d8b57",
  yellow: "#c49b22",
};
const MINI_COMPONENT_FILLS = {
  weapon: "#f2b632",
  engine: "#3f9963",
  life_support: "#2f8fde",
  bridge: "#8b5a2b",
  default: "#a8adb2",
  destroyed: "#c9433f",
};
const FACING_VECTORS = [
  [0.866, 0.5],
  [0.866, -0.5],
  [0, -1],
  [-0.866, -0.5],
  [-0.866, 0.5],
  [0, 1],
];
const AXIAL_DIRECTIONS = [
  [1, 0],
  [1, -1],
  [0, -1],
  [-1, 0],
  [-1, 1],
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
  leftMiniBoards: document.querySelector("#leftMiniBoards"),
  rightMiniBoards: document.querySelector("#rightMiniBoards"),
  shipBoardsView: document.querySelector("#shipBoardsView"),
  playersView: document.querySelector("#playersView"),
  eventsView: document.querySelector("#eventsView"),
  stateJson: document.querySelector("#stateJson"),
  combatOverlay: null,
  cardPickerOverlay: null,
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
  state.builderDraft = createEmptyDraft();
  state.knownCards = {};
  await refreshGames();
}

async function selectGame(gameId) {
  const previousGameId = state.selectedGameId;
  const previousPhase = state.selectedState?.phase;
  const revealOrders = elements.revealOrdersToggle.checked;
  const payload = await api(`/api/games/${gameId}?reveal_orders=${revealOrders}`);
  state.selectedGameId = gameId;
  state.selectedState = payload.state;
  if (previousGameId !== gameId) {
    state.builderDraft = createEmptyDraft();
    state.knownCards = {};
  } else if (previousPhase === "cleanup" && payload.state.phase === "give_orders") {
    state.builderDraft = createEmptyDraft();
  }
  rememberVisibleCards(payload.state);
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
  const previousPhase = state.selectedState?.phase;
  const previousEventCount = state.selectedState?.event_log?.length ?? 0;
  const payload = await api(`/api/games/${state.selectedGameId}/resolve`, { method: "POST" });
  state.selectedState = payload.state;
  rememberVisibleCards(payload.state);
  if (previousPhase === "cleanup" && payload.state.phase === "give_orders") {
    state.builderDraft = createEmptyDraft();
  }
  showCombatResultOverlay(payload.state, previousEventCount);
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

async function submitDemoOrders(playerId, preferredFamily) {
  const orders = buildDemoOrders(playerId, preferredFamily);
  if (!orders) {
    showError(new Error(`${playerId} cannot submit demo orders right now.`));
    return;
  }
  await submitOrders(playerId, orders);
}

function buildDemoOrders(playerId, preferredFamily) {
  const game = state.selectedState;
  const player = game?.players?.[playerId];
  if (!game || !player || !canSubmit(playerId)) return null;

  const available = [...(player.deck || [])];
  const opponentIds = Object.keys(game.players).filter((id) => id !== playerId);
  const attackTargetId = opponentIds.includes("red") ? "red" : opponentIds[0];

  function takeCard(family) {
    const index = available.findIndex((card) => card.family === family);
    if (index < 0) return null;
    return available.splice(index, 1)[0];
  }

  return {
    stacks: [1, 2, 3].map((actionNumber, index) => {
      const card = takeCard(preferredFamily) || takeCard(preferredFamily === "move" ? "attack" : "move");
      const selection = card ? demoCardSelection(card, actionNumber, attackTargetId) : null;
      return {
        action_number: actionNumber,
        seal_mode: actionNumber === 3 && card ? "overdrive" : "sealed",
        cards: selection ? [selection] : [],
      };
    }),
  };
}

function demoCardSelection(card, actionNumber, attackTargetId) {
  const selection = {
    card_id: card.id,
    face: "front",
    orientation: card.family === "move" ? DEMO_MOVE_CHOICES[actionNumber - 1] : "up",
  };
  if (card.family === "attack") {
    selection.target_player_id = attackTargetId;
  }
  return selection;
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
  renderMiniShipBoards(game);
  renderShipBoards(game);
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

  const extent = BOARD_RADIUS * HEX_SIZE * SQRT3 + HEX_SIZE * 1.5;
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

  renderBaubles(svg, game);
  renderActionPreview(svg, game);
  Object.values(game?.players || {}).forEach((player) => renderShipToken(svg, player, "ship-token"));
}

function renderBaubles(svg, game) {
  (game?.baubles || []).forEach((bauble) => {
    const group = svgEl("g");
    group.setAttribute("class", `bauble-token${bauble.is_fang ? " fang-token" : ""}${bauble.claimed_by?.length ? " claimed" : ""}`);

    baubleFootprint(bauble.q, bauble.r).forEach(([q, r], index) => {
      if (hexDistance(0, 0, q, r) > BOARD_RADIUS) return;
      const [hexX, hexY] = axialToPixel(q, r);
      const hex = svgEl("polygon");
      hex.setAttribute("points", hexPoints(hexX, hexY).map((point) => point.join(",")).join(" "));
      hex.setAttribute("class", index === 0 ? "bauble-hex bauble-center" : "bauble-hex");
      group.append(hex);
    });

    const [x, y] = axialToPixel(bauble.q, bauble.r);
    const ring = svgEl("circle");
    ring.setAttribute("class", "bauble-planet-ring");
    ring.setAttribute("cx", x);
    ring.setAttribute("cy", y);
    ring.setAttribute("r", HEX_SIZE * 2.5);

    const core = svgEl("circle");
    core.setAttribute("class", "bauble-planet-core");
    core.setAttribute("cx", x);
    core.setAttribute("cy", y);
    core.setAttribute("r", HEX_SIZE * 0.62);

    const label = svgEl("text");
    label.setAttribute("x", x);
    label.setAttribute("y", y + 3);
    label.textContent = bauble.is_fang ? "F" : String(bauble.number);

    const title = svgEl("title");
    title.textContent = bauble.is_fang
      ? "Fang: 1 VP each round, 6 VP on round 6, and 1 shieldable damage"
      : `Bauble ${bauble.number}: ${bauble.victory_points} VP`;

    group.append(ring, core, label, title);
    svg.append(group);
  });
}

function baubleFootprint(q, r) {
  return [[q, r], ...AXIAL_DIRECTIONS.map(([dq, dr]) => [q + dq, r + dr])];
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

function renderShipToken(svg, player, className) {
  const [x, y] = axialToPixel(player.ship.q, player.ship.r);
  const group = svgEl("g");
  group.setAttribute("class", className);

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
}

function renderActionPreview(svg, game) {
  const player = game?.players?.[state.builderPlayerId];
  if (!player || !shouldShowBuilderDraft(game, player)) return;

  const cardById = cardLookupForPlayer(player);
  const preview = {
    q: player.ship.q,
    r: player.ship.r,
    facing: player.ship.facing,
  };

  const firstUnresolvedStack = firstUnresolvedStackIndex(game.phase);
  state.builderDraft.stacks.forEach((stack, stackIndex) => {
    if (stackIndex < firstUnresolvedStack) return;

    const selections = stack.cards
      .map((cardId, cardIndex) => ({ card: cardById[cardId], cardIndex }))
      .filter((selection) => selection.card);
    const family = selections[0]?.card.family;
    if (family === "move") {
      selections.forEach(({ card, cardIndex }) => {
        const before = { ...preview };
        applyPreviewMove(
          preview,
          previewCardValue(card, stack.seal_mode),
          stack.move_choices[cardIndex],
        );
        drawMovementPathPreview(svg, before, preview);
        drawPositionPreview(svg, preview, `A${stackIndex + 1}.${cardIndex + 1}`);
      });
    } else if (family === "attack") {
      const firstAttack = selections.find(({ card }) => card.family === "attack");
      const target = game.players[stack.targets[firstAttack.cardIndex]];
      if (target) {
        const damage = selections
          .filter(({ card }) => card.family === "attack")
          .reduce((total, { card }) => total + previewCardValue(card, stack.seal_mode), 0);
        drawAttackPreview(svg, preview, target, `A${stackIndex + 1}`, damage);
      }
    }
  });
}

function shouldShowBuilderDraft(game, player) {
  const hasDraftCards = state.builderDraft.stacks.some((stack) => stack.cards.some(Boolean));
  if (!hasDraftCards) return false;
  if (game.phase === "give_orders") return !player.has_submitted_orders || hasDraftCards;
  return game.phase !== "complete";
}

function firstUnresolvedStackIndex(phase) {
  if (phase === "action_2") return 1;
  if (phase === "action_3") return 2;
  if (phase === "award_baubles" || phase === "cleanup") return 3;
  return 0;
}

function previewCardValue(card, sealMode) {
  return card.value + (sealMode === "overdrive" && card.is_base ? 1 : 0);
}

function applyPreviewMove(preview, distance, choice) {
  if (choice !== "u_turn") {
    const [dq, dr] = AXIAL_DIRECTIONS[preview.facing % 6];
    preview.q += dq * distance;
    preview.r += dr * distance;
    const clamped = clampToBoard(preview.q, preview.r);
    preview.q = clamped.q;
    preview.r = clamped.r;
  }
  if (choice === "turn_left") {
    preview.facing = (preview.facing + 1) % 6;
  } else if (choice === "turn_right") {
    preview.facing = (preview.facing + 5) % 6;
  } else if (choice === "u_turn") {
    preview.facing = (preview.facing + 3) % 6;
  }
}

function clampToBoard(q, r) {
  if (hexDistance(0, 0, q, r) <= BOARD_RADIUS) return { q, r };
  let best = { q: 0, r: 0 };
  let bestDistance = Infinity;
  for (let boardQ = -BOARD_RADIUS; boardQ <= BOARD_RADIUS; boardQ += 1) {
    const rMin = Math.max(-BOARD_RADIUS, -boardQ - BOARD_RADIUS);
    const rMax = Math.min(BOARD_RADIUS, -boardQ + BOARD_RADIUS);
    for (let boardR = rMin; boardR <= rMax; boardR += 1) {
      const distance = hexDistance(q, r, boardQ, boardR);
      if (distance < bestDistance) {
        best = { q: boardQ, r: boardR };
        bestDistance = distance;
      }
    }
  }
  return best;
}

function drawMovementPathPreview(svg, before, after) {
  if (before.q === after.q && before.r === after.r) return;
  const [x1, y1] = axialToPixel(before.q, before.r);
  const [x2, y2] = axialToPixel(after.q, after.r);
  const group = svgEl("g");
  group.setAttribute("class", "move-path-preview");

  const shadow = svgEl("line");
  shadow.setAttribute("class", "move-path-shadow");
  shadow.setAttribute("x1", x1);
  shadow.setAttribute("y1", y1);
  shadow.setAttribute("x2", x2);
  shadow.setAttribute("y2", y2);

  const path = svgEl("line");
  path.setAttribute("x1", x1);
  path.setAttribute("y1", y1);
  path.setAttribute("x2", x2);
  path.setAttribute("y2", y2);

  group.append(shadow, path);
  svg.append(group);
}

function drawPositionPreview(svg, preview, labelText, burstColor = null) {
  const [x, y] = axialToPixel(preview.q, preview.r);
  const group = svgEl("g");
  group.setAttribute("class", "move-preview");

  if (burstColor) {
    const burst = svgEl("polygon");
    burst.setAttribute("class", "attack-preview");
    burst.setAttribute("fill", burstColor);
    burst.setAttribute("points", burstPoints(x, y, HEX_SIZE * 1.18, HEX_SIZE * 0.48).map((point) => point.join(",")).join(" "));
    group.append(burst);
  }

  const circle = svgEl("circle");
  circle.setAttribute("cx", x);
  circle.setAttribute("cy", y);
  circle.setAttribute("r", HEX_SIZE * 0.48);

  const [fx, fy] = FACING_VECTORS[preview.facing % 6];
  const facing = svgEl("line");
  facing.setAttribute("x1", x);
  facing.setAttribute("y1", y);
  facing.setAttribute("x2", x + fx * HEX_SIZE * 0.66);
  facing.setAttribute("y2", y + fy * HEX_SIZE * 0.66);
  facing.setAttribute("class", "preview-facing");

  const label = svgEl("text");
  label.setAttribute("x", x);
  label.setAttribute("y", y + 3);
  label.textContent = labelText;

  group.append(circle, facing, label);
  svg.append(group);
}

function drawAttackPreview(svg, shooterPreview, target, labelText, damage) {
  const [sourceX, sourceY] = axialToPixel(shooterPreview.q, shooterPreview.r);
  const [targetX, targetY] = axialToPixel(target.ship.q, target.ship.r);
  const color = SHIP_COLORS[target.id] || "#6f5ab8";
  const defense = hexDistance(shooterPreview.q, shooterPreview.r, target.ship.q, target.ship.r);
  const group = svgEl("g");
  group.setAttribute("class", "volley-preview");

  const line = svgEl("line");
  line.setAttribute("x1", sourceX);
  line.setAttribute("y1", sourceY);
  line.setAttribute("x2", targetX);
  line.setAttribute("y2", targetY);
  line.setAttribute("stroke", color);

  const arrow = svgEl("polygon");
  arrow.setAttribute("class", "volley-arrowhead");
  arrow.setAttribute("fill", color);
  arrow.setAttribute("points", arrowheadPoints(sourceX, sourceY, targetX, targetY).map((point) => point.join(",")).join(" "));

  const label = svgEl("text");
  label.setAttribute("x", (sourceX + targetX) / 2);
  label.setAttribute("y", (sourceY + targetY) / 2 - HEX_SIZE * 0.45);
  label.textContent = `${labelText} DEF ${defense} DMG ${damage}`;

  group.append(line, arrow, label);
  svg.append(group);
  drawPositionPreview(svg, shooterPreview, labelText);
}

function burstPoints(x, y, outerRadius, innerRadius) {
  return Array.from({ length: 12 }, (_, index) => {
    const radius = index % 2 === 0 ? outerRadius : innerRadius;
    const angle = (Math.PI / 180) * (index * 30 - 90);
    return [x + radius * Math.cos(angle), y + radius * Math.sin(angle)];
  });
}

function arrowheadPoints(sourceX, sourceY, targetX, targetY) {
  const dx = targetX - sourceX;
  const dy = targetY - sourceY;
  const length = Math.hypot(dx, dy) || 1;
  const ux = dx / length;
  const uy = dy / length;
  const tipX = targetX - ux * HEX_SIZE * 0.74;
  const tipY = targetY - uy * HEX_SIZE * 0.74;
  const baseX = tipX - ux * HEX_SIZE * 0.72;
  const baseY = tipY - uy * HEX_SIZE * 0.72;
  const perpX = -uy * HEX_SIZE * 0.35;
  const perpY = ux * HEX_SIZE * 0.35;
  return [
    [tipX, tipY],
    [baseX + perpX, baseY + perpY],
    [baseX - perpX, baseY - perpY],
  ];
}

function hexDistance(aQ, aR, bQ, bR) {
  const aS = -aQ - aR;
  const bS = -bQ - bR;
  return Math.max(Math.abs(aQ - bQ), Math.abs(aR - bR), Math.abs(aS - bS));
}

function renderPlayers(game) {
  if (!elements.playersView) return;
  if (!game) {
    elements.playersView.replaceChildren();
    return;
  }
  const rows = Object.values(game.players).map((player) => {
    const row = document.createElement("article");
    row.className = player.has_submitted_orders ? "player-row orders-ready" : "player-row";
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
        <div><dt>Damage</dt><dd>${player.ship.damage_taken ?? 0}</dd></div>
      </dl>
    `;
    return row;
  });
  elements.playersView.replaceChildren(...rows);
}

function renderShipBoards(game) {
  if (!elements.shipBoardsView) return;
  if (!game) {
    elements.shipBoardsView.replaceChildren();
    return;
  }

  const boards = Object.values(game.players).map((player) => {
    const board = document.createElement("article");
    board.className = player.ship.destroyed ? "ship-board destroyed" : "ship-board";
    board.innerHTML = `
      <div class="ship-board-title">
        <strong>${player.id}</strong>
        <span>${player.ship.destroyed ? "Destroyed" : `${player.ship.shields} shields`}</span>
      </div>
      <div class="ship-art-frame">
        <img src="/resources/base_ship_0.png" alt="${player.id} ship damage board" />
        <div class="ship-damage-layer" aria-hidden="true">
          ${renderDestroyedComponentMarkers(player.ship.destroyed_components || [], player.ship.component_layout || [])}
        </div>
      </div>
      <div class="ship-board-footer">
        <span>${player.ship.damage_taken ?? 0} damage</span>
        <span>${(player.ship.destroyed_components || []).length} components</span>
      </div>
    `;
    return board;
  });
  elements.shipBoardsView.replaceChildren(...boards);
}

function renderDestroyedComponentMarkers(componentIds, layout) {
  const componentById = Object.fromEntries(layout.map((component) => [component.id, component]));
  return componentIds
    .map((componentId) => {
      const component = componentById[componentId];
      const x = component ? component.anchor_x * 100 : 50;
      const y = component ? component.anchor_y * 100 : 50;
      return `<span class="component-hit-marker" style="left: ${x}%; top: ${y}%;" title="${componentId}"></span>`;
    })
    .join("");
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

function rememberVisibleCards(game) {
  Object.values(game?.players || {}).forEach((player) => {
    [...(player.deck || []), ...(player.overheat || [])].forEach((card) => {
      state.knownCards[card.id] = card;
    });
    player.prepared_orders?.stacks?.forEach((stack) => {
      stack.cards.forEach((selection) => {
        const card = state.knownCards[selection.card_id];
        if (card) return;
        state.knownCards[selection.card_id] = inferCardFromId(selection.card_id);
      });
    });
  });
}

function cardLookupForPlayer(player) {
  const visibleCards = Object.fromEntries([...(player?.deck || []), ...(player?.overheat || [])].map((card) => [card.id, card]));
  return { ...state.knownCards, ...visibleCards };
}

function cardsForBuilder(player) {
  const byId = cardLookupForPlayer(player);
  const cards = [...(player?.deck || [])];
  state.builderDraft.stacks.forEach((stack) => {
    stack.cards.forEach((cardId) => {
      if (cardId && byId[cardId] && !cards.some((card) => card.id === cardId)) {
        cards.push(byId[cardId]);
      }
    });
  });
  return cards;
}

function inferCardFromId(cardId) {
  const family = cardId.startsWith("attack") ? "attack" : "move";
  const value = Number(cardId.match(/_(\d+)_/)?.[1] || 1);
  const name = family === "attack" ? `Targeted Attack ${value}` : `Controlled Move ${value}`;
  return { id: cardId, name, family, value, is_base: true };
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
  const availableCards = cardsForBuilder(player);
  const validation = validateBuiltOrders();
  const readOnly = !canSubmit(state.builderPlayerId);
  const stacks = state.builderDraft.stacks.map((stack, index) =>
    renderActionStack(stack, index, availableCards, game, readOnly),
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

function renderActionStack(stack, stackIndex, availableCards, game, readOnly) {
  const cardById = Object.fromEntries(availableCards.map((card) => [card.id, card]));
  const section = document.createElement("section");
  section.className = readOnly ? "order-stack readonly" : "order-stack";
  section.style.setProperty("--action-accent", stack.seal_mode === "overdrive" ? "#c9433f" : "#2f6f78");

  const header = document.createElement("div");
  header.className = "order-stack-header";
  header.innerHTML = `
    <h3>Action ${stack.action_number}</h3>
    <div class="order-stack-actions">
      <button class="seal-toggle ${stack.seal_mode}" type="button" data-stack="${stackIndex}" data-field="seal_mode"${
        readOnly ? " disabled" : ""
      }>
        <span class="seal-current">${stack.seal_mode === "overdrive" ? "Overdrive" : "Sealed"}</span>
        <span class="seal-hover">${stack.seal_mode === "overdrive" ? "Sealed" : "Overdrive"}</span>
      </button>
      <button class="stack-clear-button" type="button" data-stack="${stackIndex}"${readOnly ? " disabled" : ""}>
        Clear
      </button>
    </div>
  `;
  section.append(header);

  for (let cardIndex = 0; cardIndex < 2; cardIndex += 1) {
    section.append(renderCardSlot(stack, stackIndex, cardIndex, availableCards, cardById, game, readOnly));
  }
  return section;
}

function renderCardSlot(stack, stackIndex, cardIndex, availableCards, cardById, game, readOnly) {
  const slot = document.createElement("div");
  slot.className = "card-slot";
  const selectedCard = cardById[stack.cards[cardIndex]];
  const cardTone = selectedCard?.family === "attack" ? "attack-card" : selectedCard?.family === "move" ? "move-card" : "";
  const detail = selectedCard
    ? selectedCard.family === "attack"
      ? targetChoiceLabel(stack.targets[cardIndex])
      : moveChoiceLabel(stack.move_choices[cardIndex])
    : "No card";

  slot.innerHTML = `
    <button class="front-card ${cardTone}" type="button" data-stack="${stackIndex}" data-card="${cardIndex}"${
      readOnly ? " disabled" : ""
    }>
      <span class="card-slot-label">Card ${cardIndex + 1}</span>
      <strong>${selectedCard ? selectedCard.name : "Empty"}</strong>
      <span>${selectedCard ? selectedCard.id : detail}</span>
    </button>
    <button class="hex-choice-summary" type="button" data-stack="${stackIndex}" data-card="${cardIndex}"${
      readOnly ? " disabled" : ""
    }>
      ${detail}
    </button>
  `;
  return slot;
}

function moveChoiceLabel(value) {
  return MOVE_CHOICES.find((choice) => choice.value === value)?.label || "Choose move";
}

function targetChoiceLabel(playerId) {
  return playerId ? `Player ${titleCase(playerId)}` : "Choose target";
}

function titleCase(value) {
  return String(value || "").charAt(0).toUpperCase() + String(value || "").slice(1);
}

function cardPickerOverlayElement() {
  if (elements.cardPickerOverlay) return elements.cardPickerOverlay;
  const overlay = document.createElement("div");
  overlay.className = "card-picker-overlay";
  overlay.addEventListener("click", (event) => {
    if (event.target === overlay) hideCardPickerOverlay();
  });
  document.body.append(overlay);
  elements.cardPickerOverlay = overlay;
  return overlay;
}

function hideCardPickerOverlay() {
  elements.cardPickerOverlay?.classList.remove("visible");
}

function showCardPicker(stackIndex, cardIndex) {
  const game = state.selectedState;
  const player = game?.players?.[state.builderPlayerId];
  if (!game || !player || !canSubmit(state.builderPlayerId)) return;

  const overlay = cardPickerOverlayElement();
  const availableCards = cardsForBuilder(player);
  const selectedIds = selectedBuilderCardIds();
  const stack = state.builderDraft.stacks[stackIndex];
  const cardById = cardLookupForPlayer(player);
  const lockedFamily = stack.cards
    .map((cardId, index) => (index === cardIndex ? null : cardById[cardId]?.family))
    .find(Boolean);
  overlay.replaceChildren();

  const panel = document.createElement("section");
  panel.className = "card-picker-panel";
  panel.innerHTML = `
    <div class="card-picker-header">
      <span>Action ${stack.action_number} Card ${cardIndex + 1}</span>
      <div class="card-picker-actions">
        <button class="picker-clear-action" type="button">Clear action</button>
        <button type="button" aria-label="Dismiss card picker">&times;</button>
      </div>
    </div>
    <div class="card-picker-columns">
      <div class="picker-column move-column">
        <h3>Move</h3>
      </div>
      <div class="picker-column attack-column">
        <h3>Attack</h3>
      </div>
    </div>
  `;
  panel.querySelector(".card-picker-header button[aria-label]").addEventListener("click", hideCardPickerOverlay);
  panel.querySelector(".picker-clear-action").addEventListener("click", () => {
    clearActionStack(stackIndex);
    hideCardPickerOverlay();
  });

  const columns = {
    move: panel.querySelector(".move-column"),
    attack: panel.querySelector(".attack-column"),
  };

  ["move", "attack"].forEach((family) => {
    const cards = availableCards.filter((card) => card.family === family);
    if (cards.length === 0) {
      const empty = document.createElement("p");
      empty.className = "picker-empty";
      empty.textContent = "No cards";
      columns[family].append(empty);
    }
    cards.forEach((card) => {
      const isUsedElsewhere = selectedIds.includes(card.id) && stack.cards[cardIndex] !== card.id;
      const isWrongFamily = Boolean(lockedFamily && card.family !== lockedFamily);
      const button = document.createElement("button");
      button.type = "button";
      button.className = `picker-card ${family === "move" ? "move-card" : "attack-card"}`;
      button.disabled = isUsedElsewhere || isWrongFamily;
      button.innerHTML = `
        <strong>${card.name}</strong>
        <span>${card.id}</span>
        <b>${card.value}</b>
      `;
      button.addEventListener("click", () => {
        selectBuilderCard(stackIndex, cardIndex, card.id);
        hideCardPickerOverlay();
        showHexChoicePanel(stackIndex, cardIndex);
      });
      columns[family].append(button);
    });
  });

  overlay.append(panel);
  overlay.classList.add("visible");
}

function selectBuilderCard(stackIndex, cardIndex, cardId) {
  const stack = state.builderDraft.stacks[stackIndex];
  if (!stack) return;
  stack.cards[cardIndex] = cardId;
  stack.targets[cardIndex] = "";
  stack.move_choices[cardIndex] = "forward";
  applyDefaultAttackTarget(stack, cardIndex);
  renderAll();
}

function clearActionStack(stackIndex) {
  const stack = state.builderDraft.stacks[stackIndex];
  if (!stack) return;
  stack.seal_mode = "sealed";
  stack.cards = ["", ""];
  stack.targets = ["", ""];
  stack.move_choices = ["forward", "forward"];
  renderAll();
}

function showHexChoicePanel(stackIndex, cardIndex) {
  const game = state.selectedState;
  const player = game?.players?.[state.builderPlayerId];
  const stack = state.builderDraft.stacks[stackIndex];
  const card = cardLookupForPlayer(player)[stack?.cards?.[cardIndex]];
  if (!game || !player || !stack || !card || !canSubmit(state.builderPlayerId)) return;

  const overlay = cardPickerOverlayElement();
  overlay.replaceChildren();

  const panel = document.createElement("section");
  panel.className = "hex-choice-panel";
  panel.innerHTML = `
    <div class="card-picker-header">
      <span>${card.family === "attack" ? "Choose Target" : "Choose Move"}</span>
      <button type="button" aria-label="Dismiss choice panel">&times;</button>
    </div>
    <div class="hex-choice-grid"></div>
  `;
  panel.querySelector(".card-picker-header button").addEventListener("click", hideCardPickerOverlay);
  const grid = panel.querySelector(".hex-choice-grid");

  const choices = card.family === "attack" ? attackHexChoices(game) : MOVE_CHOICES;
  choices.forEach((choice) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = `hex-choice ${choice.disabled ? "disabled-choice" : ""}`;
    button.disabled = Boolean(choice.disabled);
    button.style.setProperty("--choice-fill", choice.fill || "#3f9963");
    button.innerHTML = `
      <span class="choice-hex">${choice.mark || ""}</span>
      <strong>${choice.label}</strong>
    `;
    button.addEventListener("click", () => {
      if (card.family === "attack") {
        stack.targets[cardIndex] = choice.value;
      } else {
        stack.move_choices[cardIndex] = choice.value;
      }
      hideCardPickerOverlay();
      renderAll();
    });
    grid.append(button);
  });

  overlay.append(panel);
  overlay.classList.add("visible");
}

function attackHexChoices(game) {
  return PLAYER_ORDER.map((playerId) => {
    const isSelf = playerId === state.builderPlayerId;
    const isActive = Boolean(game.players[playerId]);
    return {
      value: playerId,
      label: `Player ${titleCase(playerId)}`,
      mark: titleCase(playerId).charAt(0),
      fill: SHIP_COLORS[playerId],
      disabled: !isActive || isSelf,
    };
  });
}

function buildOrdersPayload() {
  const player = state.selectedState?.players?.[state.builderPlayerId];
  const cardById = cardLookupForPlayer(player);
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
  const card = cardLookupForPlayer(player)[stack.cards[cardIndex]];
  const opponents = Object.keys(state.selectedState?.players || {}).filter(
    (playerId) => playerId !== state.builderPlayerId,
  );
  if (card?.family === "attack" && opponents.length === 1) {
    stack.targets[cardIndex] = opponents[0];
  }
}

elements.createButton.addEventListener("click", () => createGame().catch(showError));
elements.refreshButton.addEventListener("click", () => refreshGames().catch(showError));
elements.redOrdersButton.addEventListener("click", () => submitDemoOrders("red", "move").catch(showError));
elements.blueOrdersButton.addEventListener("click", () => submitDemoOrders("blue", "attack").catch(showError));
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
elements.ordersBuilderView.addEventListener("click", (event) => {
  const clearButton = event.target.closest(".stack-clear-button");
  if (clearButton) {
    if (clearButton.disabled) return;
    clearActionStack(Number(clearButton.dataset.stack));
    return;
  }

  const sealToggle = event.target.closest(".seal-toggle");
  if (sealToggle) {
    const stack = state.builderDraft.stacks[Number(sealToggle.dataset.stack)];
    if (!stack || sealToggle.disabled) return;
    stack.seal_mode = stack.seal_mode === "sealed" ? "overdrive" : "sealed";
    renderAll();
    return;
  }

  const frontCard = event.target.closest(".front-card");
  if (frontCard) {
    if (frontCard.disabled) return;
    showCardPicker(Number(frontCard.dataset.stack), Number(frontCard.dataset.card));
    return;
  }

  const choiceButton = event.target.closest(".hex-choice-summary");
  if (choiceButton) {
    if (choiceButton.disabled) return;
    const stackIndex = Number(choiceButton.dataset.stack);
    const cardIndex = Number(choiceButton.dataset.card);
    const stack = state.builderDraft.stacks[stackIndex];
    if (!stack?.cards?.[cardIndex]) {
      showCardPicker(stackIndex, cardIndex);
      return;
    }
    showHexChoicePanel(stackIndex, cardIndex);
  }
});
elements.revealOrdersToggle.addEventListener("change", () => {
  if (state.selectedGameId) selectGame(state.selectedGameId).catch(showError);
});

function showError(error) {
  alert(error.message);
}

function showCombatResultOverlay(game, previousEventCount) {
  const volleys = latestCombatVolleys(game, previousEventCount);
  if (volleys.length === 0) return;

  const overlay = combatOverlayElement();
  const actionNumber = volleys[0].action_number;
  overlay.replaceChildren();

  const panel = document.createElement("section");
  panel.className = "combat-result-panel";
  panel.innerHTML = `
    <div class="combat-result-header">
      <span>Action ${actionNumber}</span>
      <button type="button" aria-label="Dismiss combat result">&times;</button>
    </div>
    <div class="combat-result-list"></div>
  `;
  const list = panel.querySelector(".combat-result-list");
  volleys.forEach((volley) => {
    const item = document.createElement("article");
    item.className = volley.hit ? "combat-result-item hit" : "combat-result-item miss";
    const outcome = volley.hit ? "Hit" : "Miss";
    const attackBonus = volley.attack_bonus ?? volley.aim_bonus ?? 0;
    const rollTotal = volley.roll + attackBonus;
    const damageText = volley.shielded
      ? `${volley.damage} blocked by shield`
      : `${volley.damage_applied} / ${volley.damage} damage`;
    const shotText = renderDamageShotLines(volley.damage_shots || []);
    item.innerHTML = `
      <strong>${volley.attacker_id} -> ${volley.target_id}</strong>
      <span class="combat-result-summary">${outcome}: ${attackBonus} bonus + ${volley.roll} roll = ${rollTotal} vs ${volley.defense_threshold} final defense</span>
      <div class="combat-result-breakdown">
        <span>Attack: ${attackBonus} bonus + ${volley.roll} roll = ${rollTotal}</span>
        <span>Defense: ${volley.distance ?? 0} distance + ${volley.target_movement ?? 0} move bonus + ${volley.target_defense_bonus ?? 0} modifiers = ${volley.defense_threshold}</span>
      </div>
      <span>${damageText}</span>
      ${shotText}
    `;
    list.append(item);
  });
  panel.querySelector("button").addEventListener("click", hideCombatResultOverlay);
  overlay.append(panel);
  overlay.classList.add("visible");
}

function renderDamageShotLines(shots) {
  if (shots.length === 0) return "";
  return `
    <div class="damage-shot-list">
      ${shots.map(formatDamageShot).join("")}
    </div>
  `;
}

function formatDamageShot(shot) {
  const result = shot.destroyed ? formatComponentId(shot.component_id) : "No intact component";
  return `<span>Lane ${shot.lane}: ${result}</span>`;
}

function formatComponentId(componentId) {
  return (componentId || "")
    .split("_")
    .filter(Boolean)
    .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
    .join(" ");
}

function latestCombatVolleys(game, previousEventCount) {
  const volleys = (game?.event_log || [])
    .slice(previousEventCount)
    .filter((event) => event.type === "volley_resolved");
  const latest = volleys.at(-1);
  if (!latest) return [];
  return volleys.filter(
    (event) => event.round === latest.round && event.action_number === latest.action_number,
  );
}

function combatOverlayElement() {
  if (elements.combatOverlay) return elements.combatOverlay;
  const overlay = document.createElement("div");
  overlay.className = "combat-result-overlay";
  overlay.addEventListener("click", (event) => {
    if (event.target === overlay) hideCombatResultOverlay();
  });
  document.body.append(overlay);
  elements.combatOverlay = overlay;
  return overlay;
}

function hideCombatResultOverlay() {
  elements.combatOverlay?.classList.remove("visible");
}

function renderMiniShipBoards(game) {
  if (!elements.leftMiniBoards) return;
  if (!game) {
    elements.leftMiniBoards.replaceChildren();
    return;
  }

  const colors = PLAYER_ORDER.filter((color) => game.players[color]);
  elements.leftMiniBoards.replaceChildren(...colors.map((color) => createMiniBoardCard(color, game)));
}

function createMiniBoardCard(color, game) {
  const player = game.players[color];
  const isInactive = !player;

  const card = document.createElement("div");
  card.className = `mini-ship-board ${isInactive ? "inactive" : ""}`;
  card.style.borderColor = SHIP_COLORS[color] || "#ccc";

  const header = document.createElement("div");
  header.className = "mini-ship-header";
  header.innerHTML = `
    <strong class="mini-ship-name" style="color: ${SHIP_COLORS[color] || '#555'}">${color.toUpperCase()}</strong>
    <span class="mini-ship-vp">${player ? player.victory_points : 0} VP</span>
  `;
  card.append(header);

  const svgContainer = document.createElement("div");
  svgContainer.className = "mini-ship-svg-container";

  const svg = svgEl("svg");
  svg.setAttribute("viewBox", "-34 -35 68 70");
  svg.setAttribute("class", "mini-ship-svg");

  let layout = player?.ship?.component_layout;
  if (!layout) {
    const anyActivePlayer = Object.values(game.players)[0];
    layout = anyActivePlayer?.ship?.component_layout;
  }

  if (layout) {
    const destroyedSet = new Set(player?.ship?.destroyed_components || []);
    renderMiniShieldRings(svg, player?.ship?.shields || 0);
    
    layout.forEach(comp => {
      const size = 7;
      const x = size * 1.5 * comp.q;
      const y = size * SQRT3 * (comp.r + comp.q / 2);

      const isDestroyed = destroyedSet.has(comp.id);
      const fill = isDestroyed
        ? MINI_COMPONENT_FILLS.destroyed
        : MINI_COMPONENT_FILLS[comp.type] || MINI_COMPONENT_FILLS.default;

      const poly = svgEl("polygon");
      poly.setAttribute("points", getMiniHexPoints(x, y, size).map(p => p.join(",")).join(" "));
      poly.setAttribute("stroke", "#000000");
      poly.setAttribute("stroke-width", "1");
      poly.setAttribute("fill", fill);
      poly.setAttribute("class", `mini-hex-cell ${comp.type} ${isDestroyed ? "destroyed" : ""}`);
      
      const title = svgEl("title");
      title.textContent = `${comp.name}${isDestroyed ? " (DESTROYED)" : ""}`;
      poly.append(title);

      svg.append(poly);
    });
  }

  svgContainer.append(svg);
  card.append(svgContainer);

  const footer = document.createElement("div");
  footer.className = "mini-ship-footer";
  footer.innerHTML = `
    <span class="mini-stat" title="Cards in deck"><span class="mini-icon deck-icon"></span>${player ? player.deck.length : 0}</span>
    <span class="mini-stat" title="Cards in overheat"><span class="mini-icon overheat-icon"></span>${player ? player.overheat.length : 0}</span>
  `;
  card.append(footer);
  return card;
}

function renderMiniShieldRings(svg, shieldCount) {
  [0, 1].forEach((index) => {
    const ring = svgEl("circle");
    const isActive = shieldCount > index;
    ring.setAttribute("cx", "0");
    ring.setAttribute("cy", "0");
    ring.setAttribute("r", String(32 - index * 3));
    ring.setAttribute("fill", "none");
    ring.setAttribute("stroke", isActive ? "#2f8fde" : "#c8cfcc");
    ring.setAttribute("stroke-width", isActive ? "1.6" : "1.2");
    ring.setAttribute("stroke-dasharray", isActive ? "" : "3 3");
    ring.setAttribute("opacity", isActive ? "0.95" : "0.5");
    svg.append(ring);
  });
}

function getMiniHexPoints(x, y, size) {
  return Array.from({ length: 6 }, (_, index) => {
    const angle = (Math.PI / 180) * (60 * index);
    return [x + size * Math.cos(angle), y + size * Math.sin(angle)];
  });
}

refreshGames().catch(showError);
