const state = {
  games: [],
  selectedGameId: null,
  selectedState: null,
  builderPlayerId: "red",
  builderDraft: createEmptyDraft(),
  knownCards: {},
  // New properties for board interaction
  zoomScale: 1,
  panOffsetX: 0,
  panOffsetY: 0,
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
const START_CORNER_DIRECTIONS = [3, 0, 2, 5];

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
  // Zoom button handlers
  boardZoomOutButton: document.querySelector("#boardZoomOutButton"),
  boardZoomInButton: document.querySelector("#boardZoomInButton"),
};

if (elements.boardZoomInButton) {
  elements.boardZoomInButton.addEventListener("click", () => {
    state.zoomScale = Math.min(state.zoomScale * 1.2, 4);
    renderBoard(state.selectedState);
  });
}

if (elements.boardZoomOutButton) {
  elements.boardZoomOutButton.addEventListener("click", () => {
    state.zoomScale = Math.max(state.zoomScale / 1.2, 0.5);
    renderBoard(state.selectedState);
  });
}

// Pan handling
let isPanning = false;
let panStart = { x: 0, y: 0 };
let panStartOffset = { x: 0, y: 0 };

if (elements.boardSvg) {
  elements.boardSvg.addEventListener("mousedown", (e) => {
    isPanning = true;
    panStart = { x: e.clientX, y: e.clientY };
    panStartOffset = { x: state.panOffsetX, y: state.panOffsetY };
  });
  window.addEventListener("mousemove", (e) => {
    if (!isPanning) return;
    const dx = e.clientX - panStart.x;
    const dy = e.clientY - panStart.y;
    const svgRect = elements.boardSvg.getBoundingClientRect();
    const viewSize = (BOARD_RADIUS * HEX_SIZE * SQRT3 + HEX_SIZE * 1.5) * 2 / state.zoomScale;
    const scaleFactorX = viewSize / svgRect.width;
    const scaleFactorY = viewSize / svgRect.height;
    state.panOffsetX = panStartOffset.x - dx * scaleFactorX;
    state.panOffsetY = panStartOffset.y - dy * scaleFactorY;
    renderBoard(state.selectedState);
  });
  window.addEventListener("mouseup", () => {
    isPanning = false;
  });
}

function createEmptyDraft() {
  return {
    stacks: [1, 2, 3].map((actionNumber) => ({
      action_number: actionNumber,
      seal_mode: "sealed",
      cards: ["", ""],
      faces: ["front", "front"],
      targets: ["", ""],
      move_choices: ["forward", "forward"],
      modes: ["", ""],
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
    body: JSON.stringify({
      player_ids: ["red", "blue"],
      seed: 3,
    }),
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

  const available = [...(player.hand || [])];
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
    orientation: card.is_hybrid
      ? "up"
      : card.family === "move"
        ? (card.orientation_options?.length === 1 ? card.orientation_options[0] : DEMO_MOVE_CHOICES[actionNumber - 1])
        : "up",
  };
  if (cardNeedsTarget(card)) {
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
  const viewWidth = (extent * 2) / state.zoomScale;
  const viewHeight = (extent * 2) / state.zoomScale;
  const viewX = -extent / state.zoomScale + state.panOffsetX;
  const viewY = -extent / state.zoomScale + state.panOffsetY;
  svg.setAttribute("viewBox", `${viewX} ${viewY} ${viewWidth} ${viewHeight}`);

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
      .map((cardId, cardIndex) => {
        const card = cardById[cardId];
        return { card, cardIndex, family: effectiveCardFamily(card, stack, cardIndex) };
      })
      .filter((selection) => selection.card && selection.family);
    const family = selections[0]?.family;
    if (family === "move") {
      const passes = stack.seal_mode === "overdrive" ? 2 : 1;
      for (let pass = 0; pass < passes; pass += 1) {
        selections.forEach(({ card, cardIndex, family }) => {
          if (family !== "move") return;
          const before = { ...preview };
          const distance = previewSelectionMoveDistance(card, stack, cardIndex);
          const warpDestination = previewSelectionWarpDestination(card, stack, cardIndex);
          if (warpDestination) {
            applyPreviewWarp(game, player, preview, warpDestination);
          } else {
            applyPreviewMove(
              preview,
              distance,
              stack.move_choices[cardIndex],
            );
          }
          drawMovementPathPreview(svg, before, preview);
          const label = `${previewMoveLabel(stackIndex, cardIndex, distance, warpDestination)}${pass ? " OD" : ""}`;
          drawPositionPreview(svg, preview, label);
        });
      }
    } else if (family === "attack") {
      const firstAttack = selections.find(({ card, cardIndex, family }) => (
        family === "attack" && effectiveCardRequiresTarget(card, stack, cardIndex)
      ));
      const attacksAll = selections.some(({ card, cardIndex, family }) => (
        family === "attack" && previewSelectionAttacksAll(card, stack, cardIndex)
      ));
      const targets = attacksAll
        ? Object.values(game.players || {}).filter((candidate) => candidate.id !== state.builderPlayerId)
        : firstAttack && game.players[stack.targets[firstAttack.cardIndex]]
          ? [game.players[stack.targets[firstAttack.cardIndex]]]
          : [];
      targets.forEach((target) => {
        const attackSelections = selections.filter((selection) => selection.family === "attack");
        const damage = previewVolleyDamage(attackSelections, stack);
        const aimBonus = selections
          .filter((selection) => selection.family === "attack")
          .reduce((total, { card, cardIndex }) => total + previewSelectionAimBonus(card, stack, cardIndex), 0);
        const alwaysHits = selections.some(({ card, cardIndex, family }) => (
          family === "attack" && previewSelectionAlwaysHits(card, stack, cardIndex)
        ));
        drawAttackPreview(svg, preview, target, `A${stackIndex + 1}`, { damage, aimBonus, alwaysHits });
        if (stack.seal_mode === "overdrive") {
          drawAttackPreview(svg, preview, target, `A${stackIndex + 1} OD`, { damage, aimBonus, alwaysHits });
        }
      });
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
  const value = card.effect?.value ?? card.value ?? 0;
  return value;
}

function previewSelectionMoveDistance(card, stack, cardIndex) {
  if (selectedFace(card, stack, cardIndex) === "desperate" && card?.desperate_face) {
    return card.desperate_face.movement_disabled || card.desperate_face.warp_destination
      ? 0
      : card.desperate_face.value;
  }
  return previewCardValue(card, stack.seal_mode);
}

function previewSelectionWarpDestination(card, stack, cardIndex) {
  if (selectedFace(card, stack, cardIndex) === "desperate" && card?.desperate_face) {
    return card.desperate_face.warp_destination || "";
  }
  return "";
}

function previewSelectionAttackDamage(card, stack, cardIndex) {
  return previewSelectionAttackBaseDamage(card, stack, cardIndex)
    + previewSelectionAttackDamageBonus(card, stack, cardIndex);
}

function previewSelectionAttackBaseDamage(card, stack, cardIndex) {
  if (selectedFace(card, stack, cardIndex) === "desperate" && card?.desperate_face) {
    return card.desperate_face.value;
  }
  return (card.effect?.family ?? card.family) === "attack" ? 1 : 0;
}

function previewSelectionAttackDamageBonus(card, stack, cardIndex) {
  if (selectedFace(card, stack, cardIndex) === "desperate" && card?.desperate_face) {
    return card.desperate_face.damage_bonus || 0;
  }
  return 0;
}

function previewVolleyDamage(attackSelections, stack) {
  const baseDamage = Math.max(
    1,
    ...attackSelections.map(({ card, cardIndex }) => previewSelectionAttackBaseDamage(card, stack, cardIndex)),
  );
  const damageBonus = attackSelections.reduce(
    (total, { card, cardIndex }) => total + previewSelectionAttackDamageBonus(card, stack, cardIndex),
    0,
  );
  return baseDamage + damageBonus;
}

function previewSelectionAimBonus(card, stack, cardIndex) {
  if (selectedFace(card, stack, cardIndex) === "desperate" && card?.desperate_face) {
    return card.desperate_face.aim_bonus || 0;
  }
  const family = card.effect?.family ?? card.family;
  if (family === "attack") {
    return previewCardValue(card, stack.seal_mode);
  }
  return 0;
}

function previewSelectionAlwaysHits(card, stack, cardIndex) {
  return Boolean(selectedFace(card, stack, cardIndex) === "desperate" && card?.desperate_face?.always_hits);
}

function previewSelectionAttacksAll(card, stack, cardIndex) {
  return Boolean(selectedFace(card, stack, cardIndex) === "desperate" && card?.desperate_face?.attacks_all);
}

function previewMoveLabel(stackIndex, cardIndex, distance, warpDestination = "") {
  const base = `A${stackIndex + 1}.${cardIndex + 1}`;
  if (warpDestination) return `${base} W`;
  return distance > 0 ? `${base} M${distance}` : base;
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

function applyPreviewWarp(game, player, preview, destination) {
  let target = null;
  if (destination === "home") {
    target = previewHomeStart(game, player);
  } else if (destination === "bauble") {
    target = previewBaubleWarpTarget(game, preview);
  } else if (destination === "leader") {
    target = previewLeaderWarpTarget(game, player);
  }
  if (!target) return;
  preview.q = target.q;
  preview.r = target.r;
  if (target.facing !== undefined) {
    preview.facing = target.facing;
  }
}

function previewHomeStart(game, player) {
  const playerIds = Object.keys(game.players || {});
  const index = Math.max(0, playerIds.indexOf(player.id));
  const cornerDirection = START_CORNER_DIRECTIONS[index] ?? START_CORNER_DIRECTIONS[0];
  const distanceFromCenter = BOARD_RADIUS - 3;
  const [dq, dr] = AXIAL_DIRECTIONS[cornerDirection];
  return { q: dq * distanceFromCenter, r: dr * distanceFromCenter };
}

function previewBaubleWarpTarget(game, preview) {
  const numbered = (game.baubles || []).filter((bauble) => !bauble.is_fang);
  const active = numbered.filter((bauble) => bauble.number === game.round_number);
  const candidates = active.length ? active : numbered;
  if (!candidates.length) return null;
  return [...candidates].sort((left, right) => (
    hexDistance(preview.q, preview.r, left.q, left.r) - hexDistance(preview.q, preview.r, right.q, right.r)
    || left.number - right.number
    || String(left.id).localeCompare(String(right.id))
  ))[0];
}

function previewLeaderWarpTarget(game, player) {
  const orderedIds = playerOrderFromStartingPlayer(game);
  let candidates = orderedIds
    .map((playerId) => game.players[playerId])
    .filter((candidate) => candidate && candidate.id !== player.id && !candidate.eliminated);
  if (!candidates.length) {
    candidates = orderedIds.map((playerId) => game.players[playerId]).filter((candidate) => candidate && !candidate.eliminated);
  }
  if (!candidates.length) return null;
  const leader = [...candidates].sort((left, right) => (
    right.victory_points - left.victory_points
    || orderedIds.indexOf(left.id) - orderedIds.indexOf(right.id)
  ))[0].ship;
  const [dq, dr] = AXIAL_DIRECTIONS[(leader.facing + 3) % 6];
  const behind = clampToBoard(leader.q + dq, leader.r + dr);
  return { q: behind.q, r: behind.r, facing: leader.facing };
}

function playerOrderFromStartingPlayer(game) {
  const playerIds = Object.keys(game.players || {});
  const startingIndex = Math.max(0, playerIds.indexOf(game.starting_player_id));
  return playerIds.slice(startingIndex).concat(playerIds.slice(0, startingIndex));
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

function drawAttackPreview(svg, shooterPreview, target, labelText, attackPreview) {
  const [sourceX, sourceY] = axialToPixel(shooterPreview.q, shooterPreview.r);
  const [targetX, targetY] = axialToPixel(target.ship.q, target.ship.r);
  const color = SHIP_COLORS[target.id] || "#6f5ab8";
  const defense = hexDistance(shooterPreview.q, shooterPreview.r, target.ship.q, target.ship.r);
  const damage = attackPreview.damage || 0;
  const aimBonus = attackPreview.aimBonus || 0;
  const targetRoll = Math.max(0, defense - aimBonus);
  const targetText = attackPreview.alwaysHits
    ? "HIT"
    : aimBonus
      ? `${targetRoll}+ (+${aimBonus} Aim)`
      : `${targetRoll}+`;
  const group = svgEl("g");
  group.setAttribute("class", aimBonus || attackPreview.alwaysHits ? "volley-preview bonus-preview" : "volley-preview");

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
  label.textContent = `${labelText} ROLL ${targetText} DMG ${damage}`;

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
        <div><dt>Hand</dt><dd>${player.hand?.length ?? 0}</dd></div>
        <div><dt>Discard</dt><dd>${player.discard?.length ?? 0}</dd></div>
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
    [...(player.deck || []), ...(player.hand || []), ...(player.discard || []), ...(player.overheat || [])].forEach((card) => {
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
  const visibleCards = Object.fromEntries(
    [...(player?.deck || []), ...(player?.hand || []), ...(player?.discard || []), ...(player?.overheat || [])]
      .map((card) => [card.id, card]),
  );
  const merged = { ...state.knownCards, ...visibleCards };
  Object.entries(merged).forEach(([cardId, card]) => {
    if (!card || cardId === undefined) return;
    if (card.is_hybrid === undefined) {
      merged[cardId] = { ...card, is_hybrid: inferCardFromId(cardId).is_hybrid };
    }
  });
  return merged;
}

function cardsForBuilder(player) {
  const byId = cardLookupForPlayer(player);
  const cards = [...(player?.hand || [])];
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
  const isHybrid = cardId.startsWith("desp_ace_shot") || cardId.startsWith("desp_deadeye") || cardId.startsWith("desp_nightjammer") || cardId.startsWith("desp_self_destruct") || cardId.startsWith("desp_death_blossom") || cardId.startsWith("desp_steady_shot");
  const family = isHybrid ? "hybrid" : cardId.startsWith("attack") || cardId.startsWith("desp_targeted_attack") ? "attack" : "move";
  const value = Number(cardId.match(/_(\d+)_/)?.[1] || 1);
  const name = family === "attack" ? `Targeted Attack ${value}` : family === "hybrid" ? `Hybrid Card ${value}` : `Controlled Move ${value}`;
  const requiresTarget = family === "attack" && !cardId.startsWith("desp_") ? true : cardId.startsWith("desp_targeted_attack");
  return {
    id: cardId,
    name,
    family,
    value,
    is_base: true,
    requires_target: requiresTarget,
    is_hybrid: isHybrid,
    effect: { family, value, requires_target: requiresTarget, is_hybrid: isHybrid },
  };
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
  const face = selectedFace(selectedCard, stack, cardIndex);
  const family = effectiveCardFamily(selectedCard, stack, cardIndex);
  const desperateTone = face === "desperate" ? `desperate-card desperate-${family}-card` : "";
  const cardTone = face === "desperate"
    ? desperateTone
    : selectedCard?.is_hybrid && face !== "desperate"
      ? "hybrid-card"
      : family === "attack"
        ? "attack-card"
        : family === "move" ? "move-card" : "";
  const detail = selectedCard
    ? face === "desperate"
      ? desperateFaceLabel(selectedCard)
      : selectedCard.is_hybrid
      ? hybridModeLabel(stack.modes[cardIndex])
      : selectedCard.family === "attack"
        ? effectiveCardRequiresTarget(selectedCard, stack, cardIndex)
          ? targetChoiceLabel(stack.targets[cardIndex])
          : "Pairs with targeted attack"
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
    <button class="hex-choice-summary ${desperateTone}" type="button" data-stack="${stackIndex}" data-card="${cardIndex}"${
      readOnly ? " disabled" : ""
    }>
      ${detail}
    </button>
  `;
  return slot;
}

function cardNeedsTarget(card) {
  const family = card?.effect?.family ?? card?.family;
  const requiresTarget = card?.effect?.requires_target ?? card?.requires_target;
  return Boolean(family === "attack" && requiresTarget !== false);
}

function selectedFace(card, stack, cardIndex) {
  if (!card?.desperate_face) return "front";
  return stack?.faces?.[cardIndex] === "desperate" ? "desperate" : "front";
}

function effectiveCardRequiresTarget(card, stack, cardIndex) {
  if (!card) return false;
  if (selectedFace(card, stack, cardIndex) === "desperate") {
    return Boolean(card.desperate_face?.requires_target);
  }
  return cardNeedsTarget(card);
}

function effectiveCardFamily(card, stack, cardIndex) {
  if (!card) return "";
  if (selectedFace(card, stack, cardIndex) === "desperate") return card.desperate_face?.family || "";
  if (card.is_hybrid) return stack?.modes?.[cardIndex] || "";
  return card.effect?.family ?? card.family;
}

function stackLockedFamily(stack, cardById, excludingCardIndex = null) {
  return stack.cards
    .map((cardId, index) => (
      index === excludingCardIndex ? "" : effectiveCardFamily(cardById[cardId], stack, index)
    ))
    .find(Boolean) || "";
}

function stackHasTargetedAttack(stack, cardById, excludingCardIndex = null) {
  return stack.cards.some((cardId, index) => {
    if (index === excludingCardIndex) return false;
    const card = cardById[cardId];
    return effectiveCardFamily(card, stack, index) === "attack" && effectiveCardRequiresTarget(card, stack, index);
  });
}

function cardUseChoices(card, stack, cardById, cardIndex) {
  const lockedFamily = stackLockedFamily(stack, cardById, cardIndex);
  const hasTargetedPartner = stackHasTargetedAttack(stack, cardById, cardIndex);
  const choices = [];

  function familyAllowed(family) {
    return !lockedFamily || lockedFamily === family;
  }

  if (card.is_hybrid) {
    choices.push({
      face: "front",
      mode: "move",
      family: "move",
      label: "Basic Move",
      mark: "M",
      fill: "#3f9963",
      disabled: !familyAllowed("move"),
    });
    choices.push({
      face: "front",
      mode: "attack",
      family: "attack",
      label: "Basic Attack",
      mark: "A",
      fill: "#c9433f",
      disabled: !hasTargetedPartner || !familyAllowed("attack"),
    });
  }

  if (card.desperate_face) {
    const family = card.desperate_face.family;
    const requiresTarget = Boolean(card.desperate_face.requires_target);
    const attacksAll = Boolean(card.desperate_face.attacks_all);
    const needsTargetedPartner = family === "attack" && !requiresTarget && !attacksAll;
    choices.push({
      face: "desperate",
      mode: "",
      family,
      label: `${card.name} Desperate`,
      mark: family === "attack" ? "D" : "M",
      fill: family === "attack" ? "#c9433f" : "#3f9963",
      isDesperate: true,
      desperateFamily: family,
      disabled: !familyAllowed(family) || (needsTargetedPartner && !hasTargetedPartner),
    });
  }

  if (!card.is_hybrid && !card.desperate_face) {
    const family = card.family;
    const needsTargetedPartner = family === "attack" && card.requires_target === false;
    choices.push({
      face: "front",
      mode: "",
      family,
      label: family === "attack" ? "Attack" : "Move",
      mark: family === "attack" ? "A" : "M",
      fill: family === "attack" ? "#c9433f" : "#3f9963",
      disabled: !familyAllowed(family) || (needsTargetedPartner && !hasTargetedPartner),
    });
  } else if (!card.is_hybrid && card.family === "move") {
    choices.unshift({
      face: "front",
      mode: "",
      family: "move",
      label: "Basic Move",
      mark: "M",
      fill: "#3f9963",
      disabled: !familyAllowed("move"),
    });
  } else if (!card.is_hybrid && card.family === "attack") {
    const needsTargetedPartner = card.requires_target === false;
    choices.unshift({
      face: "front",
      mode: "",
      family: "attack",
      label: "Basic Attack",
      mark: "A",
      fill: "#c9433f",
      disabled: !familyAllowed("attack") || (needsTargetedPartner && !hasTargetedPartner),
    });
  }

  return choices;
}

function hybridModeLabel(mode) {
  return mode === "attack" ? "Attack mode" : mode === "move" ? "Move mode" : "Choose mode";
}

function desperateFaceLabel(card) {
  const face = card?.desperate_face;
  if (!face) return "Basic";
  if (face.family === "move") {
    if (face.warp_destination) {
      const destination = titleCase(face.warp_destination);
      const defense = face.defense_bonus ? `, +${face.defense_bonus} Defense` : "";
      return `Desperate: Warp ${destination}${defense}`;
    }
    if (face.movement_disabled) return `Desperate: +${face.defense_bonus} Defense`;
    return `Desperate: Move ${face.value}`;
  }
  const parts = [];
  if (face.attacks_all) parts.push("Attack all");
  if (face.fixed_defense_threshold) parts.push(`Defense ${face.fixed_defense_threshold}`);
  if (face.max_range) parts.push(`Range ${face.max_range}`);
  if (face.aim_bonus) parts.push(`+${face.aim_bonus} Aim`);
  if (face.value) parts.push(`Damage ${face.value}`);
  if (face.damage_bonus) parts.push(`+${face.damage_bonus} Damage`);
  if (face.always_hits) parts.push("Always hits");
  return `Desperate: ${parts.join(", ") || "Attack mod"}`;
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

function clearCardSlot(stackIndex, cardIndex) {
  const stack = state.builderDraft.stacks[stackIndex];
  if (!stack) return;
  stack.cards[cardIndex] = "";
  stack.faces[cardIndex] = "front";
  stack.targets[cardIndex] = "";
  stack.move_choices[cardIndex] = "forward";
  stack.modes[cardIndex] = "";
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
      <div class="picker-column desperation-column">
        <h3>Desperation</h3>
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
    desperation: panel.querySelector(".desperation-column"),
  };

  ["move", "attack", "desperation"].forEach((family) => {
    const cards = availableCards.filter((card) => {
      if (family === "desperation") return card.is_base === false;
      return card.is_base !== false && card.family === family;
    });
    if (cards.length === 0) {
      const empty = document.createElement("p");
      empty.className = "picker-empty";
      empty.textContent = "No cards";
      columns[family].append(empty);
    }
    cards.forEach((card) => {
      const choices = cardUseChoices(card, stack, cardById, cardIndex);
      const isUsedElsewhere = selectedIds.includes(card.id) && stack.cards[cardIndex] !== card.id;
      const hasLegalChoice = choices.some((choice) => !choice.disabled);
      const button = document.createElement("button");
      button.type = "button";
      button.className = `picker-card ${family === "move" ? "move-card" : family === "desperation" ? "hybrid-card" : "attack-card"}`;
      button.disabled = isUsedElsewhere || !hasLegalChoice;
      button.innerHTML = `
        <strong>${card.name}</strong>
        <span>${card.id}</span>
        <b>${card.value}</b>
      `;
      button.addEventListener("click", () => {
        if (card.is_hybrid || card.desperate_face) {
          showCardUseChoicePanel(stackIndex, cardIndex, card.id);
          return;
        }
        const choice = choices.find((candidate) => !candidate.disabled);
        selectBuilderCardUse(stackIndex, cardIndex, card.id, choice);
      });
      columns[family].append(button);
    });
  });

  overlay.append(panel);
  overlay.classList.add("visible");
}

function selectBuilderCardUse(stackIndex, cardIndex, cardId, choice) {
  const stack = state.builderDraft.stacks[stackIndex];
  if (!stack) return;
  stack.cards[cardIndex] = cardId;
  stack.faces[cardIndex] = choice?.face || "front";
  stack.targets[cardIndex] = "";
  stack.move_choices[cardIndex] = "forward";
  stack.modes[cardIndex] = choice?.mode || "";
  applyDefaultAttackTarget(stack, cardIndex);
  hideCardPickerOverlay();
  renderAll();
  showFollowupChoicePanel(stackIndex, cardIndex);
}

function clearActionStack(stackIndex) {
  const stack = state.builderDraft.stacks[stackIndex];
  if (!stack) return;
  stack.seal_mode = "sealed";
  stack.cards = ["", ""];
  stack.faces = ["front", "front"];
  stack.targets = ["", ""];
  stack.move_choices = ["forward", "forward"];
  stack.modes = ["", ""];
  renderAll();
}

function moveChoicesForCard(card, stack = null, cardIndex = null) {
  if (!card) return MOVE_CHOICES;
  const face = cardIndex === null ? "front" : selectedFace(card, stack, cardIndex);
  const options = face === "desperate"
    ? card.desperate_face?.orientation_options
    : (card.effect?.orientation_options ?? card.orientation_options);
  if (options && options.length === 1) {
    return [{ value: options[0], label: "Forward", mark: "F" }];
  }
  return MOVE_CHOICES;
}

function showCardUseChoicePanel(stackIndex, cardIndex, cardId) {
  const game = state.selectedState;
  const player = game?.players?.[state.builderPlayerId];
  const stack = state.builderDraft.stacks[stackIndex];
  const cardById = cardLookupForPlayer(player);
  const card = cardById[cardId];
  if (!game || !player || !stack || !card || !canSubmit(state.builderPlayerId)) return;

  const overlay = cardPickerOverlayElement();
  overlay.replaceChildren();
  const panel = document.createElement("section");
  panel.className = "hex-choice-panel";
  panel.innerHTML = `
    <div class="card-picker-header">
      <span>${card.name}</span>
      <button type="button" aria-label="Dismiss choice panel">&times;</button>
    </div>
    <div class="hex-choice-grid"></div>
  `;
  panel.querySelector(".card-picker-header button").addEventListener("click", hideCardPickerOverlay);
  const grid = panel.querySelector(".hex-choice-grid");
  cardUseChoices(card, stack, cardById, cardIndex).forEach((choice) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = `hex-choice ${choice.isDesperate ? `desperate-choice desperate-${choice.desperateFamily}-choice` : ""} ${choice.disabled ? "disabled-choice" : ""}`;
    button.disabled = Boolean(choice.disabled);
    button.style.setProperty("--choice-fill", choice.fill);
    button.innerHTML = `
      <span class="choice-hex">${choice.mark}</span>
      <strong>${choice.label}</strong>
    `;
    button.addEventListener("click", () => {
      selectBuilderCardUse(stackIndex, cardIndex, card.id, choice);
    });
    grid.append(button);
  });
  overlay.append(panel);
  overlay.classList.add("visible");
}

function showFollowupChoicePanel(stackIndex, cardIndex) {
  const game = state.selectedState;
  const player = game?.players?.[state.builderPlayerId];
  const stack = state.builderDraft.stacks[stackIndex];
  const card = cardLookupForPlayer(player)[stack?.cards?.[cardIndex]];
  if (!game || !player || !stack || !card || !canSubmit(state.builderPlayerId)) return;

  const family = effectiveCardFamily(card, stack, cardIndex);
  if (family === "attack") {
    if (effectiveCardRequiresTarget(card, stack, cardIndex)) showHexChoicePanel(stackIndex, cardIndex);
    return;
  }

  if (family === "move" && moveChoicesForCard(card, stack, cardIndex).length > 1) {
    showHexChoicePanel(stackIndex, cardIndex);
  }
}

function showHexChoicePanel(stackIndex, cardIndex) {
  const game = state.selectedState;
  const player = game?.players?.[state.builderPlayerId];
  const stack = state.builderDraft.stacks[stackIndex];
  const card = cardLookupForPlayer(player)[stack?.cards?.[cardIndex]];
  if (!game || !player || !stack || !card || !canSubmit(state.builderPlayerId)) return;
  const face = selectedFace(card, stack, cardIndex);
  const family = effectiveCardFamily(card, stack, cardIndex);
  if (card.is_hybrid && face !== "desperate" && !stack.modes[cardIndex]) {
    return;
  }
  if (family === "attack" && !effectiveCardRequiresTarget(card, stack, cardIndex)) {
    return;
  }

  const overlay = cardPickerOverlayElement();
  overlay.replaceChildren();

  const panel = document.createElement("section");
  panel.className = "hex-choice-panel";
  panel.innerHTML = `
    <div class="card-picker-header">
      <span>${family === "attack" ? "Choose Target" : "Choose Move"}</span>
      <button type="button" aria-label="Dismiss choice panel">&times;</button>
    </div>
    <div class="hex-choice-grid"></div>
  `;
  panel.querySelector(".card-picker-header button").addEventListener("click", hideCardPickerOverlay);
  const grid = panel.querySelector(".hex-choice-grid");

  const choices = family === "attack"
    ? attackHexChoices(game)
    : moveChoicesForCard(card, stack, cardIndex);
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
      if (family === "attack") {
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
          const face = selectedFace(card, stack, cardIndex);
          const family = effectiveCardFamily(card, stack, cardIndex);
          const selection = {
            card_id: cardId,
            face,
            orientation: family === "move"
              ? stack.move_choices[cardIndex]
              : "up",
            mode: card?.is_hybrid && face !== "desperate" ? stack.modes[cardIndex] : undefined,
          };
          if (effectiveCardRequiresTarget(card, stack, cardIndex)) {
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

  const cardById = Object.fromEntries((player.hand || []).map((card) => [card.id, card]));
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
      const family = effectiveCardFamily(card, stack, cardIndex);
      if (!family) return { ok: false, message: `${cardId} needs a mode or face selection.` };
      families.add(family);
      if (effectiveCardRequiresTarget(card, stack, cardIndex)) {
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
    stack.faces[cardIndex] = "front";
    stack.targets[cardIndex] = "";
    stack.move_choices[cardIndex] = "forward";
    stack.modes[cardIndex] = "";
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
  if (effectiveCardRequiresTarget(card, stack, cardIndex) && opponents.length === 1) {
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
    showFollowupChoicePanel(stackIndex, cardIndex);
  }
});
elements.revealOrdersToggle.addEventListener("change", () => {
  if (state.selectedGameId) selectGame(state.selectedGameId).catch(showError);
});

function showError(error) {
  alert(error.message);
}

function showCombatResultOverlay(game, previousEventCount) {
  const steps = latestResolutionSteps(game, previousEventCount);
  if (steps.length === 0) return;

  const overlay = combatOverlayElement();
  overlay.replaceChildren();

  let currentStepIndex = 0;
  const renderStep = () => {
    const step = steps[currentStepIndex];
    overlay.replaceChildren();
    const panel = document.createElement("section");
    panel.className = "combat-result-panel";
    panel.innerHTML = `
      <div class="combat-result-header">
        <span>Action ${step.actionNumber} - ${step.label}</span>
        <button type="button" aria-label="Dismiss combat result">&times;</button>
      </div>
      <div class="combat-result-list"></div>
      <div class="combat-result-actions">
        <button type="button">${currentStepIndex < steps.length - 1 ? "Advance" : "Close"}</button>
      </div>
    `;
    const list = panel.querySelector(".combat-result-list");
    step.render(list);
    panel.querySelector(".combat-result-header button").addEventListener("click", hideCombatResultOverlay);
    panel.querySelector(".combat-result-actions button").addEventListener("click", () => {
      if (currentStepIndex < steps.length - 1) {
        currentStepIndex += 1;
        renderStep();
      } else {
        hideCombatResultOverlay();
      }
    });
    overlay.append(panel);
    overlay.classList.add("visible");
  };
  renderStep();
}

function renderMovementResults(list, movements) {
  movements.forEach((movement) => {
    const item = document.createElement("article");
    item.className = "combat-result-item";
    item.innerHTML = `
      <strong>${movement.player_id}</strong>
      <span class="combat-result-summary">${movement.steps.length} movement step${movement.steps.length === 1 ? "" : "s"}</span>
      <div class="combat-result-breakdown">
        ${movement.steps.map(formatMovementStep).join("")}
      </div>
    `;
    list.append(item);
  });
}

function formatMovementStep(step) {
  const before = step.before || {};
  const after = step.after || {};
  const destination = step.warp_destination
    ? `Warp ${titleCase(step.warp_destination)}`
    : step.distance > 0
      ? `Move ${step.distance}`
      : "No movement";
  const defense = step.defense_bonus ? `, +${step.defense_bonus} Defense` : "";
  return `<span>${step.card_id}: ${destination}${defense} (${before.q}, ${before.r}) -> (${after.q}, ${after.r}), facing ${after.facing}</span>`;
}

function renderVolleyResults(list, volleys) {
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
}

function latestResolutionSteps(game, previousEventCount) {
  const events = (game?.event_log || []).slice(previousEventCount);
  const movementEvents = events.filter((event) => event.type === "movement_resolved");
  const volleyEvents = events.filter((event) => event.type === "volley_resolved");
  const latest = [...movementEvents, ...volleyEvents].at(-1);
  if (!latest) return [];

  const movements = movementEvents.filter(
    (event) => event.round === latest.round && event.action_number === latest.action_number,
  );
  const volleys = volleyEvents.filter(
    (event) => event.round === latest.round && event.action_number === latest.action_number,
  );
  const steps = [];
  if (movements.length) {
    steps.push({
      actionNumber: latest.action_number,
      label: "Movement",
      render: (list) => renderMovementResults(list, movements),
    });
  }
  if (volleys.length) {
    steps.push({
      actionNumber: latest.action_number,
      label: "Attacks",
      render: (list) => renderVolleyResults(list, volleys),
    });
  }
  return steps;
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
    <span class="mini-stat" title="Cards in hand"><span class="mini-icon hand-icon">H</span>${player ? (player.hand?.length ?? 0) : 0}</span>
    <span class="mini-stat" title="Cards in deck"><span class="mini-icon deck-icon">D</span>${player ? player.deck.length : 0}</span>
    <span class="mini-stat" title="Cards in discard"><span class="mini-icon discard-icon">X</span>${player ? (player.discard?.length ?? 0) : 0}</span>
    <span class="mini-stat" title="Cards in overheat"><span class="mini-icon overheat-icon">O</span>${player ? player.overheat.length : 0}</span>
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
