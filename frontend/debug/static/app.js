const state = {
  games: [],
  selectedGameId: null,
  selectedState: null,
  builderPlayerId: "red",
  debugDesperationCardId: "",
  builderDraft: createEmptyDraft(),
  knownCards: {},
  selectedAiType: "bauble_runner",
  selectedAiTypes: {
    red: "bauble_runner",
    blue: "bauble_runner",
    green: "bauble_runner",
    yellow: "bauble_runner",
  },
  dismissedEndGameFor: null,
  playbackSpeed: "normal",
  autoPlaying: false,
  aiTargets: {},
  theme: "light",
  // New properties for board interaction
  zoomScale: 1,
  panOffsetX: 0,
  panOffsetY: 0,
  isPhone: false,
  mobileCardSheetOpen: false,
  mobileStatusOpen: false,
  mobileStatusPlayerId: "",
  mobileBoardInitialized: false,
  lastDeviceDiagnosticsKey: "",
  resolving: false,
};

const BOARD_RADIUS = 14;
const HEX_SIZE = 14;
const SQRT3 = Math.sqrt(3);
const DEMO_MOVE_CHOICES = ["forward", "turn_left", "turn_right"];
const AI_TYPES = {
  bauble_runner: "Bauble Runner",
  hunter_killer: "Hunter-Killer",
  blaster: "Blaster",
};
const MOVE_CHOICES = [
  { value: "forward", label: "Forward", mark: "F" },
  { value: "turn_left", label: "Turn Left, Move", mark: "L" },
  { value: "turn_right", label: "Turn Right, Move", mark: "R" },
  { value: "slip_left", label: "Side Slip Left", mark: "SL" },
  { value: "slip_right", label: "Side Slip Right", mark: "SR" },
  { value: "u_turn_move", label: "U-Turn Move", mark: "U" },
  { value: "u_turn_attack", label: "U-Turn Attack", mark: "UA" },
];
const MOVE_CHOICE_BY_VALUE = Object.fromEntries(MOVE_CHOICES.map((choice) => [choice.value, choice]));
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

function hasOverheatPile(game) {
  return game?.rules_config?.overheat_pile !== false;
}

const elements = {
  createButton: document.querySelector("#createButton"),
  createGameControls: document.querySelector("#createGameControls"),
  themeToggleButton: document.querySelector("#themeToggleButton"),
  refreshButton: document.querySelector("#refreshButton"),
  actionLog: document.querySelector("#actionLog") || document.querySelector("#gamesList"),
  exportLogButton: document.querySelector("#exportLogButton"),
  gameCount: document.querySelector("#gameCount"),
  selectedGameId: document.querySelector("#selectedGameId"),
  roundValue: document.querySelector("#roundValue"),
  phaseValue: document.querySelector("#phaseValue"),
  startingPlayerValue: document.querySelector("#startingPlayerValue"),
  aiControls: document.querySelector("#aiControls"),
  playbackSpeedSelect: document.querySelector("#playbackSpeedSelect"),
  redOrdersButton: document.querySelector("#redOrdersButton"),
  blueOrdersButton: document.querySelector("#blueOrdersButton"),
  aiTypeSelect: document.querySelector("#aiTypeSelect"),
  redAiTypeSelect: document.querySelector("#redAiTypeSelect"),
  blueAiTypeSelect: document.querySelector("#blueAiTypeSelect"),
  resolveButton: document.querySelector("#resolveButton"),
  finishedGameActions: document.querySelector("#finishedGameActions"),
  replayGameButton: document.querySelector("#replayGameButton"),
  resultsSummaryButton: document.querySelector("#resultsSummaryButton"),
  revealOrdersToggle: document.querySelector("#revealOrdersToggle"),
  builderPlayerSelect: document.querySelector("#builderPlayerSelect"),
  debugDesperationSelect: document.querySelector("#debugDesperationSelect"),
  debugDrawDesperationButton: document.querySelector("#debugDrawDesperationButton"),
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
  endGameOverlay: null,
  cardPickerOverlay: null,
  resolutionCallout: null,
  mobileControls: null,
  mobileOrdersCloseButton: null,
  mobileStatusCloseButton: null,
  // Zoom button handlers
  boardZoomOutButton: document.querySelector("#boardZoomOutButton"),
  boardZoomInButton: document.querySelector("#boardZoomInButton"),
};

function detectPhoneLayout() {
  const coarsePointer = window.matchMedia?.("(pointer: coarse)")?.matches;
  const anyCoarsePointer = window.matchMedia?.("(any-pointer: coarse)")?.matches;
  const narrowViewport = window.matchMedia?.("(max-width: 760px)")?.matches;
  const tabletViewport = window.matchMedia?.("(max-width: 1366px)")?.matches;
  const compactHeight = window.matchMedia?.("(max-height: 620px)")?.matches;
  const mobileAgent = /Android|iPhone|iPod|IEMobile|Mobile/i.test(navigator.userAgent || "");
  const touchCapable = (navigator.maxTouchPoints || 0) > 0;
  return Boolean(
    ((coarsePointer || anyCoarsePointer || touchCapable) && tabletViewport)
    || (mobileAgent && (narrowViewport || compactHeight)),
  );
}

function applyDeviceMode() {
  const wasPhone = state.isPhone;
  state.isPhone = detectPhoneLayout();
  document.documentElement.dataset.device = state.isPhone ? "phone" : "desktop";
  document.body.classList.toggle("mobile-orders-open", state.isPhone && state.mobileCardSheetOpen);
  document.body.classList.toggle("mobile-status-open", state.isPhone && state.mobileStatusOpen);
  ensureMobileControls();
  if (state.isPhone && !wasPhone) resetMobileBoardView();
  if (!state.isPhone) {
    state.mobileCardSheetOpen = false;
    state.mobileStatusOpen = false;
    document.body.classList.remove("mobile-orders-open", "mobile-status-open");
  }
  renderMobileControls();
  reportDeviceDiagnostics("applyDeviceMode");
}

function mediaMatches(query) {
  return Boolean(window.matchMedia?.(query)?.matches);
}

function collectDeviceDiagnostics(reason) {
  return {
    reason,
    data_device: document.documentElement.dataset.device || "",
    detected_phone_layout: state.isPhone,
    user_agent: navigator.userAgent || "",
    platform: navigator.platform || "",
    vendor: navigator.vendor || "",
    max_touch_points: navigator.maxTouchPoints || 0,
    device_pixel_ratio: window.devicePixelRatio || 1,
    inner_width: window.innerWidth,
    inner_height: window.innerHeight,
    outer_width: window.outerWidth,
    outer_height: window.outerHeight,
    screen_width: window.screen?.width,
    screen_height: window.screen?.height,
    avail_width: window.screen?.availWidth,
    avail_height: window.screen?.availHeight,
    visual_viewport_width: window.visualViewport?.width,
    visual_viewport_height: window.visualViewport?.height,
    orientation_type: window.screen?.orientation?.type || "",
    pointer_coarse: mediaMatches("(pointer: coarse)"),
    pointer_fine: mediaMatches("(pointer: fine)"),
    any_pointer_coarse: mediaMatches("(any-pointer: coarse)"),
    any_pointer_fine: mediaMatches("(any-pointer: fine)"),
    hover_hover: mediaMatches("(hover: hover)"),
    any_hover_hover: mediaMatches("(any-hover: hover)"),
    max_width_760: mediaMatches("(max-width: 760px)"),
    max_width_900: mediaMatches("(max-width: 900px)"),
    max_width_1024: mediaMatches("(max-width: 1024px)"),
    max_width_1180: mediaMatches("(max-width: 1180px)"),
    max_width_1366: mediaMatches("(max-width: 1366px)"),
    max_height_620: mediaMatches("(max-height: 620px)"),
  };
}

function deviceDiagnosticsKey(diagnostics) {
  return [
    diagnostics.data_device,
    diagnostics.inner_width,
    diagnostics.inner_height,
    diagnostics.max_touch_points,
    diagnostics.pointer_coarse,
    diagnostics.any_pointer_coarse,
    diagnostics.max_width_1366,
  ].join("|");
}

function reportDeviceDiagnostics(reason) {
  const diagnostics = collectDeviceDiagnostics(reason);
  const key = deviceDiagnosticsKey(diagnostics);
  if (key === state.lastDeviceDiagnosticsKey) return;
  state.lastDeviceDiagnosticsKey = key;
  console.info("[StarShot device diagnostics]", diagnostics);
  fetch("/api/debug/device-info", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(diagnostics),
    keepalive: true,
  }).catch((error) => {
    console.warn("[StarShot device diagnostics] server log failed", error);
  });
}

function resetMobileBoardView() {
  state.zoomScale = 1;
  state.panOffsetX = 0;
  state.panOffsetY = 0;
  state.mobileBoardInitialized = true;
  renderBoard(state.selectedState);
}

function ensureMobileControls() {
  if (!elements.mobileControls) {
    const controls = document.createElement("nav");
    controls.className = "mobile-game-controls";
    controls.setAttribute("aria-label", "Mobile game controls");
    controls.innerHTML = `
      <button type="button" data-mobile-action="orders">Orders</button>
      <button type="button" data-mobile-action="status">Ships</button>
      <button type="button" data-mobile-action="center">Center</button>
    `;
    controls.addEventListener("click", (event) => {
      const button = event.target.closest("[data-mobile-action]");
      if (!button) return;
      if (button.dataset.mobileAction === "orders") toggleMobileOrders();
      if (button.dataset.mobileAction === "status") toggleMobileStatus();
      if (button.dataset.mobileAction === "center") resetMobileBoardView();
    });
    document.body.append(controls);
    elements.mobileControls = controls;
  }

  if (!elements.mobileOrdersCloseButton) {
    const button = document.createElement("button");
    button.className = "mobile-sheet-close";
    button.type = "button";
    button.textContent = "Map";
    button.addEventListener("click", () => setMobileOrdersOpen(false));
    const ordersBuilder = document.querySelector(".orders-builder");
    ordersBuilder?.prepend(button);
    elements.mobileOrdersCloseButton = button;
  }

  if (!elements.mobileStatusCloseButton) {
    const button = document.createElement("button");
    button.className = "mobile-sheet-close";
    button.type = "button";
    button.textContent = "Map";
    button.addEventListener("click", () => setMobileStatusOpen(false));
    document.querySelector(".player-rail")?.prepend(button);
    elements.mobileStatusCloseButton = button;
  }
}

function renderMobileControls() {
  if (!elements.mobileControls) return;
  const ordersButton = elements.mobileControls.querySelector("[data-mobile-action='orders']");
  const statusButton = elements.mobileControls.querySelector("[data-mobile-action='status']");
  if (ordersButton) ordersButton.setAttribute("aria-pressed", String(state.mobileCardSheetOpen));
  if (statusButton) statusButton.setAttribute("aria-pressed", String(state.mobileStatusOpen));
}

function toggleMobileOrders() {
  setMobileOrdersOpen(!state.mobileCardSheetOpen);
}

function setMobileOrdersOpen(isOpen) {
  state.mobileCardSheetOpen = Boolean(isOpen);
  if (state.mobileCardSheetOpen) state.mobileStatusOpen = false;
  applyDeviceMode();
}

function toggleMobileStatus(playerId = "") {
  state.mobileStatusPlayerId = playerId || state.mobileStatusPlayerId;
  setMobileStatusOpen(!state.mobileStatusOpen || Boolean(playerId));
}

function setMobileStatusOpen(isOpen) {
  state.mobileStatusOpen = Boolean(isOpen);
  if (state.mobileStatusOpen) state.mobileCardSheetOpen = false;
  applyDeviceMode();
}

applyDeviceMode();
window.addEventListener("resize", applyDeviceMode);
window.addEventListener("orientationchange", () => {
  window.setTimeout(() => {
    applyDeviceMode();
    if (state.isPhone) resetMobileBoardView();
  }, 150);
});

function initialTheme() {
  const stored = window.localStorage?.getItem("starshotTheme");
  if (stored === "dark" || stored === "light") return stored;
  if (window.matchMedia?.("(prefers-color-scheme: dark)")?.matches) return "dark";
  return "light";
}

function applyTheme(theme) {
  state.theme = theme;
  document.documentElement.dataset.theme = theme;
  document.documentElement.style.colorScheme = theme;
  if (elements.themeToggleButton) {
    elements.themeToggleButton.textContent = theme === "dark" ? "Light Mode" : "Dark Mode";
    elements.themeToggleButton.setAttribute("aria-pressed", String(theme === "dark"));
  }
}

applyTheme(initialTheme());

if (elements.boardZoomInButton) {
  elements.boardZoomInButton.addEventListener("click", () => {
    state.zoomScale = Math.min(state.zoomScale * 1.2, 4);
    state.mobileBoardInitialized = true;
    renderBoard(state.selectedState);
  });
}

if (elements.boardZoomOutButton) {
  elements.boardZoomOutButton.addEventListener("click", () => {
    state.zoomScale = Math.max(state.zoomScale / 1.2, 0.5);
    state.mobileBoardInitialized = true;
    renderBoard(state.selectedState);
  });
}

// Pan handling
let isPanning = false;
let panStart = { x: 0, y: 0 };
let panStartOffset = { x: 0, y: 0 };
let boardTouchGesture = null;

function boardViewSize() {
  const extent = BOARD_RADIUS * HEX_SIZE * SQRT3 + HEX_SIZE * 1.5;
  return (extent * 2) / state.zoomScale;
}

function panBoardByScreenDelta(dx, dy, startOffset = { x: state.panOffsetX, y: state.panOffsetY }) {
  const svgRect = elements.boardSvg?.getBoundingClientRect();
  if (!svgRect?.width || !svgRect?.height) return;
  const viewSize = boardViewSize();
  const scaleFactorX = viewSize / svgRect.width;
  const scaleFactorY = viewSize / svgRect.height;
  state.panOffsetX = startOffset.x - dx * scaleFactorX;
  state.panOffsetY = startOffset.y - dy * scaleFactorY;
  state.mobileBoardInitialized = true;
  renderBoard(state.selectedState);
}

function touchPoints(event) {
  return [...event.touches].map((touch) => ({ x: touch.clientX, y: touch.clientY }));
}

function midpoint(points) {
  return {
    x: points.reduce((total, point) => total + point.x, 0) / points.length,
    y: points.reduce((total, point) => total + point.y, 0) / points.length,
  };
}

function pointDistance(left, right) {
  return Math.hypot(left.x - right.x, left.y - right.y);
}

if (elements.boardSvg) {
  elements.boardSvg.addEventListener("mousedown", (e) => {
    if (state.isPhone) return;
    isPanning = true;
    panStart = { x: e.clientX, y: e.clientY };
    panStartOffset = { x: state.panOffsetX, y: state.panOffsetY };
  });
  window.addEventListener("mousemove", (e) => {
    if (!isPanning) return;
    const dx = e.clientX - panStart.x;
    const dy = e.clientY - panStart.y;
    panBoardByScreenDelta(dx, dy, panStartOffset);
  });
  window.addEventListener("mouseup", () => {
    isPanning = false;
  });
  elements.boardSvg.addEventListener("touchstart", (event) => {
    if (!state.isPhone) return;
    const points = touchPoints(event);
    if (!points.length) return;
    event.preventDefault();
    const center = midpoint(points);
    boardTouchGesture = {
      points,
      center,
      distance: points.length > 1 ? pointDistance(points[0], points[1]) : 0,
      zoomScale: state.zoomScale,
      offsetX: state.panOffsetX,
      offsetY: state.panOffsetY,
    };
  }, { passive: false });
  elements.boardSvg.addEventListener("touchmove", (event) => {
    if (!state.isPhone || !boardTouchGesture) return;
    const points = touchPoints(event);
    if (!points.length) return;
    event.preventDefault();
    const center = midpoint(points);
    const dx = center.x - boardTouchGesture.center.x;
    const dy = center.y - boardTouchGesture.center.y;

    if (points.length > 1 && boardTouchGesture.points.length > 1) {
      const nextDistance = pointDistance(points[0], points[1]);
      const ratio = boardTouchGesture.distance ? nextDistance / boardTouchGesture.distance : 1;
      state.zoomScale = Math.min(4, Math.max(0.72, boardTouchGesture.zoomScale * ratio));
    }
    panBoardByScreenDelta(dx, dy, {
      x: boardTouchGesture.offsetX,
      y: boardTouchGesture.offsetY,
    });
  }, { passive: false });
  elements.boardSvg.addEventListener("touchend", () => {
    boardTouchGesture = null;
  });
  elements.boardSvg.addEventListener("touchcancel", () => {
    boardTouchGesture = null;
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

async function createGame(playerCount = 2) {
  const playerIds = playerIdsForCount(playerCount);
  const payload = await api("/api/games", {
    method: "POST",
    body: JSON.stringify({
      player_ids: playerIds,
    }),
  });
  state.selectedGameId = payload.game_id;
  state.builderDraft = createEmptyDraft();
  state.knownCards = {};
  state.aiTargets = {};
  state.dismissedEndGameFor = null;
  await refreshGames();
}

function playerIdsForCount(playerCount) {
  const count = Math.max(2, Math.min(4, Number(playerCount) || 2));
  return PLAYER_ORDER.slice(0, count);
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
    state.dismissedEndGameFor = null;
    if (state.isPhone) resetMobileBoardView();
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
  elements.revealOrdersToggle.checked = true;
  state.selectedState = payload.state;
  await refreshGames();
}

async function resolveNextStep() {
  if (!state.selectedGameId || state.resolving) return;
  state.resolving = true;
  renderAll();
  const previousState = state.selectedState;
  try {
    const previousPhase = state.selectedState?.phase;
    const previousEventCount = state.selectedState?.event_log?.length ?? 0;
    const payload = await api(`/api/games/${state.selectedGameId}/resolve`, { method: "POST" });
    rememberVisibleCards(payload.state);
    const cleanupAnimations = await showResolutionCallouts(payload.state, previousEventCount, previousState);
    let resolvedState = payload.state;
    if (previousPhase === "award_baubles" && payload.state.phase === "cleanup") {
      const cleanupPayload = await api(`/api/games/${state.selectedGameId}/resolve`, { method: "POST" });
      rememberVisibleCards(cleanupPayload.state);
      resolvedState = cleanupPayload.state;
      if (resolvedState.phase === "give_orders") {
        state.builderDraft = createEmptyDraft();
      }
    } else if (previousPhase === "cleanup" && payload.state.phase === "give_orders") {
      state.builderDraft = createEmptyDraft();
    }
    state.selectedState = resolvedState;
    await refreshGames();
    cleanupAnimations?.();
  } finally {
    state.resolving = false;
    renderAll();
  }
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

async function submitAiOrders(playerId) {
  const aiType = selectedAiTypeForPlayer(playerId);
  const orders = buildAiOrders(playerId, aiType);
  if (!orders) {
    const label = AI_TYPES[aiType] || "AI";
    showError(new Error(`${label} cannot submit orders for ${playerId} right now.`));
    return;
  }
  await submitOrders(playerId, orders);
}

async function debugDrawDesperationCard() {
  if (!state.selectedGameId || !state.builderPlayerId || !state.debugDesperationCardId) return;
  const payload = await api(`/api/games/${state.selectedGameId}/debug/desperation-draw`, {
    method: "POST",
    body: JSON.stringify({
      player_id: state.builderPlayerId,
      card_id: state.debugDesperationCardId,
    }),
  });
  rememberVisibleCards(payload.state);
  state.selectedState = payload.state;
  await refreshGames();
}

async function submitAiOrdersSilently(playerId) {
  const aiType = selectedAiTypeForPlayer(playerId);
  const orders = buildAiOrders(playerId, aiType);
  if (!orders) return false;
  await submitOrders(playerId, orders);
  return true;
}

async function playEntireGame() {
  if (!state.selectedGameId || state.autoPlaying) return;
  const previousSpeed = state.playbackSpeed;
  state.autoPlaying = true;
  state.playbackSpeed = "instant";
  if (elements.playbackSpeedSelect) elements.playbackSpeedSelect.value = "play_game";
  renderAll();
  try {
    let guard = 0;
    while (state.selectedState?.phase !== "complete" && guard < 250) {
      guard += 1;
      const game = state.selectedState;
      if (!game) break;
      if (game.phase === "give_orders") {
        const pendingPlayers = PLAYER_ORDER
          .filter((playerId) => game.players?.[playerId] && canSubmit(playerId));
        for (const playerId of pendingPlayers) {
          await submitAiOrdersSilently(playerId);
        }
      } else if (canResolve(state.selectedState)) {
        await resolveNextStep();
      } else {
        break;
      }
    }
    if (guard >= 250) throw new Error("Autoplay stopped after 250 steps.");
  } finally {
    state.autoPlaying = false;
    state.playbackSpeed = previousSpeed;
    if (elements.playbackSpeedSelect) elements.playbackSpeedSelect.value = previousSpeed;
    renderAll();
  }
}

async function replayFinishedGame() {
  const game = state.selectedState;
  if (!game || game.phase !== "complete" || state.autoPlaying) return;
  state.autoPlaying = true;
  state.dismissedEndGameFor = state.selectedGameId;
  clearTransientOverlays();
  renderAll();
  try {
    const cleanupAnimations = await showResolutionCallouts(game, 0);
    cleanupAnimations?.();
  } finally {
    state.autoPlaying = false;
    renderAll();
  }
}

function showResultsSummary() {
  if (!state.selectedState || state.selectedState.phase !== "complete") return;
  state.dismissedEndGameFor = null;
  renderEndGameSummary(state.selectedState);
}

function selectedAiTypeForPlayer(playerId) {
  return state.selectedAiTypes[playerId] || state.selectedAiType || "bauble_runner";
}

function buildAiOrders(playerId, aiType) {
  if (aiType === "bauble_runner") return buildBaubleRunnerOrders(playerId);
  if (aiType === "hunter_killer") return buildHunterKillerOrders(playerId);
  if (aiType === "blaster") return buildBlasterOrders(playerId);
  return buildDemoOrders(playerId, "move");
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

function buildBaubleRunnerOrders(playerId) {
  const game = state.selectedState;
  const player = game?.players?.[playerId];
  if (!game || !player || !canSubmit(playerId)) return null;

  const available = [...(player.hand || [])];
  const opponentIds = Object.keys(game.players).filter((id) => id !== playerId);
  const attackTargetId = nearestOpponentId(game, player) || (opponentIds.includes("red") ? "red" : opponentIds[0]);
  const preview = {
    q: player.ship.q,
    r: player.ship.r,
    facing: player.ship.facing,
  };
  const currentTarget = nearestBaubleForRound(game, game.round_number, preview);
  const sealedCurrentReachPlan = currentTarget ? baubleRunnerReachPlan(currentTarget, available, preview, false) : null;
  const currentReachPlan = sealedCurrentReachPlan
    || (currentTarget ? baubleRunnerReachPlan(currentTarget, available, preview, true) : null);
  const plannedMoves = currentReachPlan ? [...currentReachPlan] : [];
  const targetBaubles = currentReachPlan ? [currentTarget] : nextRoundBaubleTargets(game, preview);

  return {
    stacks: [1, 2, 3].map((actionNumber) => {
      const alreadyScoring = distanceToBestBauble(targetBaubles, preview).distance === 0;
      const movePlan = plannedMoves.length
        ? takePlannedAiMove(available, plannedMoves.shift())
        : alreadyScoring
          ? null
          : takeBestBaubleMove(targetBaubles, available, preview);
      if (movePlan) {
        applyAiMoveStackPreview(preview, movePlan);
        return {
          action_number: actionNumber,
          seal_mode: movePlan.sealMode,
          cards: movePlan.selections,
        };
      }

      const attackPlan = takeAiAttack(available, attackTargetId);
      return {
        action_number: actionNumber,
        seal_mode: "sealed",
        cards: attackPlan ? [attackPlan.selection] : [],
      };
    }),
  };
}

function buildHunterKillerOrders(playerId) {
  const game = state.selectedState;
  const player = game?.players?.[playerId];
  if (!game || !player || !canSubmit(playerId)) return null;

  const targetId = persistentHunterKillerTargetId(game, player);
  const target = game.players[targetId];
  if (!target) return buildDemoOrders(playerId, "attack");

  const available = [...(player.hand || [])];
  const preview = {
    q: player.ship.q,
    r: player.ship.r,
    facing: player.ship.facing,
  };
  const attackCount = available.filter(aiCanUseAsAttack).length;
  if (attackCount === 0) {
    return buildHunterKillerNoAttackOrders(game, available, preview, target);
  }
  const attackSlots = new Set(
    [0, 1, 2].slice(Math.max(0, 3 - Math.min(3, attackCount))),
  );

  return {
    stacks: [1, 2, 3].map((actionNumber, stackIndex) => {
      const positionMove = takeHunterKillerPositionMove(available, game, preview, target);
      if (positionMove) {
        applyAiMoveStackPreview(preview, positionMove);
        return {
          action_number: actionNumber,
          seal_mode: positionMove.sealMode,
          cards: positionMove.selections,
        };
      }

      if (attackSlots.has(stackIndex)) {
        const attackPlan = takeHunterKillerAttack(available, game, preview, targetId, target);
        if (attackPlan) {
          return {
            action_number: actionNumber,
            seal_mode: attackPlan.sealMode,
            cards: [attackPlan.selection],
          };
        }
      }

      const movePlan = takeBestOpponentMove(available, preview, target);
      if (movePlan) {
        applyAiMoveStackPreview(preview, movePlan);
        return {
          action_number: actionNumber,
          seal_mode: movePlan.sealMode,
          cards: movePlan.selections,
        };
      }

      const attackPlan = takeHunterKillerAttack(available, game, preview, targetId, target);
      return {
        action_number: actionNumber,
        seal_mode: attackPlan ? attackPlan.sealMode : "sealed",
        cards: attackPlan ? [attackPlan.selection] : [],
      };
    }),
  };
}

function buildBlasterOrders(playerId) {
  const game = state.selectedState;
  const player = game?.players?.[playerId];
  if (!game || !player || !canSubmit(playerId)) return null;

  const available = [...(player.hand || [])];
  const preview = {
    q: player.ship.q,
    r: player.ship.r,
    facing: player.ship.facing,
  };
  const targetId = blasterTargetId(game, player, available, preview);
  const target = game.players[targetId];
  if (!target) return buildDemoOrders(playerId, "attack");

  const attackCount = available.filter(aiCanUseAsAttack).length;
  const attackSlots = new Set(
    [0, 1, 2].slice(Math.max(0, 3 - Math.min(3, attackCount))),
  );

  return {
    stacks: [1, 2, 3].map((actionNumber, stackIndex) => {
      const distance = hexDistance(preview.q, preview.r, target.ship.q, target.ship.r);
      if (distance > 8) {
        const movePlan = takeBestOpponentMove(available, preview, target);
        if (movePlan) {
          applyAiMoveStackPreview(preview, movePlan);
          return {
            action_number: actionNumber,
            seal_mode: movePlan.sealMode,
            cards: movePlan.selections,
          };
        }
      }

      if (attackSlots.has(stackIndex) || distance <= 8) {
        const attackPlan = takeHunterKillerAttack(available, game, preview, targetId, target);
        if (attackPlan) {
          return {
            action_number: actionNumber,
            seal_mode: attackPlan.sealMode,
            cards: [attackPlan.selection],
          };
        }
      }

      const movePlan = takeBestOpponentMove(available, preview, target);
      if (movePlan) {
        applyAiMoveStackPreview(preview, movePlan);
        return {
          action_number: actionNumber,
          seal_mode: movePlan.sealMode,
          cards: movePlan.selections,
        };
      }

      return {
        action_number: actionNumber,
        seal_mode: "sealed",
        cards: [],
      };
    }),
  };
}

function buildBaubleMoveOnlyOrders(game, available, preview) {
  const currentTarget = nearestBaubleForRound(game, game.round_number, preview);
  const sealedCurrentReachPlan = currentTarget ? baubleRunnerReachPlan(currentTarget, available, preview, false) : null;
  const currentReachPlan = sealedCurrentReachPlan
    || (currentTarget ? baubleRunnerReachPlan(currentTarget, available, preview, true) : null);
  const plannedMoves = currentReachPlan ? [...currentReachPlan] : [];
  const targetBaubles = currentTarget ? [currentTarget] : nextRoundBaubleTargets(game, preview);

  return {
    stacks: [1, 2, 3].map((actionNumber) => {
      const alreadyScoring = distanceToBestBauble(targetBaubles, preview).distance === 0;
      const movePlan = plannedMoves.length
        ? takePlannedAiMove(available, plannedMoves.shift())
        : alreadyScoring
          ? null
          : takeBestBaubleMove(targetBaubles, available, preview);
      if (movePlan) {
        applyAiMoveStackPreview(preview, movePlan);
        return {
          action_number: actionNumber,
          seal_mode: movePlan.sealMode,
          cards: movePlan.selections,
        };
      }
      return {
        action_number: actionNumber,
        seal_mode: "sealed",
        cards: [],
      };
    }),
  };
}

function buildHunterKillerNoAttackOrders(game, available, preview, target) {
  const currentTarget = nearestBaubleForRound(game, game.round_number, preview);
  const sealedCurrentReachPlan = currentTarget ? baubleRunnerReachPlan(currentTarget, available, preview, false) : null;
  const currentReachPlan = sealedCurrentReachPlan
    || (currentTarget ? baubleRunnerReachPlan(currentTarget, available, preview, true) : null);
  const plannedMoves = currentReachPlan ? [...currentReachPlan] : [];

  return {
    stacks: [1, 2, 3].map((actionNumber) => {
      const movePlan = plannedMoves.length
        ? takePlannedAiMove(available, plannedMoves.shift())
        : takeBestOpponentMove(available, preview, target);
      if (movePlan) {
        applyAiMoveStackPreview(preview, movePlan);
        return {
          action_number: actionNumber,
          seal_mode: movePlan.sealMode,
          cards: movePlan.selections,
        };
      }
      return {
        action_number: actionNumber,
        seal_mode: "sealed",
        cards: [],
      };
    }),
  };
}

function nextRoundBaubleTargets(game, preview) {
  const nextRound = Math.min((game?.round_number || 1) + 1, 6);
  const nextTarget = nearestBaubleForRound(game, nextRound, preview);
  return nextTarget ? [nextTarget] : activeBaubleTargets(game);
}

function nearestBaubleForRound(game, roundNumber, preview) {
  const candidates = roundBaubleTargets(game, roundNumber);
  if (!candidates.length) return null;
  return [...candidates].sort((left, right) => (
    baubleRangeDistance(left, preview) - baubleRangeDistance(right, preview)
    || (right.victory_points || 0) - (left.victory_points || 0)
    || String(left.id).localeCompare(String(right.id))
  ))[0];
}

function roundBaubleTargets(game, roundNumber) {
  const baubles = game?.baubles || [];
  if (roundNumber >= 6) return baubles.filter((bauble) => bauble.is_fang);
  return baubles.filter((bauble) => !bauble.is_fang && bauble.number === roundNumber);
}

function baubleRunnerReachPlan(bauble, available, preview, allowOverdrive) {
  const moveCards = available.filter(aiCanUseAsMove);
  const seen = new Set();

  function search(position, remainingCards, actionsLeft) {
    if (baubleRangeDistance(bauble, position) === 0) return [];
    if (actionsLeft === 0) return null;

    const key = `${position.q},${position.r},${position.facing}|${actionsLeft}|${remainingCards.map((card) => card.id).join(",")}`;
    if (seen.has(key)) return null;
    seen.add(key);

    const options = aiMoveStackOptions(remainingCards, allowOverdrive)
      .map((option) => {
        const candidate = { q: position.q, r: position.r, facing: position.facing };
        applyAiMoveStackPreview(candidate, option);
        return {
          ...option,
          candidate,
          distance: baubleRangeDistance(bauble, candidate),
        };
      })
      .sort((left, right) => (
        left.distance - right.distance
        || (left.sealMode === "overdrive" ? 1 : 0) - (right.sealMode === "overdrive" ? 1 : 0)
        || right.moves.length - left.moves.length
      ));
    for (const option of options) {
      const usedIds = new Set(option.moves.map((move) => move.card.id));
      const nextCards = remainingCards.filter((card) => !usedIds.has(card.id));
      const remainder = search(option.candidate, nextCards, actionsLeft - 1);
      if (remainder) {
        return [plannedMoveStack(option), ...remainder];
      }
    }
    return null;
  }

  return search({ q: preview.q, r: preview.r, facing: preview.facing }, moveCards, 3);
}

function takeBestBaubleMove(targetBaubles, available, preview) {
  let best = null;
  aiMoveStackOptions(available, false).forEach((option) => {
    const candidate = {
      q: preview.q,
      r: preview.r,
      facing: preview.facing,
    };
    applyAiMoveStackPreview(candidate, option);
    const baubleScore = distanceToBestBauble(targetBaubles, candidate);
    const currentScore = distanceToBestBauble(targetBaubles, preview);
    const improvement = currentScore.distance - baubleScore.distance;
    const score = [
      improvement,
      -baubleScore.distance,
      baubleScore.victoryPoints,
      aiMoveStackDistance(option),
      option.moves.length,
      -option.firstIndex,
    ];
    if (!best || compareAiScores(score, best.score) > 0) {
      best = { ...option, score };
    }
  });
  if (!best || best.score[0] <= 0) return null;
  removeAiMoveStackCards(available, best);
  return materializeAiMoveStack(best);
}

function takePlannedAiMove(available, plannedStack) {
  if (!plannedStack) return null;
  const moves = [];
  for (const plannedMove of plannedStack.moves || []) {
    const index = available.findIndex((card) => card.id === plannedMove.cardId);
    if (index < 0) return null;
    moves.push({ card: available[index], index, choice: plannedMove.choice });
  }
  removeAiMoveStackCards(available, { moves });
  return materializeAiMoveStack({
    sealMode: plannedStack.sealMode,
    moves,
    firstIndex: Math.min(...moves.map((move) => move.index)),
  });
}

function takeBestOpponentMove(available, preview, target) {
  let best = null;
  aiMoveStackOptions(available, false).forEach((option) => {
    const candidate = {
      q: preview.q,
      r: preview.r,
      facing: preview.facing,
    };
    applyAiMoveStackPreview(candidate, option);
    const currentDistance = hexDistance(preview.q, preview.r, target.ship.q, target.ship.r);
    const candidateDistance = hexDistance(candidate.q, candidate.r, target.ship.q, target.ship.r);
    const improvement = currentDistance - candidateDistance;
    const score = [
      improvement,
      -candidateDistance,
      aiMoveStackDistance(option),
      option.moves.length,
      -option.firstIndex,
    ];
    if (!best || compareAiScores(score, best.score) > 0) {
      best = { ...option, score };
    }
  });
  if (!best || best.score[0] < 0) return null;
  removeAiMoveStackCards(available, best);
  return materializeAiMoveStack(best);
}

function takeHunterKillerPositionMove(available, game, preview, target) {
  if ((game?.round_number || 1) >= 6) return null;
  const currentNeeded = bestPredictedAttackNeededRoll(available, preview, target);
  if (currentNeeded < 11) return null;
  let best = null;
  aiMoveStackOptions(available, false).forEach((option) => {
    const candidate = {
      q: preview.q,
      r: preview.r,
      facing: preview.facing,
    };
    applyAiMoveStackPreview(candidate, option);
    const usedIds = new Set(option.moves.map((move) => move.card.id));
    const remainingAfterMove = available.filter((card) => !usedIds.has(card.id));
    const candidateNeeded = bestPredictedAttackNeededRoll(remainingAfterMove, candidate, target);
    const currentDistance = hexDistance(preview.q, preview.r, target.ship.q, target.ship.r);
    const candidateDistance = hexDistance(candidate.q, candidate.r, target.ship.q, target.ship.r);
    const improvement = currentNeeded - candidateNeeded;
    const score = [
      improvement,
      -candidateNeeded,
      currentDistance - candidateDistance,
      aiMoveStackDistance(option),
      option.moves.length,
      -option.firstIndex,
    ];
    if (!best || compareAiScores(score, best.score) > 0) {
      best = { ...option, score };
    }
  });
  if (!best || best.score[0] <= 0) return null;
  removeAiMoveStackCards(available, best);
  return materializeAiMoveStack(best);
}

function takeHunterKillerAttack(available, game, preview, attackTargetId, target) {
  if (!attackTargetId) return null;
  let best = null;
  available.forEach((card, index) => {
    if (!aiCanUseAsAttack(card)) return;
    const sealMode = hunterKillerAttackSealMode(game, preview, target, card);
    const score = [previewCardValue(card, sealMode), sealMode === "overdrive" ? 1 : 0, -index];
    if (!best || compareAiScores(score, best.score) > 0) {
      best = {
        card,
        index,
        sealMode,
        score,
        selection: aiSelectionForAttack(card, attackTargetId),
      };
    }
  });
  if (!best) return null;
  available.splice(best.index, 1);
  return best;
}

function hunterKillerAttackSealMode(game, preview, target, card) {
  if ((game?.round_number || 1) >= 6) return "overdrive";
  const neededRoll = predictedAttackNeededRoll(preview, target, card);
  return neededRoll >= 11 ? "sealed" : "overdrive";
}

function predictedAttackNeededRoll(preview, target, card) {
  if (!target?.ship) return 12;
  const distance = hexDistance(preview.q, preview.r, target.ship.q, target.ship.r);
  const defense = distance + (target.ship.movement_this_action || 0) + (target.ship.defense_bonus_this_action || 0);
  return defense - predictedAttackAimBonus(card);
}

function bestPredictedAttackNeededRoll(available, preview, target) {
  const attackCards = available.filter(aiCanUseAsAttack);
  if (!attackCards.length) return Infinity;
  return Math.min(...attackCards.map((card) => predictedAttackNeededRoll(preview, target, card)));
}

function predictedAttackAimBonus(card) {
  if (card?.effect?.aim_bonus) return card.effect.aim_bonus;
  return card?.aim_bonus || 0;
}

function takeAiAttack(available, attackTargetId, sealMode = "sealed") {
  if (!attackTargetId) return null;
  let best = null;
  available.forEach((card, index) => {
    if (!aiCanUseAsAttack(card)) return;
    const score = [previewCardValue(card, sealMode), -index];
    if (!best || compareAiScores(score, best.score) > 0) {
      best = {
        card,
        index,
        sealMode,
        score,
        selection: aiSelectionForAttack(card, attackTargetId),
      };
    }
  });
  if (!best) return null;
  available.splice(best.index, 1);
  return best;
}

function aiMoveChoices(card) {
  if (!aiCanUseAsMove(card)) return [];
  return card.orientation_options?.length ? card.orientation_options : ["forward"];
}

function aiMoveSealModes(allowOverdrive) {
  return allowOverdrive ? ["sealed", "overdrive"] : ["sealed"];
}

function aiMoveStackOptions(available, allowOverdrive) {
  const moveEntries = available
    .map((card, index) => ({ card, index }))
    .filter(({ card }) => aiCanUseAsMove(card));
  const options = [];

  moveEntries.forEach((entry) => {
    aiMoveChoices(entry.card).forEach((choice) => {
      options.push(materializeAiMoveStack({
        sealMode: "sealed",
        moves: [{ ...entry, choice }],
        firstIndex: entry.index,
      }));
      if (allowOverdrive) {
        options.push(materializeAiMoveStack({
          sealMode: "overdrive",
          moves: [{ ...entry, choice }],
          firstIndex: entry.index,
        }));
      }
    });
  });

  for (let leftIndex = 0; leftIndex < moveEntries.length; leftIndex += 1) {
    for (let rightIndex = 0; rightIndex < moveEntries.length; rightIndex += 1) {
      if (leftIndex === rightIndex) continue;
      const left = moveEntries[leftIndex];
      const right = moveEntries[rightIndex];
      aiMoveChoices(left.card).forEach((leftChoice) => {
        aiMoveChoices(right.card).forEach((rightChoice) => {
          options.push(materializeAiMoveStack({
            sealMode: "sealed",
            moves: [
              { ...left, choice: leftChoice },
              { ...right, choice: rightChoice },
            ],
            firstIndex: Math.min(left.index, right.index),
          }));
        });
      });
    }
  }

  return options;
}

function aiCanUseAsMove(card) {
  if (!card || card.no_basic_face) return false;
  return card.is_hybrid || (card.effect?.family ?? card.family) === "move";
}

function aiCanUseAsAttack(card) {
  if (!card || card.no_basic_face) return false;
  return card.is_hybrid || (card.effect?.family ?? card.family) === "attack";
}

function aiSelectionForMove(card, choice) {
  const selection = {
    card_id: card.id,
    face: "front",
    orientation: choice,
  };
  if (card.is_hybrid) selection.mode = "move";
  return selection;
}

function aiSelectionForAttack(card, attackTargetId) {
  const selection = {
    card_id: card.id,
    face: "front",
    orientation: "up",
  };
  if (card.is_hybrid) selection.mode = "attack";
  if (attackTargetId) selection.target_player_id = attackTargetId;
  return selection;
}

function plannedMoveStack(option) {
  return {
    sealMode: option.sealMode,
    moves: option.moves.map((move) => ({
      cardId: move.card.id,
      choice: move.choice,
    })),
  };
}

function materializeAiMoveStack(option) {
  return {
    ...option,
    selections: option.moves.map((move) => aiSelectionForMove(move.card, move.choice)),
  };
}

function aiMoveStackDistance(option) {
  const passes = option.sealMode === "overdrive" ? 2 : 1;
  return option.moves.reduce((sum, move) => sum + previewCardValue(move.card, option.sealMode) * passes, 0);
}

function removeAiMoveStackCards(available, option) {
  const usedIds = new Set(option.moves.map((move) => move.card.id));
  for (let index = available.length - 1; index >= 0; index -= 1) {
    if (usedIds.has(available[index].id)) available.splice(index, 1);
  }
}

function aiStackForSelection(card, choice, mode) {
  return {
    seal_mode: "sealed",
    cards: [card.id],
    faces: ["front"],
    move_choices: [choice],
    modes: [card.is_hybrid ? mode : ""],
    targets: [""],
  };
}

function applyAiMovePreview(preview, movePlan) {
  applyAiMoveCandidatePreview(preview, movePlan.card, movePlan.choice, movePlan.sealMode);
}

function applyAiMoveStackPreview(preview, movePlan) {
  const passes = movePlan.sealMode === "overdrive" ? 2 : 1;
  for (let pass = 0; pass < passes; pass += 1) {
    movePlan.moves.forEach((move, cardIndex) => {
      applyPreviewMove(
        preview,
        previewCardValue(move.card, movePlan.sealMode),
        move.choice,
        move.card,
        aiStackForMovePlan(movePlan),
        cardIndex,
      );
    });
  }
}

function applyAiMoveCandidatePreview(preview, card, choice, sealMode) {
  const passes = sealMode === "overdrive" ? 2 : 1;
  for (let pass = 0; pass < passes; pass += 1) {
    applyPreviewMove(
      preview,
      previewCardValue(card, sealMode),
      choice,
      card,
      aiStackForSelection(card, choice, "move"),
      0,
    );
  }
}

function distanceToBestBauble(candidates, preview) {
  if (!candidates.length) return { distance: Infinity, victoryPoints: 0 };
  return candidates
    .map((bauble) => ({
      distance: baubleRangeDistance(bauble, preview),
      victoryPoints: bauble.victory_points || 0,
    }))
    .sort((left, right) => (
      left.distance - right.distance
      || right.victoryPoints - left.victoryPoints
    ))[0];
}

function baubleRangeDistance(bauble, preview) {
  return Math.max(0, hexDistance(preview.q, preview.r, bauble.q, bauble.r) - 1);
}

function activeBaubleTargets(game) {
  const baubles = game?.baubles || [];
  const active = baubles.filter((bauble) => bauble.is_fang || bauble.number === game.round_number);
  if (active.length) return active;
  return baubles.filter((bauble) => !bauble.is_fang);
}

function nearestOpponentId(game, player) {
  return activeOpponentPlayers(game, player)
    .sort((left, right) => (
      hexDistance(player.ship.q, player.ship.r, left.ship.q, left.ship.r)
      - hexDistance(player.ship.q, player.ship.r, right.ship.q, right.ship.r)
      || left.id.localeCompare(right.id)
    ))[0]?.id || "";
}

function activeOpponentPlayers(game, player) {
  return Object.values(game?.players || {})
    .filter((candidate) => (
      candidate.id !== player.id
      && !candidate.eliminated
      && !candidate.ship?.destroyed
    ));
}

function persistentHunterKillerTargetId(game, player) {
  const key = `${state.selectedGameId || "game"}:${player.id}`;
  const rememberedId = state.aiTargets[key];
  if (rememberedId && isActiveOpponent(game, player, rememberedId)) {
    return rememberedId;
  }
  const nextId = initialHunterKillerTargetId(game, player);
  if (nextId) state.aiTargets[key] = nextId;
  return nextId;
}

function initialHunterKillerTargetId(game, player) {
  return nearestOpponentId(game, player);
}

function isActiveOpponent(game, player, targetId) {
  const target = game?.players?.[targetId];
  return Boolean(target && target.id !== player.id && !target.eliminated && !target.ship?.destroyed);
}

function blasterTargetId(game, player, available, preview) {
  const candidates = activeOpponentPlayers(game, player)
    .filter((target) => canReachTargetDistance(available, preview, target, 8));
  const pool = candidates.length ? candidates : activeOpponentPlayers(game, player);
  return pool
    .sort((left, right) => compareAiScores(blasterTargetScore(player, right), blasterTargetScore(player, left)))[0]?.id || "";
}

function blasterTargetScore(player, target) {
  const destroyedComponents = target.ship?.destroyed_components?.length || 0;
  return [
    target.ship?.damage_taken || 0,
    destroyedComponents,
    -(target.ship?.shields || 0),
    -hexDistance(player.ship.q, player.ship.r, target.ship.q, target.ship.r),
    -PLAYER_ORDER.indexOf(target.id),
  ];
}

function canReachTargetDistance(available, preview, target, maxDistance) {
  if (hexDistance(preview.q, preview.r, target.ship.q, target.ship.r) <= maxDistance) return true;
  const moveCards = available.filter(aiCanUseAsMove);
  const seen = new Set();

  function search(position, remainingCards, actionsLeft) {
    if (hexDistance(position.q, position.r, target.ship.q, target.ship.r) <= maxDistance) return true;
    if (actionsLeft === 0) return false;
    const key = `${position.q},${position.r},${position.facing}|${actionsLeft}|${remainingCards.map((card) => card.id).join(",")}`;
    if (seen.has(key)) return false;
    seen.add(key);

    return aiMoveStackOptions(remainingCards, true).some((option) => {
      const candidate = { q: position.q, r: position.r, facing: position.facing };
      applyAiMoveStackPreview(candidate, option);
      const usedIds = new Set(option.moves.map((move) => move.card.id));
      const nextCards = remainingCards.filter((card) => !usedIds.has(card.id));
      return search(candidate, nextCards, actionsLeft - 1);
    });
  }

  return search({ q: preview.q, r: preview.r, facing: preview.facing }, moveCards, 3);
}

function compareAiScores(left, right) {
  for (let index = 0; index < Math.max(left.length, right.length); index += 1) {
    const difference = (left[index] || 0) - (right[index] || 0);
    if (difference !== 0) return difference;
  }
  return 0;
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
  const events = state.selectedState?.event_log || [];
  elements.gameCount.textContent = events.length.toString();
  if (!elements.actionLog) return;
  elements.actionLog.replaceChildren(...actionLogItems(state.selectedState));
}

function renderAll() {
  renderGames();
  const game = state.selectedState;
  elements.selectedGameId.textContent = state.selectedGameId ? state.selectedGameId.slice(0, 12) : "None";
  elements.roundValue.textContent = game?.round_number ?? "-";
  elements.phaseValue.textContent = game?.phase ?? "-";
  elements.startingPlayerValue.textContent = game?.starting_player_id ?? "-";
  if (elements.redOrdersButton) elements.redOrdersButton.disabled = !canSubmit("red");
  if (elements.blueOrdersButton) elements.blueOrdersButton.disabled = !canSubmit("blue");
  if (elements.aiTypeSelect) {
    elements.aiTypeSelect.disabled = !game;
    elements.aiTypeSelect.value = state.selectedAiType;
  }
  syncAiTypeSelect("red", elements.redAiTypeSelect, game);
  syncAiTypeSelect("blue", elements.blueAiTypeSelect, game);
  renderAiControls(game);
  renderDebugDesperationDraw(game);
  elements.resolveButton.disabled = state.autoPlaying || !canResolve(game);
  renderFinishedGameActions(game);
  renderOrdersBuilder(game);
  renderBoard(game);
  renderMiniShipBoards(game);
  renderShipBoards(game);
  renderPlayers(game);
  renderEvents(game);
  elements.stateJson.textContent = JSON.stringify(game || {}, null, 2);
  renderEndGameSummary(game);
  renderMobileControls();
}

function renderFinishedGameActions(game) {
  const isFinished = game?.phase === "complete";
  if (elements.finishedGameActions) elements.finishedGameActions.hidden = !isFinished;
  if (elements.replayGameButton) elements.replayGameButton.disabled = !isFinished || state.autoPlaying || state.resolving;
  if (elements.resultsSummaryButton) elements.resultsSummaryButton.disabled = !isFinished;
}

function syncAiTypeSelect(playerId, select, game) {
  if (!select) return;
  select.disabled = !game || !game.players?.[playerId];
  select.value = selectedAiTypeForPlayer(playerId);
}

function renderAiControls(game) {
  if (!elements.aiControls) return;
  if (!game) {
    elements.aiControls.replaceChildren();
    return;
  }
  const controls = PLAYER_ORDER
    .filter((playerId) => game.players?.[playerId])
    .map((playerId) => {
      const control = document.createElement("div");
      control.className = "player-ai-group";
      control.style.borderLeftColor = SHIP_COLORS[playerId] || "#60706b";
      control.innerHTML = `
        <label class="ai-control player-ai-control">
          ${escapeHtml(titleCase(playerId))} AI
          <select data-ai-player="${escapeHtml(playerId)}">
            ${Object.entries(AI_TYPES).map(([value, label]) => `
              <option value="${escapeHtml(value)}"${selectedAiTypeForPlayer(playerId) === value ? " selected" : ""}>${escapeHtml(label)}</option>
            `).join("")}
          </select>
        </label>
        <button type="button" data-ai-submit="${escapeHtml(playerId)}"${!state.autoPlaying && canSubmit(playerId) ? "" : " disabled"}>${escapeHtml(titleCase(playerId))} AI</button>
      `;
      return control;
    });
  elements.aiControls.replaceChildren(...controls);
}

function actionLogItems(game) {
  const events = enrichOrderDiscardEvents(game?.event_log || []);
  if (!events.length) {
    const empty = document.createElement("div");
    empty.className = "action-log-empty";
    empty.textContent = "No actions yet.";
    return [empty];
  }
  return [...events].filter((event) => !event._pairedWithOrders).reverse().map((event) => {
    const item = document.createElement("article");
    const playerId = actionLogPlayerId(event);
    const activity = actionLogActivity(event);
    item.className = `action-log-item ${actionLogTone(event)} ${activity ? `activity-${activity}` : ""}`;
    if (playerId && SHIP_COLORS[playerId]) item.style.borderLeftColor = SHIP_COLORS[playerId];
    item.innerHTML = `
      <div class="action-log-kicker">${escapeHtml(actionLogKicker(event))}</div>
      <strong>${escapeHtml(actionLogTitle(event))}</strong>
      <div class="action-log-body">${actionLogBody(event)}</div>
      <pre class="action-log-detail">${escapeHtml(actionLogDetail(event))}</pre>
    `;
    return item;
  });
}

function enrichOrderDiscardEvents(events) {
  const enriched = events.map((event) => ({ ...event }));
  const pendingDiscards = {};
  enriched.forEach((event, index) => {
    if (event.type === "hand_discarded") {
      pendingDiscards[event.player_id] = {
        index,
        cardIds: [...(event.card_ids || [])],
      };
      return;
    }
    if (event.type !== "orders_submitted") return;
    const pending = pendingDiscards[event.player_id];
    if (!pending) return;
    event.unused_card_ids = pending.cardIds;
    enriched[pending.index]._pairedWithOrders = true;
    delete pendingDiscards[event.player_id];
  });
  return enriched;
}

function actionLogTone(event) {
  if (event.type === "volley_resolved") return event.hit ? "hit" : "miss";
  if (event.type === "bauble_awarded") return "award";
  if (event.type === "orders_submitted" || event.type === "action_revealed") return "orders";
  return "";
}

function actionLogActivity(event) {
  if (event.type === "volley_resolved") return "attack";
  if (event.type === "movement_resolved") return "move";
  if (event.type === "bauble_awarded" || event.type === "baubles_awarded") return "award";
  if (event.type === "action_revealed") return actionCardsActivity(event.cards || []);
  if (event.type === "orders_submitted") return "orders";
  return "";
}

function actionLogPlayerId(event) {
  return event.player_id || event.attacker_id || event.awards?.[0]?.player_id || "";
}

function actionLogKicker(event) {
  const round = event.round ? `Round ${event.round}` : "Game";
  const action = event.action_number ? ` Action ${event.action_number}` : "";
  return `${round}${action}`;
}

function actionLogTitle(event) {
  if (event.type === "orders_submitted") return `${titleCase(event.player_id)} orders set`;
  if (event.type === "action_revealed") return `${titleCase(event.player_id)} ${englishActionStack(event.action_number, event.cards || [], event.seal_mode)}`;
  if (event.type === "movement_resolved") return `${titleCase(event.player_id)} ${englishMovementEvent(event)}`;
  if (event.type === "volley_resolved") return englishVolleyEvent(event);
  if (event.type === "bauble_awarded") return `${event.bauble?.is_fang ? "Fang" : `Bauble ${event.bauble?.number}`} awarded`;
  if (event.type === "baubles_awarded") return "No baubles awarded";
  if (event.type === "phase_changed") return `Phase: ${event.phase}`;
  if (event.type === "hand_discarded") return `${titleCase(event.player_id)} discarded unused cards`;
  if (event.type === "action_cards_moved") return `${titleCase(event.player_id)} cleaned up action cards`;
  if (event.type === "debug_desperation_drawn") return `${titleCase(event.player_id)} drew ${event.card_name || event.card_id}`;
  return titleCase((event.type || "event").replaceAll("_", " "));
}

function actionLogBody(event) {
  if (event.type === "orders_submitted") {
    const unused = event.unused_card_ids?.length
      ? `<span>Unused/discarded: ${escapeHtml(englishCardIdList(event.unused_card_ids))}</span>`
      : "";
    return `${orderStacksSummary(event.stacks || [])}${unused}`;
  }
  if (event.type === "action_revealed") return `<span class="activity-${actionCardsActivity(event.cards || [])}">${escapeHtml(englishCardSelections(event.cards || []))}</span>`;
  if (event.type === "movement_resolved") {
    return (event.steps || []).map((step) => `<span class="activity-move">${escapeHtml(englishMovementStep(step))}</span>`).join("");
  }
  if (event.type === "volley_resolved") {
    const attackBonus = event.attack_bonus ?? event.aim_bonus ?? 0;
    const rollTotal = event.roll + attackBonus;
    const result = volleyOutcomeText(event);
    const overdrive = event.overdrive_copy ? "Overdrive copy. " : "";
    return `<span class="activity-attack">${escapeHtml(`${overdrive}Defense ${event.defense_threshold}; rolled ${event.roll} + ${attackBonus} Aim = ${rollTotal}: ${result}`)}</span>`;
  }
  if (event.type === "bauble_awarded") {
    return (event.awards || []).map((award) => {
      const cardText = award.desperation_card_drawn ? ` and drew ${award.desperation_card_id || "a card"}` : "";
      return `<span class="activity-award">${escapeHtml(`${titleCase(award.player_id)} gained ${award.vp_awarded} VP${cardText}`)}</span>`;
    }).join("");
  }
  if (event.type === "baubles_awarded") return `<span>${escapeHtml(event.message || "No ships were in range.")}</span>`;
  if (event.type === "hand_discarded") return `<span>${escapeHtml((event.card_ids || []).join(", ") || "No cards")}</span>`;
  if (event.type === "action_cards_moved") {
    const discarded = event.moved_to_discard?.length ? `Discard: ${event.moved_to_discard.join(", ")}` : "";
    const overheated = hasOverheatPile(state.selectedState) && event.moved_to_overheat?.length
      ? `Overheat: ${event.moved_to_overheat.join(", ")}`
      : "";
    return [discarded, overheated].filter(Boolean).map((line) => `<span>${escapeHtml(line)}</span>`).join("");
  }
  if (event.type === "debug_desperation_drawn") {
    return `<span>${escapeHtml(`${event.card_id} added to hand by debug draw`)}</span>`;
  }
  return "";
}

function actionLogDetail(event) {
  const { _pairedWithOrders, ...detail } = event;
  return JSON.stringify(detail, null, 2);
}

function orderStacksSummary(stacks) {
  if (!stacks.length) return "<span>Orders hidden.</span>";
  return stacks.map((stack) => {
    const activity = actionCardsActivity(stack.cards || []);
    return `<span class="activity-${activity}">${escapeHtml(englishActionStack(stack.action_number, stack.cards || [], stack.seal_mode))}</span>`;
  }).join("");
}

function englishActionStack(actionNumber, cards, sealMode = "sealed") {
  const prefix = `Action ${actionNumber}:`;
  const overdrive = sealMode === "overdrive" ? "Overdrive " : "";
  if (!cards.length) return `${prefix} No cards`;
  return `${prefix} ${overdrive}${englishCardSelections(cards)}`;
}

function englishCardSelections(cards) {
  if (!cards.length) return "No cards";
  return cards.map(englishCardSelection).join(" + ");
}

function englishCardSelection(selection) {
  const card = inferCardFromId(selection.card_id || "");
  const family = selection.mode || card.family;
  if (family === "attack") {
    const target = selection.target_player_id ? ` at ${titleCase(selection.target_player_id)}` : "";
    return `Attack +${card.value}${target}`;
  }
  if (family === "move") {
    const moveText = englishMoveChoice(selection.orientation || "forward", card.value);
    return moveText;
  }
  return selection.card_id || "Card";
}

function englishCardIdList(cardIds) {
  if (!cardIds.length) return "no cards";
  return cardIds.map(englishCardId).join(", ");
}

function englishCardId(cardId) {
  const card = state.knownCards[cardId] || inferCardFromId(cardId);
  const family = card.effect?.family ?? card.family;
  const value = card.effect?.value ?? card.value;
  if (card.is_hybrid || family === "hybrid") return card.name || `Hybrid ${value}`;
  if (family === "attack") return `Attack +${value}`;
  if (family === "move") return `Move ${value}`;
  return card.name || cardId;
}

function englishMovementEvent(event) {
  const steps = event.steps || [];
  if (!steps.length) return "did not move";
  const total = steps.reduce((sum, step) => sum + (step.distance || 0), 0);
  if (steps.length === 1) return englishMovementStep(steps[0]);
  return `moved ${total}`;
}

function englishMovementStep(step) {
  if (step.warp_destination) return `warped ${titleCase(step.warp_destination)}`;
  if (step.distance <= 0) return "held position";
  return englishMoveChoice(step.choice || "forward", step.distance);
}

function englishMoveChoice(choice, distance) {
  const distanceText = distance > 0 ? ` ${distance}` : "";
  if (choice === "turn_left") return `Turn Left, Move${distanceText}`;
  if (choice === "turn_right") return `Turn Right, Move${distanceText}`;
  if (choice === "slip_left") return `Side Slip Left${distanceText}`;
  if (choice === "slip_right") return `Side Slip Right${distanceText}`;
  if (choice === "u_turn_move") return `U-Turn, Move${distanceText}`;
  return `Move${distanceText}`;
}

function englishVolleyEvent(event) {
  const result = event.hit ? "hit" : "missed";
  return `${titleCase(event.attacker_id)} shot ${titleCase(event.target_id)} and ${result}`;
}

function volleyOutcomeText(event) {
  if (!event.hit) return "MISS";
  if (event.shielded) return "HIT, absorbed by shields";
  const destroyed = (event.damage_shots || [])
    .filter((shot) => shot.destroyed && shot.component_id)
    .map((shot) => formatComponentId(shot.component_id));
  if (destroyed.length) return `HIT, damaged ${destroyed.join(", ")}`;
  if (event.damage_applied) return `HIT, ${event.damage_applied} damage`;
  return "HIT";
}

function volleyCalloutTitle(event) {
  const attacker = titleCase(event.attacker_id);
  if (!event.hit) return `${attacker} Misses`;
  if (event.shielded) return `${attacker} Hits - Absorbed by Shields`;
  const destroyed = (event.damage_shots || []).find((shot) => shot.destroyed && shot.component_id);
  if (destroyed) return `${attacker} Hits - ${formatComponentId(destroyed.component_id)} Destroyed`;
  return `${attacker} Hits - Damage`;
}

function actionCardsActivity(cards) {
  if (!cards.length) return "orders";
  return cards.some((selection) => {
    const card = inferCardFromId(selection.card_id || "");
    return (selection.mode || card.family) === "attack";
  }) ? "attack" : "move";
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

async function exportGameLog() {
  const text = englishGameLog(state.selectedState);
  const blob = new Blob([text], { type: "text/plain" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = `starshot-log-${state.selectedGameId?.slice(0, 8) || "game"}.txt`;
  document.body.append(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
  const copied = await copyTextToClipboard(text);
  flashExportButton(copied ? "Exported + Copied" : "Exported");
}

async function copyTextToClipboard(text) {
  try {
    if (navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(text);
      return true;
    }
  } catch {
    // Fall back to the legacy copy path below.
  }
  const textarea = document.createElement("textarea");
  textarea.value = text;
  textarea.setAttribute("readonly", "");
  textarea.style.position = "fixed";
  textarea.style.left = "-9999px";
  document.body.append(textarea);
  textarea.select();
  try {
    return document.execCommand("copy");
  } catch {
    return false;
  } finally {
    textarea.remove();
  }
}

function flashExportButton(label) {
  if (!elements.exportLogButton) return;
  const original = elements.exportLogButton.textContent;
  elements.exportLogButton.textContent = label;
  window.setTimeout(() => {
    elements.exportLogButton.textContent = original || "Export Log";
  }, 1800);
}

function aiStackForMovePlan(movePlan) {
  return {
    seal_mode: movePlan.sealMode,
    cards: movePlan.moves.map((move) => move.card.id),
    faces: movePlan.moves.map(() => "front"),
    move_choices: movePlan.moves.map((move) => move.choice),
    modes: movePlan.moves.map((move) => (move.card.is_hybrid ? "move" : "")),
    targets: movePlan.moves.map(() => ""),
  };
}

function englishGameLog(game) {
  if (!game) return "No game selected.";
  const lines = [
    `StarShot game ${state.selectedGameId || ""}`,
    `Round ${game.round_number}, phase ${game.phase}, starting player ${game.starting_player_id}`,
    ...deckMetadataLogLines(game),
    "",
  ];
  enrichOrderDiscardEvents(game.event_log || []).forEach((event) => {
    if (event._pairedWithOrders) return;
    const line = englishEventLine(event);
    if (line) lines.push(line);
  });
  return lines.join("\n");
}

function deckMetadataLogLines(game) {
  const deckSet = game.deck_set;
  if (!deckSet) {
    return [
      `Deck set: ${game.deck_set_id || "unknown"}`,
      `Rules config: ${JSON.stringify(game.rules_config || {})}`,
    ];
  }
  const lines = [
    `Deck set: ${deckSet.id || game.deck_set_id || "unknown"} (${deckSet.name || "unnamed"}, rules ${deckSet.rules_version || "unknown"})`,
    `Deck path: ${deckSet.path || "unknown"}`,
    `Rules config: ${JSON.stringify(deckSet.rules_config || game.rules_config || {})}`,
  ];
  Object.entries(deckSet.files || {}).forEach(([name, file]) => {
    lines.push(`Deck file ${name}: ${file?.path || "unknown"}`);
    lines.push(`Deck file ${name} sha256: ${file?.sha256 || "missing"}`);
  });
  return lines;
}

function englishEventLine(event) {
  if (event.type === "hand_drawn") {
    return `${titleCase(event.player_id)} drew ${englishCardIdList(event.card_ids || [])}.`;
  }
  if (event.type === "orders_submitted") {
    const unused = event.unused_card_ids?.length ? ` Discarded unused: ${englishCardIdList(event.unused_card_ids)}.` : "";
    return `${titleCase(event.player_id)} issued orders: ${plainOrderStacks(event.stacks || [])}.${unused}`;
  }
  if (event.type === "action_revealed") {
    return `${titleCase(event.player_id)} revealed ${englishActionStack(event.action_number, event.cards || [], event.seal_mode)}.`;
  }
  if (event.type === "movement_resolved") {
    return `${titleCase(event.player_id)} action ${event.action_number}: ${(event.steps || []).map(englishMovementStep).join(", ")}.`;
  }
  if (event.type === "volley_resolved") {
    const attackBonus = event.attack_bonus ?? event.aim_bonus ?? 0;
    return `${titleCase(event.attacker_id)} shot ${titleCase(event.target_id)} on action ${event.action_number}: defense ${event.defense_threshold}, rolled ${event.roll} + ${attackBonus} aim = ${event.roll_total}; ${volleyOutcomeText(event)}.`;
  }
  if (event.type === "bauble_awarded") {
    return (event.awards || []).map((award) => {
      const cardText = award.desperation_card_drawn ? ` and drew ${award.desperation_card_id || "a card"}` : "";
      return `${titleCase(award.player_id)} scored ${award.vp_awarded} VP from ${event.bauble?.is_fang ? "Fang" : `Bauble ${event.bauble?.number}`}${cardText}.`;
    }).join("\n");
  }
  if (event.type === "baubles_awarded") return event.message || "No baubles awarded.";
  if (event.type === "hand_discarded") return `${titleCase(event.player_id)} discarded ${englishCardIdList(event.card_ids || [])}.`;
  if (event.type === "phase_changed") return `Phase changed to ${event.phase}.`;
  return "";
}

function plainOrderStacks(stacks) {
  if (!stacks.length) return "orders hidden";
  return stacks.map((stack) => englishActionStack(stack.action_number, stack.cards || [], stack.seal_mode)).join("; ");
}

function canSubmit(playerId) {
  const player = state.selectedState?.players?.[playerId];
  return Boolean(player && state.selectedState.phase === "give_orders" && !player.has_submitted_orders);
}

function canResolve(game) {
  return Boolean(game && !state.resolving && !["give_orders", "complete"].includes(game.phase));
}

function playbackDelay(duration) {
  if (state.playbackSpeed === "instant") return 0;
  const multiplier = state.playbackSpeed === "fast" ? 0.35 : 1;
  return Math.max(0, Math.round((duration || 1200) * multiplier));
}

function playbackGap(duration = 180) {
  if (state.playbackSpeed === "instant") return 0;
  const multiplier = state.playbackSpeed === "fast" ? 0.35 : 1;
  return Math.max(0, Math.round(duration * multiplier));
}

function renderBoard(game) {
  const svg = elements.boardSvg;
  if (!svg) return;
  if (state.isPhone && !state.mobileBoardInitialized) {
    state.zoomScale = 1;
    state.panOffsetX = 0;
    state.panOffsetY = 0;
    state.mobileBoardInitialized = true;
  }
  svg.replaceChildren();

  const extent = BOARD_RADIUS * HEX_SIZE * SQRT3 + HEX_SIZE * 1.5;
  const viewWidth = (extent * 2) / state.zoomScale;
  const viewHeight = (extent * 2) / state.zoomScale;
  const viewX = -extent / state.zoomScale + state.panOffsetX;
  const viewY = -extent / state.zoomScale + state.panOffsetY;
  svg.setAttribute("viewBox", `${viewX} ${viewY} ${viewWidth} ${viewHeight}`);
  svg._volleyPathCounts = new Map();

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
  group.dataset.playerId = player.id;
  group.setAttribute("role", "button");
  group.setAttribute("tabindex", "0");
  group.setAttribute("aria-label", `${titleCase(player.id)} ship status`);

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
  group.addEventListener("click", () => {
    if (!state.isPhone) return;
    state.mobileStatusPlayerId = player.id;
    setMobileStatusOpen(true);
  });
  group.addEventListener("keydown", (event) => {
    if (!state.isPhone || !["Enter", " "].includes(event.key)) return;
    event.preventDefault();
    state.mobileStatusPlayerId = player.id;
    setMobileStatusOpen(true);
  });
  svg.append(group);
}

function renderActionPreview(svg, game) {
  if (game?.phase === "complete") return;
  const player = game?.players?.[state.builderPlayerId];
  if (renderSubmittedOrdersPreview(svg, game)) return;
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
      drawStackMovementPreview(svg, game, player, preview, stack, stackIndex, selections, "");
    } else if (family === "attack") {
      drawStackAttackPreview(svg, game, player, preview, stack, stackIndex, selections, "");
    }
  });
}

function renderSubmittedOrdersPreview(svg, game) {
  const players = Object.values(game?.players || {}).filter((player) => player.prepared_orders);
  if (!players.length) return false;
  const firstUnresolvedStack = firstUnresolvedStackIndex(game.phase);
  players.forEach((player) => {
    const cardById = cardLookupForPlayer(player);
    const preview = {
      q: player.ship.q,
      r: player.ship.r,
      facing: player.ship.facing,
    };
    (player.prepared_orders?.stacks || []).forEach((orderStack, stackIndex) => {
      if (stackIndex < firstUnresolvedStack) return;
      renderStackPreview(svg, game, player, preview, stackFromSubmittedOrder(orderStack), stackIndex, cardById);
    });
  });
  return true;
}

function stackFromSubmittedOrder(orderStack) {
  return {
    action_number: orderStack.action_number,
    seal_mode: orderStack.seal_mode,
    cards: (orderStack.cards || []).map((selection) => selection.card_id),
    faces: (orderStack.cards || []).map((selection) => selection.face || "front"),
    targets: (orderStack.cards || []).map((selection) => selection.target_player_id || ""),
    move_choices: (orderStack.cards || []).map((selection) => selection.orientation || "forward"),
    modes: (orderStack.cards || []).map((selection) => selection.mode || ""),
  };
}

function renderStackPreview(svg, game, player, preview, stack, stackIndex, cardById) {
  const selections = stack.cards
    .map((cardId, cardIndex) => {
      const card = cardById[cardId] || inferCardFromId(cardId);
      return { card, cardIndex, family: effectiveCardFamily(card, stack, cardIndex) };
    })
    .filter((selection) => selection.card && selection.family);
  const family = selections[0]?.family;
  if (family === "move") {
    drawStackMovementPreview(svg, game, player, preview, stack, stackIndex, selections, player.id[0].toUpperCase());
  } else if (family === "attack") {
    drawStackAttackPreview(svg, game, player, preview, stack, stackIndex, selections, player.id[0].toUpperCase());
  }
}

function drawStackMovementPreview(svg, game, player, preview, stack, stackIndex, selections, labelPrefix = "") {
  const passes = stack.seal_mode === "overdrive" ? 2 : 1;
  for (let pass = 0; pass < passes; pass += 1) {
    selections.forEach(({ card, cardIndex, family }) => {
      if (family !== "move") return;
      if (pass > 0 && previewSelectionIsDesperate(card, stack, cardIndex)) return;
      const before = { ...preview };
      const distance = previewSelectionMoveDistance(card, stack, cardIndex);
      const warpDestination = previewSelectionWarpDestination(card, stack, cardIndex);
      if (warpDestination) {
        applyPreviewWarp(game, player, preview, warpDestination);
      } else {
        applyPreviewMove(preview, distance, stack.move_choices[cardIndex], card, stack, cardIndex);
      }
      if (svg) drawMovementPathPreview(svg, before, preview);
      const baseLabel = labelPrefix
        ? `${labelPrefix}${stackIndex + 1}.${cardIndex + 1}`
        : previewMoveLabel(stackIndex, cardIndex, distance, warpDestination);
      if (svg) drawPositionPreview(svg, preview, `${baseLabel}${pass ? " OD" : ""}`);
    });
  }
}

function applyStackMovementToPreview(game, player, preview, stack, cardById) {
  const selections = stack.cards
    .map((cardId, cardIndex) => {
      const card = cardById[cardId] || inferCardFromId(cardId);
      return { card, cardIndex, family: effectiveCardFamily(card, stack, cardIndex) };
    })
    .filter((selection) => selection.card && selection.family === "move");
  if (selections.length) {
    drawStackMovementPreview(null, game, player, preview, stack, 0, selections, "");
  }
}

function drawStackAttackPreview(svg, game, player, preview, stack, stackIndex, selections, labelPrefix = "") {
  attackProjectionsForStack(game, player, preview, stack, stackIndex, null, labelPrefix, selections).forEach((projection) => {
    drawAttackPreview(svg, preview, projection.target, projection.label, projection);
  });
}

function attackProjectionsForStack(game, player, preview, stack, stackIndex, cardById = null, labelPrefix = "", selections = null) {
  const allSelections = selections || stack.cards
    .map((cardId, cardIndex) => {
      const card = cardById?.[cardId] || inferCardFromId(cardId);
      return { card, cardIndex, family: effectiveCardFamily(card, stack, cardIndex) };
    })
    .filter((selection) => selection.card && selection.family);
  const attackSelections = allSelections.filter((selection) => selection.family === "attack");
  const primary = attackProjectionsForSelections(game, player, preview, stack, stackIndex, attackSelections, labelPrefix, false);
  if (stack.seal_mode !== "overdrive") return primary;
  const overdriveSelections = allSelections.filter(({ card, cardIndex, family }) => (
    family === "attack" && !previewSelectionIsDesperate(card, stack, cardIndex)
  ));
  const overdrive = attackProjectionsForSelections(game, player, preview, stack, stackIndex, overdriveSelections, labelPrefix, true);
  return primary.concat(overdrive);
}

function attackProjectionsForSelections(game, player, preview, stack, stackIndex, attackSelections, labelPrefix = "", isOverdriveCopy = false) {
  if (!attackSelections.length) return [];
  const firstAttack = attackSelections.find(({ card, cardIndex }) => effectiveCardRequiresTarget(card, stack, cardIndex));
  const attacksAll = attackSelections.some(({ card, cardIndex }) => previewSelectionAttacksAll(card, stack, cardIndex));
  const targets = attacksAll
    ? Object.values(game.players || {}).filter((candidate) => candidate.id !== player.id)
    : firstAttack && game.players[stack.targets[firstAttack.cardIndex]]
      ? [game.players[stack.targets[firstAttack.cardIndex]]]
      : [];
  const baseLabel = `${labelPrefix}A${stackIndex + 1}${isOverdriveCopy ? " OD" : ""}`;
  return targets.map((target) => ({
    ...attackProjection(player, preview, target, attackSelections, stack),
    isOverdriveCopy,
    label: baseLabel,
    target,
  }));
}

function attackProjection(attacker, shooterPreview, target, attackSelections, stack) {
  const distance = hexDistance(shooterPreview.q, shooterPreview.r, target.ship.q, target.ship.r);
  const damage = previewVolleyDamage(attackSelections, stack);
  const aimBonus = attackSelections.reduce(
    (total, { card, cardIndex }) => total + previewSelectionAimBonus(card, stack, cardIndex),
    0,
  ) + (attacker?.captain_id === "malcolm_manderly" ? 2 : 0);
  const alwaysHits = attackSelections.some(({ card, cardIndex }) => previewSelectionAlwaysHits(card, stack, cardIndex));
  const leadTheTarget = attackSelections.some(({ card, cardIndex }) => previewSelectionLeadTheTarget(card, stack, cardIndex));
  const fixedDefenseThreshold = attackSelections
    .map(({ card, cardIndex }) => previewSelectionFixedDefenseThreshold(card, stack, cardIndex))
    .find((value) => value !== null && value !== undefined);
  const maxRange = attackSelections
    .map(({ card, cardIndex }) => previewSelectionMaxRange(card, stack, cardIndex))
    .find((value) => value !== null && value !== undefined);
  const targetMovement = leadTheTarget ? 0 : (target.ship.movement_this_action || 0);
  const targetDefenseBonus = target.ship.defense_bonus_this_action || 0;
  const defense = fixedDefenseThreshold ?? (distance + targetMovement + targetDefenseBonus);
  const inRange = maxRange === null || maxRange === undefined || distance <= maxRange;
  const targetRoll = Math.max(0, defense - aimBonus);
  return {
    aimBonus,
    alwaysHits,
    damage,
    defense,
    distance,
    fixedDefenseThreshold,
    inRange,
    leadTheTarget,
    maxRange,
    targetDefenseBonus,
    targetMovement,
    targetRoll,
    hitChance: projectedHitChance(targetRoll, alwaysHits, inRange),
  };
}

function projectedHitChance(targetRoll, alwaysHits, inRange) {
  if (!inRange) return 0;
  if (alwaysHits || targetRoll <= 1) return 1;
  const needed = Math.min(12, Math.max(1, Math.ceil(targetRoll)));
  return (13 - needed) / 12;
}

function attackProjectionSummary(projection) {
  const rollText = !projection.inRange
    ? `out of range ${projection.distance}/${projection.maxRange}`
    : projection.alwaysHits
      ? "always hits"
      : `${projection.targetRoll}+ (${formatPercent(projection.hitChance)})`;
  const parts = [
    `${titleCase(projection.target.id)}: ${rollText}`,
    `${projection.damage} damage`,
    `+${projection.aimBonus} Aim`,
    `Defense ${projection.defense}`,
  ];
  if (projection.targetMovement) parts.push(`${projection.targetMovement} target move`);
  if (projection.targetDefenseBonus) parts.push(`+${projection.targetDefenseBonus} defense`);
  if (projection.fixedDefenseThreshold !== null && projection.fixedDefenseThreshold !== undefined) parts.push("fixed defense");
  if (projection.leadTheTarget) parts.push("ignores movement");
  return parts.join(" | ");
}

function formatPercent(value) {
  return `${Math.round(Math.max(0, Math.min(1, value)) * 100)}%`;
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

function previewSelectionIsDesperate(card, stack, cardIndex) {
  return Boolean(selectedFace(card, stack, cardIndex) === "desperate" && card?.desperate_face);
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
    return card.desperate_face.base_damage ?? card.desperate_face.value ?? 1;
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

function previewSelectionLeadTheTarget(card, stack, cardIndex) {
  return Boolean(selectedFace(card, stack, cardIndex) === "desperate" && card?.desperate_face?.lead_the_target);
}

function previewSelectionFixedDefenseThreshold(card, stack, cardIndex) {
  if (selectedFace(card, stack, cardIndex) === "desperate" && card?.desperate_face) {
    return card.desperate_face.fixed_defense_threshold ?? null;
  }
  return null;
}

function previewSelectionMaxRange(card, stack, cardIndex) {
  if (selectedFace(card, stack, cardIndex) === "desperate" && card?.desperate_face) {
    return card.desperate_face.max_range ?? null;
  }
  return null;
}

function previewSelectionAttacksAll(card, stack, cardIndex) {
  return Boolean(selectedFace(card, stack, cardIndex) === "desperate" && card?.desperate_face?.attacks_all);
}

function previewMoveLabel(stackIndex, cardIndex, distance, warpDestination = "") {
  const base = `A${stackIndex + 1}.${cardIndex + 1}`;
  if (warpDestination) return `${base} W`;
  return distance > 0 ? `${base} M${distance}` : base;
}

function applyPreviewMove(preview, distance, choice, card = null, stack = null, cardIndex = 0) {
  const face = selectedFace(card, stack, cardIndex) === "desperate" ? card?.desperate_face : null;
  const turnAfterMove = Boolean(face?.double_turn_after_move);
  if (choice === "u_turn_move" || face?.u_turn_move) {
    preview.facing = (preview.facing + 3) % 6;
  } else if (face?.double_turn_right) {
    preview.facing = (preview.facing + 4) % 6;
  } else if (!turnAfterMove && choice === "turn_left") {
    preview.facing = (preview.facing + 1) % 6;
  } else if (!turnAfterMove && choice === "turn_right") {
    preview.facing = (preview.facing + 5) % 6;
  }
  let movementFacing = preview.facing;
  if (choice === "slip_right") {
    movementFacing = (preview.facing + 5) % 6;
  } else if (choice === "slip_left") {
    movementFacing = (preview.facing + 1) % 6;
  }
  const [dq, dr] = AXIAL_DIRECTIONS[movementFacing % 6];
  preview.q += dq * distance;
  preview.r += dr * distance;
  const clamped = clampToBoard(preview.q, preview.r);
  preview.q = clamped.q;
  preview.r = clamped.r;
  if (turnAfterMove) {
    preview.facing = choice === "turn_left"
      ? (preview.facing + 2) % 6
      : (preview.facing + 4) % 6;
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
  const damage = attackPreview.damage || 0;
  const aimBonus = attackPreview.aimBonus || 0;
  const targetText = !attackPreview.inRange
    ? `RNG ${attackPreview.distance}/${attackPreview.maxRange}`
    : attackPreview.alwaysHits
      ? "HIT"
      : aimBonus
        ? `${attackPreview.targetRoll}+ (+${aimBonus} Aim)`
        : `${attackPreview.targetRoll}+`;
  const curve = volleyCurve(svg, sourceX, sourceY, targetX, targetY);
  const group = svgEl("g");
  group.setAttribute("class", aimBonus || attackPreview.alwaysHits ? "volley-preview bonus-preview" : "volley-preview");

  const path = svgEl("path");
  path.setAttribute("d", `M ${sourceX} ${sourceY} Q ${curve.controlX} ${curve.controlY} ${targetX} ${targetY}`);
  path.setAttribute("stroke", color);

  const arrow = svgEl("polygon");
  arrow.setAttribute("class", "volley-arrowhead");
  arrow.setAttribute("fill", color);
  arrow.setAttribute("points", arrowheadPoints(curve.controlX, curve.controlY, targetX, targetY).map((point) => point.join(",")).join(" "));

  const label = svgEl("text");
  label.setAttribute("x", curve.labelX);
  label.setAttribute("y", curve.labelY);
  label.textContent = `${labelText} ROLL ${targetText} DMG ${damage} ${formatPercent(attackPreview.hitChance)}`;

  const title = svgEl("title");
  title.textContent = attackProjectionSummary({ ...attackPreview, target });

  group.append(path, arrow, label, title);
  svg.append(group);
  drawPositionPreview(svg, shooterPreview, labelText);
}

function volleyCurve(svg, sourceX, sourceY, targetX, targetY) {
  const dx = targetX - sourceX;
  const dy = targetY - sourceY;
  const length = Math.hypot(dx, dy) || 1;
  const normalX = -dy / length;
  const normalY = dx / length;
  const key = `${Math.round(sourceX)},${Math.round(sourceY)}>${Math.round(targetX)},${Math.round(targetY)}`;
  const counts = svg._volleyPathCounts || new Map();
  const index = counts.get(key) || 0;
  counts.set(key, index + 1);
  svg._volleyPathCounts = counts;
  const side = index % 2 === 0 ? 1 : -1;
  const rank = Math.floor(index / 2);
  const offset = side * (HEX_SIZE * (0.72 + rank * 0.48));
  const midX = (sourceX + targetX) / 2;
  const midY = (sourceY + targetY) / 2;
  return {
    controlX: midX + normalX * offset,
    controlY: midY + normalY * offset,
    labelX: midX + normalX * (offset + HEX_SIZE * 0.4),
    labelY: midY + normalY * (offset + HEX_SIZE * 0.4),
  };
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
  const overheatStat = (player) => hasOverheatPile(game)
    ? `<div><dt>Overheat</dt><dd>${player.overheat.length}</dd></div>`
    : "";
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
        ${overheatStat(player)}
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
  if (!elements.eventsView) return;
  const events = game?.event_log || [];
  elements.eventsView.replaceChildren(
    ...events.map((event) => {
      const item = document.createElement("li");
      item.innerHTML = `<strong>${event.type}</strong><pre>${JSON.stringify(event, null, 2)}</pre>`;
      return item;
    }),
  );
}

function renderEndGameSummary(game) {
  const overlay = endGameOverlayElement();
  if (!game || game.phase !== "complete" || state.dismissedEndGameFor === state.selectedGameId) {
    overlay.classList.remove("visible");
    return;
  }
  const summary = endGameSummary(game);
  const winnerText = summary.winners.length === 0
    ? "No Survivors"
    : summary.winners.length > 1
      ? `Tie: ${summary.winners.map(titleCase).join(", ")}`
      : `${titleCase(summary.winners[0])} Wins`;
  overlay.innerHTML = `
    <section class="end-game-panel" role="dialog" aria-modal="true" aria-label="End game summary">
      <div class="end-game-header">
        <div>
          <span>Game Complete</span>
          <strong>${escapeHtml(winnerText)}</strong>
        </div>
        <button type="button" data-end-game-close>Close</button>
      </div>
      <div class="end-game-scoreboard">
        ${summary.players.map((player) => `
          <article class="end-game-player" style="border-left-color: ${SHIP_COLORS[player.id] || "#60706b"}">
            <div class="end-game-player-title">
              <strong>${escapeHtml(titleCase(player.id))}</strong>
              <span>${player.finalVp} VP</span>
            </div>
            <div class="end-game-ship" aria-label="${escapeHtml(player.id)} ship status">
              ${miniShipSvgMarkup(game.players[player.id], game)}
            </div>
            <div class="end-game-stat-grid">
              <div class="summary-stat wide"><span>AI</span><strong>${escapeHtml(AI_TYPES[player.aiType] || player.aiType)}</strong></div>
              <div class="summary-stat"><span>Total VP</span><strong>${player.finalVp}</strong></div>
              <div class="summary-stat"><span>Bauble VP</span><strong>${player.baubleVp}</strong></div>
              <div class="summary-stat"><span>Attack VP</span><strong>${player.attackVp}</strong></div>
              <div class="summary-stat"><span>Baubles</span><strong>${player.baubleCount}</strong></div>
              <div class="summary-stat"><span>Distance</span><strong>${player.distanceMoved}</strong></div>
              <div class="summary-stat"><span>Damage Taken</span><strong>${player.damageSustained}</strong></div>
              <div class="summary-stat"><span>Shots</span><strong>${player.shots}</strong></div>
              <div class="summary-stat"><span>Hit Rate</span><strong>${player.hitPct}</strong></div>
              <div class="summary-stat wide"><span>Hit Most</span><strong>${escapeHtml(player.mostHitTarget)}</strong></div>
              <div class="summary-stat wide"><span>Kills</span><strong>${escapeHtml(player.killsText)}</strong></div>
              <div class="summary-stat wide"><span>Status</span><strong>${escapeHtml(player.killedByText)}</strong></div>
            </div>
          </article>
        `).join("")}
      </div>
      <div class="end-game-overall">
        <strong>Overall</strong>
        <dl>
          <div><dt>Total VP</dt><dd>${summary.overall.totalVp}</dd></div>
          <div><dt>Bauble VP</dt><dd>${summary.overall.baubleVp}</dd></div>
          <div><dt>Attack VP</dt><dd>${summary.overall.attackVp}</dd></div>
          <div><dt>Total damage sustained</dt><dd>${summary.overall.damageSustained}</dd></div>
          <div><dt>Total shots</dt><dd>${summary.overall.shots}</dd></div>
          <div><dt>Hit percentage</dt><dd>${summary.overall.hitPct}</dd></div>
        </dl>
      </div>
    </section>
  `;
  overlay.classList.add("visible");
}

function endGameOverlayElement() {
  if (elements.endGameOverlay) return elements.endGameOverlay;
  const overlay = document.createElement("div");
  overlay.className = "end-game-overlay";
  overlay.addEventListener("click", (event) => {
    if (event.target === overlay || event.target.closest("[data-end-game-close]")) {
      state.dismissedEndGameFor = state.selectedGameId;
      overlay.classList.remove("visible");
    }
  });
  document.body.append(overlay);
  elements.endGameOverlay = overlay;
  return overlay;
}

function endGameSummary(game) {
  const stats = Object.fromEntries(Object.keys(game.players || {}).map((playerId) => [playerId, {
    id: playerId,
    aiType: selectedAiTypeForPlayer(playerId),
    finalVp: game.players[playerId]?.victory_points || 0,
    destroyed: Boolean(game.players[playerId]?.ship?.destroyed),
    damageSustained: game.players[playerId]?.ship?.damage_taken || 0,
    knockout: knockoutInfoForPlayer(game, playerId),
    distanceMoved: 0,
    baubleCount: 0,
    baubleVp: 0,
    hitCount: 0,
    attackVp: 0,
    eventAttackVp: 0,
    shots: 0,
    hitsByTarget: {},
    kills: [],
    killedBy: "",
  }]));
  (game.event_log || []).forEach((event) => {
    if (event.type === "movement_resolved" && stats[event.player_id]) {
      stats[event.player_id].distanceMoved += (event.steps || []).reduce((sum, step) => sum + (step.distance || 0), 0);
    } else if (event.type === "bauble_awarded") {
      (event.awards || []).forEach((award) => {
        if (!stats[award.player_id]) return;
        stats[award.player_id].baubleCount += 1;
        stats[award.player_id].baubleVp += award.vp_awarded || 0;
      });
    } else if (event.type === "volley_resolved" && stats[event.attacker_id]) {
      stats[event.attacker_id].shots += 1;
      if (event.hit) {
        stats[event.attacker_id].hitCount += 1;
        if (event.target_id) {
          stats[event.attacker_id].hitsByTarget[event.target_id] = (stats[event.attacker_id].hitsByTarget[event.target_id] || 0) + 1;
        }
        stats[event.attacker_id].eventAttackVp += event.vp_awarded || 0;
        if (event.target_destroyed && !event.was_destroyed && stats[event.target_id]) {
          stats[event.attacker_id].kills.push(event.target_id);
          stats[event.target_id].killedBy = event.attacker_id;
        }
      }
    }
  });
  const players = Object.values(stats).sort((left, right) => PLAYER_ORDER.indexOf(left.id) - PLAYER_ORDER.indexOf(right.id));
  players.forEach((player) => {
    player.attackVp = Math.max(0, player.finalVp - player.baubleVp);
    player.hitPct = player.shots ? `${Math.round((player.hitCount / player.shots) * 100)}%` : "0%";
    player.mostHitTarget = mostHitTargetText(player.hitsByTarget);
    player.killsText = player.kills.length ? player.kills.map(titleCase).join(", ") : "None";
    player.killedByText = player.destroyed
      ? player.killedBy
        ? `Destroyed by ${titleCase(player.killedBy)}${player.knockout ? ` (${player.knockout})` : ""}`
        : `Destroyed${player.knockout ? ` (${player.knockout})` : ""}`
      : "Survived";
  });
  const resultWinners = Array.isArray(game.result?.winner_ids) ? game.result.winner_ids : null;
  const topVp = Math.max(...players.map((player) => player.finalVp), 0);
  const overallShots = players.reduce((sum, player) => sum + player.shots, 0);
  const overallHits = players.reduce((sum, player) => sum + player.hitCount, 0);
  const overall = {
    totalVp: players.reduce((sum, player) => sum + player.finalVp, 0),
    baubleVp: players.reduce((sum, player) => sum + player.baubleVp, 0),
    attackVp: players.reduce((sum, player) => sum + player.attackVp, 0),
    damageSustained: players.reduce((sum, player) => sum + player.damageSustained, 0),
    shots: overallShots,
    hitPct: overallShots ? `${Math.round((overallHits / overallShots) * 100)}%` : "0%",
  };
  return {
    players,
    overall,
    winners: resultWinners ?? players.filter((player) => player.finalVp === topVp).map((player) => player.id),
  };
}

function knockoutInfoForPlayer(game, playerId) {
  const ship = game?.players?.[playerId]?.ship || {};
  if (ship.knocked_out_round) {
    return formatKnockoutInfo(ship.knocked_out_round, ship.knocked_out_action_number, ship.knocked_out_phase);
  }
  const knockoutEvent = (game?.event_log || []).find((event) => {
    if (event.type === "volley_resolved") {
      return event.target_id === playerId && event.target_destroyed && !event.was_destroyed;
    }
    if (event.type === "bauble_awarded") {
      return (event.awards || []).some((award) => award.player_id === playerId && award.target_destroyed);
    }
    return false;
  });
  if (!knockoutEvent) return "";
  if (knockoutEvent.type === "volley_resolved") {
    return formatKnockoutInfo(knockoutEvent.round, knockoutEvent.action_number, `action_${knockoutEvent.action_number}`);
  }
  return formatKnockoutInfo(knockoutEvent.round, null, "award_baubles");
}

function formatKnockoutInfo(round, actionNumber, phase) {
  const roundText = round ? `Round ${round}` : "Unknown round";
  if (actionNumber) return `${roundText}, Action ${actionNumber}`;
  return `${roundText}, ${formatPhase(phase || "")}`;
}

function formatPhase(phase) {
  return String(phase || "Unknown phase")
    .split("_")
    .filter(Boolean)
    .map(titleCase)
    .join(" ");
}

function mostHitTargetText(hitsByTarget) {
  const entries = Object.entries(hitsByTarget || {});
  if (!entries.length) return "None";
  entries.sort((left, right) => right[1] - left[1] || left[0].localeCompare(right[0]));
  const [targetId, hits] = entries[0];
  return `${titleCase(targetId)} (${hits})`;
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
      state.knownCards[card.id] = normalizeCardMetadata(card);
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
      .map((card) => [card.id, normalizeCardMetadata(card)]),
  );
  const merged = { ...state.knownCards, ...visibleCards };
  Object.entries(merged).forEach(([cardId, card]) => {
    if (!card || cardId === undefined) return;
    merged[cardId] = normalizeCardMetadata(card);
  });
  return merged;
}

function cardsForBuilder(player) {
  const byId = cardLookupForPlayer(player);
  const cards = [...(player?.hand || [])].map((card) => byId[card.id] || normalizeCardMetadata(card));
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
  const hybridPrefixes = [
    "desp_reconfigure",
    "desp_hull_repair",
    "desp_steady_shot",
    "desp_side_slip",
    "desp_drift_king",
    "desp_thrust_ions",
    "desp_crazy_ivan",
    "desp_active_cooling",
  ];
  const hybridIds = new Set([
    "desp_turbo_ions",
    "desp_nightjammer",
    "desp_holdo_maneuver",
    "desp_starshot",
    "desp_scattershot",
    "desp_lead_the_target",
    "desp_overdrive_2x",
  ]);
  const isHybrid = hybridPrefixes.some((prefix) => cardId.startsWith(prefix)) || hybridIds.has(cardId);
  const isBaseAttack = cardId.startsWith("targeted_attack_aim_");
  const family = isHybrid ? "hybrid" : isBaseAttack || cardId.startsWith("desp_crack_shot") ? "attack" : "move";
  const value = Number(cardId.match(/_(\d+)(?:_|$)/)?.[1] || 1);
  const name = family === "attack" ? `Targeted Attack ${value}` : family === "hybrid" ? `Hybrid Card ${value}` : `Controlled Move ${value}`;
  const requiresTarget = cardId.startsWith("desp_crack_shot") || isBaseAttack;
  const noBasicFace = cardId.startsWith("desp_afterburners") || cardId.startsWith("desp_crack_shot");
  return {
    id: cardId,
    name,
    family,
    value,
    is_base: !cardId.startsWith("desp_"),
    requires_target: requiresTarget,
    is_hybrid: isHybrid,
    no_basic_face: noBasicFace,
    desperate_face: inferredDesperateFace(cardId),
    effect: { family, value, requires_target: requiresTarget, is_hybrid: isHybrid },
  };
}

function inferredDesperateFace(cardId) {
  if (cardId.startsWith("desp_afterburners")) {
    return {
      family: "move",
      value: 3,
      orientation_options: ["forward", "turn_right", "turn_left"],
      requires_target: false,
    };
  }
  if (cardId.startsWith("desp_crack_shot")) {
    return {
      family: "attack",
      value: 0,
      base_damage: 1,
      damage_bonus: 1,
      orientation_options: ["up"],
      requires_target: true,
    };
  }
  return null;
}

function normalizeCardMetadata(card) {
  if (!card?.id) return card;
  const inferred = inferCardFromId(card.id);
  return {
    ...inferred,
    ...card,
    is_hybrid: card.is_hybrid ?? inferred.is_hybrid,
    no_basic_face: card.no_basic_face ?? inferred.no_basic_face,
    desperate_face: card.desperate_face ?? inferred.desperate_face,
    effect: {
      ...(inferred.effect || {}),
      ...(card.effect || {}),
    },
  };
}

function renderOrdersBuilder(game) {
  renderBuilderPlayerSelect(game);
  if (!elements.ordersBuilderView || !elements.ordersPreview || !elements.submitBuiltOrdersButton) return;
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
  if (!elements.builderPlayerSelect) return;
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

function renderDebugDesperationDraw(game) {
  if (!elements.debugDesperationSelect || !elements.debugDrawDesperationButton) return;
  const cardTypes = desperationCardTypes(game);
  if (!cardTypes.some((card) => card.id === state.debugDesperationCardId)) {
    state.debugDesperationCardId = cardTypes[0]?.id || "";
  }

  elements.debugDesperationSelect.replaceChildren(
    ...cardTypes.map((card) => {
      const option = document.createElement("option");
      option.value = card.id;
      option.textContent = card.name;
      option.selected = card.id === state.debugDesperationCardId;
      return option;
    }),
  );
  elements.debugDesperationSelect.disabled = cardTypes.length === 0;
  elements.debugDrawDesperationButton.disabled = !game || !state.builderPlayerId || !state.debugDesperationCardId;
}

function desperationCardTypes(game) {
  const byName = new Map();
  (game?.desperation_deck?.cards || []).forEach((card) => {
    if (!byName.has(card.name)) byName.set(card.name, card);
  });
  return [...byName.values()].sort((left, right) => left.name.localeCompare(right.name));
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
      <button class="seal-toggle ${stack.seal_mode}" type="button" data-stack="${stackIndex}" data-field="seal_mode"${readOnly ? " disabled" : ""
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
  const attackPreview = renderStackAttackPreviewSummary(game, stack, stackIndex, cardById);
  if (attackPreview) {
    const preview = document.createElement("div");
    preview.className = "stack-attack-preview";
    preview.innerHTML = attackPreview;
    section.append(preview);
  }

  for (let cardIndex = 0; cardIndex < 2; cardIndex += 1) {
    section.append(renderCardSlot(stack, stackIndex, cardIndex, availableCards, cardById, game, readOnly));
  }
  return section;
}

function renderStackAttackPreviewSummary(game, stack, stackIndex, cardById) {
  const player = game?.players?.[state.builderPlayerId];
  if (!game || !player) return "";
  const preview = previewBeforeBuilderStack(game, player, stackIndex, cardById);
  const projections = attackProjectionsForStack(game, player, preview, stack, stackIndex, cardById, "");
  if (!projections.length) return "";

  const targetLines = projections.map((projection) => (
    `<div class="stack-attack-preview-target">
      <strong>${escapeHtml(projection.label)}</strong>
      <span>${escapeHtml(attackProjectionSummary(projection))}</span>
    </div>`
  )).join("");
  const hasOverdrive = projections.some((projection) => projection.isOverdriveCopy);
  const overdriveLine = hasOverdrive
    ? `<p>${escapeHtml("Overdrive repeats non-Desperate attack cards as a second volley.")}</p>`
    : "";
  return `
    <div class="stack-attack-preview-kicker">Shot Preview</div>
    ${targetLines}
    ${overdriveLine}
  `;
}

function previewBeforeBuilderStack(game, player, stackIndex, cardById) {
  const preview = {
    q: player.ship.q,
    r: player.ship.r,
    facing: player.ship.facing,
  };
  const firstUnresolvedStack = firstUnresolvedStackIndex(game.phase);
  state.builderDraft.stacks.forEach((priorStack, priorStackIndex) => {
    if (priorStackIndex < firstUnresolvedStack || priorStackIndex >= stackIndex) return;
    applyStackMovementToPreview(game, player, preview, priorStack, cardById);
  });
  return preview;
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
  const detail = selectedCard ? selectedCardDetail(selectedCard, stack, cardIndex) : "No card";

  slot.innerHTML = `
    <button class="front-card ${cardTone}" type="button" data-stack="${stackIndex}" data-card="${cardIndex}"${readOnly ? " disabled" : ""
    }>
      <span class="card-slot-label">Card ${cardIndex + 1}</span>
      <strong>${selectedCard ? selectedCard.name : "Empty"}</strong>
      <span>${selectedCard ? selectedCard.id : detail}</span>
    </button>
    <button class="hex-choice-summary ${desperateTone}" type="button" data-stack="${stackIndex}" data-card="${cardIndex}"${readOnly ? " disabled" : ""
    }>
      ${detail}
    </button>
  `;
  return slot;
}

function cardNeedsTarget(card) {
  const family = card?.effect?.family ?? card?.family;
  const requiresTarget = card?.effect?.requires_target ?? card?.requires_target;
  return Boolean(family === "attack" && requiresTarget === true);
}

function selectedFace(card, stack, cardIndex) {
  if (!card?.desperate_face) return "front";
  if (card.no_basic_face) return "desperate";
  return stack?.faces?.[cardIndex] === "desperate" ? "desperate" : "front";
}

function selectedOrientation(card, stack, cardIndex) {
  return stack?.move_choices?.[cardIndex] || card?.orientation_options?.[0] || "forward";
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
  if (selectedFace(card, stack, cardIndex) === "desperate") {
    if (selectedOrientation(card, stack, cardIndex) === "u_turn_attack") return "attack";
    if (selectedOrientation(card, stack, cardIndex) === "u_turn_move") return "move";
    if (card.desperate_face?.family === "hybrid") return "";
    return card.desperate_face?.family || "";
  }
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

function cardUseChoices(card, stack, cardById, cardIndex, game = null) {
  const lockedFamily = stackLockedFamily(stack, cardById, cardIndex);
  const choices = [];

  function familyAllowed(family) {
    return !lockedFamily || lockedFamily === family;
  }

  function pushChoice(choice) {
    choices.push({
      ...choice,
      disabled: choice.disabled || !familyAllowed(choice.family),
    });
  }

  function pushAttackTargetChoices(baseChoice) {
    if (!baseChoice.requiresTarget || !game) {
      pushChoice(baseChoice);
      return;
    }
    attackHexChoices(game).filter((target) => !target.disabled).forEach((target) => {
      pushChoice({
        ...baseChoice,
        label: `${baseChoice.label}: ${target.label}`,
        mark: target.mark,
        fill: target.fill || baseChoice.fill,
        target: target.value,
        terminal: true,
        disabled: target.disabled,
      });
    });
  }

  function pushDesperateMoveChoices(face, family) {
    const moveChoices = (face.orientation_options || ["forward"])
      .map((value) => MOVE_CHOICE_BY_VALUE[value] || { value, label: titleCase(value.replaceAll("_", " ")), mark: "" });
    moveChoices.forEach((moveChoice) => {
      const choiceFamily = moveChoice.value === "u_turn_attack" ? "attack" : family === "hybrid" ? "move" : family;
      const requiresTarget = choiceFamily === "attack" && Boolean(face.requires_target);
      const moveLabel = face.double_turn_after_move
        ? `Move ${face.value}, ${moveChoice.value === "turn_left" ? "Turn Left Twice" : "Turn Right Twice"}`
        : moveChoice.label;
      const label = family === "hybrid" || moveChoices.length > 1
        ? `${card.name}: ${moveLabel}`
        : `${card.name} Desperate`;
      pushAttackTargetChoices({
        face: "desperate",
        mode: "",
        family: choiceFamily,
        label,
        mark: moveChoice.mark || (choiceFamily === "attack" ? "D" : "M"),
        fill: choiceFamily === "attack" ? "#c9433f" : "#3f9963",
        orientation: moveChoice.value,
        isDesperate: true,
        desperateFamily: choiceFamily,
        requiresTarget,
        terminal: true,
      });
    });
  }

  if (card.is_hybrid && !card.no_basic_face) {
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
      disabled: !familyAllowed("attack"),
    });
  }

  if (card.desperate_face) {
    const family = card.desperate_face.family;
    if (family === "move" || family === "hybrid") {
      pushDesperateMoveChoices(card.desperate_face, family);
    } else {
      pushAttackTargetChoices({
        face: "desperate",
        mode: "",
        family,
        label: `${card.name} Desperate`,
        mark: "D",
        fill: "#c9433f",
        orientation: card.desperate_face.orientation_options?.[0] || "up",
        isDesperate: true,
        desperateFamily: family,
        requiresTarget: Boolean(card.desperate_face.requires_target),
      });
    }
  }

  if (!card.no_basic_face && !card.is_hybrid && !card.desperate_face) {
    const family = card.family;
    choices.push({
      face: "front",
      mode: "",
      family,
      label: family === "attack" ? "Attack" : "Move",
      mark: family === "attack" ? "A" : "M",
      fill: family === "attack" ? "#c9433f" : "#3f9963",
      disabled: !familyAllowed(family),
    });
  } else if (!card.no_basic_face && !card.is_hybrid && card.family === "move") {
    choices.unshift({
      face: "front",
      mode: "",
      family: "move",
      label: "Basic Move",
      mark: "M",
      fill: "#3f9963",
      disabled: !familyAllowed("move"),
    });
  } else if (!card.no_basic_face && !card.is_hybrid && card.family === "attack") {
    choices.unshift({
      face: "front",
      mode: "",
      family: "attack",
      label: "Basic Attack",
      mark: "A",
      fill: "#c9433f",
      disabled: !familyAllowed("attack"),
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
    if (face.side_slip_direction) return `Desperate: Side Slip ${face.value}`;
    if (face.double_turn_right) return `Desperate: Drift ${face.value}`;
    if (face.double_turn_after_move) return `Desperate: Move ${face.value}, Turn Twice`;
    if (face.u_turn_move) return `Desperate: U-Turn Move ${face.value}`;
    if (face.active_cooling) return `Desperate: Move ${face.value}, Cool`;
    return `Desperate: Move ${face.value}`;
  }
  const parts = [];
  if (face.attacks_all) parts.push("Attack all");
  if (face.fixed_defense_threshold) parts.push(`Defense ${face.fixed_defense_threshold}`);
  if (face.max_range) parts.push(`Range ${face.max_range}`);
  if (face.aim_bonus) parts.push(`+${face.aim_bonus} Aim`);
  if (face.value) parts.push(`Damage ${face.value}`);
  if (face.base_damage && face.base_damage !== 1) parts.push(`Base ${face.base_damage}`);
  if (face.damage_bonus) parts.push(`+${face.damage_bonus} Damage`);
  if (face.always_hits) parts.push("Always hits");
  if (face.lead_the_target) parts.push("Lead target");
  if (face.u_turn_attack) parts.push("U-Turn");
  return `Desperate: ${parts.join(", ") || "Attack mod"}`;
}

function moveChoiceLabel(value) {
  return MOVE_CHOICES.find((choice) => choice.value === value)?.label || "Choose move";
}

function desperateMoveChoiceLabel(face, value) {
  if (face?.double_turn_after_move) {
    return `Move ${face.value}, ${value === "turn_left" ? "Turn Left Twice" : "Turn Right Twice"}`;
  }
  if (value === "u_turn_attack") return "U-Turn Attack";
  if (value === "u_turn_move") return "U-Turn Move";
  return moveChoiceLabel(value);
}

function selectedCardDetail(card, stack, cardIndex) {
  const face = selectedFace(card, stack, cardIndex);
  const family = effectiveCardFamily(card, stack, cardIndex);
  if (face === "desperate") {
    if (family === "attack" && effectiveCardRequiresTarget(card, stack, cardIndex)) {
      return `${desperateFaceLabel(card)}: ${targetChoiceLabel(stack.targets[cardIndex])}`;
    }
    if (family === "move" && moveChoicesForCard(card, stack, cardIndex).length > 1) {
      return `Desperate: ${desperateMoveChoiceLabel(card.desperate_face, stack.move_choices[cardIndex])}`;
    }
    if (card.desperate_face?.family === "hybrid") {
      return `Desperate: ${desperateMoveChoiceLabel(card.desperate_face, stack.move_choices[cardIndex])}`;
    }
    return desperateFaceLabel(card);
  }
  if (card.is_hybrid) return hybridModeLabel(stack.modes[cardIndex]);
  if (card.family === "attack") {
    return effectiveCardRequiresTarget(card, stack, cardIndex)
      ? targetChoiceLabel(stack.targets[cardIndex])
      : "Forward-line attack";
  }
  return moveChoiceLabel(stack.move_choices[cardIndex]);
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
      const choices = cardUseChoices(card, stack, cardById, cardIndex, game);
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
  stack.targets[cardIndex] = choice?.target || "";
  stack.move_choices[cardIndex] = choice?.orientation || "forward";
  stack.modes[cardIndex] = choice?.mode || "";
  applyDefaultAttackTarget(stack, cardIndex);
  hideCardPickerOverlay();
  renderAll();
  if (choice?.terminal || !showFollowupChoicePanel(stackIndex, cardIndex)) {
    showNextCardPickerIfNeeded(stackIndex, cardIndex);
  }
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
  if (!card) return MOVE_CHOICES.slice(0, 3);
  const face = cardIndex === null ? "front" : selectedFace(card, stack, cardIndex);
  const options = face === "desperate"
    ? card.desperate_face?.orientation_options
    : (card.effect?.orientation_options ?? card.orientation_options);
  return (options || ["forward"])
    .map((value) => MOVE_CHOICE_BY_VALUE[value] || { value, label: titleCase(value.replaceAll("_", " ")), mark: "" });
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
  cardUseChoices(card, stack, cardById, cardIndex, game).forEach((choice) => {
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
  if (!game || !player || !stack || !card || !canSubmit(state.builderPlayerId)) return false;

  const family = effectiveCardFamily(card, stack, cardIndex);
  if (family === "attack") {
    if (stack.targets[cardIndex]) return false;
    if (effectiveCardRequiresTarget(card, stack, cardIndex) && !stackHasTargetedAttack(stack, cardLookupForPlayer(player), cardIndex)) {
      showHexChoicePanel(stackIndex, cardIndex);
      return true;
    }
    return false;
  }

  if (family === "move" && moveChoicesForCard(card, stack, cardIndex).length > 1) {
    if (selectedFace(card, stack, cardIndex) === "desperate") return false;
    showHexChoicePanel(stackIndex, cardIndex);
    return true;
  }
  return false;
}

function showNextCardPickerIfNeeded(stackIndex, cardIndex) {
  const stack = state.builderDraft.stacks[stackIndex];
  if (!stack || cardIndex !== 0 || stack.cards[1] || !canSubmit(state.builderPlayerId)) return;
  showCardPicker(stackIndex, 1);
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
      showNextCardPickerIfNeeded(stackIndex, cardIndex);
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
            orientation: family === "move" || (face === "desperate" && card?.desperate_face?.family === "hybrid")
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

  const cardById = Object.fromEntries((player.hand || []).map((card) => [card.id, normalizeCardMetadata(card)]));
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

elements.createButton?.addEventListener("click", () => createGame().catch(showError));
elements.themeToggleButton?.addEventListener("click", () => {
  const nextTheme = state.theme === "dark" ? "light" : "dark";
  window.localStorage?.setItem("starshotTheme", nextTheme);
  applyTheme(nextTheme);
});
elements.createGameControls?.addEventListener("click", (event) => {
  const button = event.target.closest("[data-player-count]");
  if (!button) return;
  createGame(button.dataset.playerCount).catch(showError);
});
elements.refreshButton.addEventListener("click", () => refreshGames().catch(showError));
elements.exportLogButton?.addEventListener("click", () => exportGameLog().catch(showError));
elements.redOrdersButton?.addEventListener("click", () => submitAiOrders("red").catch(showError));
elements.blueOrdersButton?.addEventListener("click", () => submitAiOrders("blue").catch(showError));
elements.aiControls?.addEventListener("change", (event) => {
  const select = event.target.closest("[data-ai-player]");
  if (!select) return;
  state.selectedAiTypes[select.dataset.aiPlayer] = select.value;
});
elements.aiControls?.addEventListener("click", (event) => {
  const button = event.target.closest("[data-ai-submit]");
  if (!button) return;
  submitAiOrders(button.dataset.aiSubmit).catch(showError);
});
elements.playbackSpeedSelect?.addEventListener("change", (event) => {
  if (event.target.value === "play_game") {
    playEntireGame().catch(showError);
    return;
  }
  state.playbackSpeed = event.target.value;
});
elements.resolveButton.addEventListener("click", () => resolveNextStep().catch(showError));
elements.replayGameButton?.addEventListener("click", () => replayFinishedGame().catch(showError));
elements.resultsSummaryButton?.addEventListener("click", showResultsSummary);
elements.submitBuiltOrdersButton.addEventListener("click", () => submitBuiltOrders().catch(showError));
elements.debugDesperationSelect?.addEventListener("change", (event) => {
  state.debugDesperationCardId = event.target.value;
});
elements.debugDrawDesperationButton?.addEventListener("click", () => debugDrawDesperationCard().catch(showError));
elements.aiTypeSelect?.addEventListener("change", (event) => {
  state.selectedAiType = event.target.value;
});
elements.redAiTypeSelect?.addEventListener("change", (event) => {
  state.selectedAiTypes.red = event.target.value;
});
elements.blueAiTypeSelect?.addEventListener("change", (event) => {
  state.selectedAiTypes.blue = event.target.value;
});
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

function clearTransientOverlays() {
  elements.resolutionCallout?.classList.remove("visible");
  hideCombatResultOverlay();
}

function showResolutionCallouts(game, previousEventCount, previousGame = null) {
  const callouts = resolutionCallouts(game, previousEventCount);
  if (!callouts.length) return Promise.resolve(() => { });
  const overlay = resolutionCalloutElement();
  const animationContext = createBoardAnimationContext();
  let index = 0;

  return new Promise((resolve) => {
    function showNext() {
      const callout = callouts[index];
      overlay.className = `resolution-callout visible ${callout.activity ? `activity-${callout.activity}` : ""}`;
      overlay.innerHTML = `
      <strong>${escapeHtml(callout.title)}</strong>
      ${callout.detail ? `<span>${escapeHtml(callout.detail)}</span>` : ""}
    `;
      if (callout.moveStep) animateBoardShip(callout.playerId, callout.moveStep.before, callout.moveStep.after, animationContext);
      if (callout.blast) animateBoardDot(callout.blast.from, callout.blast.to, "attack", callout.blast.impact);
      index += 1;
      window.setTimeout(() => {
        overlay.classList.remove("visible");
        if (index < callouts.length) {
          window.setTimeout(showNext, playbackGap());
        } else {
          window.setTimeout(() => resolve(() => cleanupBoardAnimationContext(animationContext)), playbackGap());
        }
      }, playbackDelay(callout.duration || 1200));
    }

    showNext();
  });
}

function createBoardAnimationContext() {
  return {
    hiddenTokens: new Set(),
    shipGhosts: new Map(),
  };
}

function cleanupBoardAnimationContext(context) {
  context?.shipGhosts?.forEach((ship) => ship.remove());
  context?.hiddenTokens?.forEach((token) => {
    token.style.opacity = "";
  });
}

function resolutionCallouts(game, previousEventCount) {
  const events = (game?.event_log || []).slice(previousEventCount);
  const replayPositions = replayStartingPositions(game, game?.event_log || [], previousEventCount);
  const callouts = [];
  events.forEach((event) => {
    if (event.type === "movement_resolved") {
      const firstStep = (event.steps || [])[0];
      const lastStep = (event.steps || [])[event.steps.length - 1];
      if (!replayPositions[event.player_id] && firstStep?.before) {
        replayPositions[event.player_id] = { ...firstStep.before };
      }
      if (event.overdrive_copy) {
        callouts.push({
          activity: "overdrive",
          title: "OVERDRIVE",
          detail: `${titleCase(event.player_id)} repeats Action ${event.action_number}`,
          duration: 800,
        });
      }
      callouts.push({
        activity: "move",
        playerId: event.player_id,
        title: `${titleCase(event.player_id)} Moves`,
        detail: `Action ${event.action_number}: ${(event.steps || []).map(englishMovementStep).join(", ")}`,
        moveStep: firstStep ? { before: firstStep.before, after: firstStep.after } : null,
      });
      if (lastStep?.after) replayPositions[event.player_id] = { ...lastStep.after };
    } else if (event.type === "volley_resolved") {
      const attackBonus = event.attack_bonus ?? event.aim_bonus ?? 0;
      const rollTotal = event.roll + attackBonus;
      const attacker = event.attacker_position || replayPositions[event.attacker_id] || game.players?.[event.attacker_id]?.ship;
      const target = event.target_position || replayPositions[event.target_id] || game.players?.[event.target_id]?.ship;
      if (event.overdrive_copy) {
        callouts.push({
          activity: "overdrive",
          title: "OVERDRIVE",
          detail: `${titleCase(event.attacker_id)} fires again`,
          duration: 800,
        });
      }
      callouts.push({
        activity: "attack",
        title: `${titleCase(event.attacker_id)} Shoots`,
        detail: `Action ${event.action_number}: ${titleCase(event.target_id)}`,
        duration: 900,
        blast: attacker && target ? { from: attacker, to: target, impact: event.hit ? "hit" : "miss" } : null,
      });
      callouts.push({
        activity: event.hit ? "attack" : "miss",
        title: volleyCalloutTitle(event),
        detail: `Defense ${event.defense_threshold}; rolled ${event.roll} + ${attackBonus} Aim = ${rollTotal}: ${volleyOutcomeText(event)}`,
        duration: 1500,
      });
    } else if (event.type === "bauble_awarded") {
      (event.awards || []).forEach((award) => {
        callouts.push({
          activity: "award",
          title: `${titleCase(award.player_id)} Scores`,
          detail: `+${award.vp_awarded} VP${award.desperation_card_drawn ? ", drew a card" : ""}`,
        });
      });
    }
  });
  return callouts;
}

function replayStartingPositions(game, eventLog, startIndex) {
  const positions = {};
  Object.entries(game?.players || {}).forEach(([playerId, player]) => {
    if (player?.ship) positions[playerId] = { q: player.ship.q, r: player.ship.r, facing: player.ship.facing };
  });
  eventLog.slice(0, startIndex).forEach((event) => {
    if (event.type !== "movement_resolved") return;
    const lastStep = (event.steps || [])[event.steps.length - 1];
    if (lastStep?.after) positions[event.player_id] = { ...lastStep.after };
  });
  eventLog.slice(startIndex).forEach((event) => {
    if (event.type !== "movement_resolved") return;
    const firstStep = (event.steps || [])[0];
    if (firstStep?.before && positions[event.player_id]?._inferredFromFirstMove !== true) {
      positions[event.player_id] = { ...firstStep.before, _inferredFromFirstMove: true };
    }
  });
  Object.keys(positions).forEach((playerId) => {
    delete positions[playerId]._inferredFromFirstMove;
  });
  return positions;
}

function resolutionCalloutElement() {
  if (elements.resolutionCallout) return elements.resolutionCallout;
  const overlay = document.createElement("div");
  overlay.className = "resolution-callout";
  document.body.append(overlay);
  elements.resolutionCallout = overlay;
  return overlay;
}

function animateBoardDot(fromHex, toHex, activity, impact = "") {
  const start = boardScreenPoint(fromHex);
  const end = boardScreenPoint(toHex);
  if (!start || !end) return;
  const dot = document.createElement("div");
  dot.className = `board-motion-dot ${activity === "attack" ? "attack-dot" : "move-dot"}`;
  dot.style.left = `${start.x}px`;
  dot.style.top = `${start.y}px`;
  dot.style.setProperty("--motion-x", `${end.x - start.x}px`);
  dot.style.setProperty("--motion-y", `${end.y - start.y}px`);
  document.body.append(dot);
  window.setTimeout(() => {
    dot.remove();
    if (impact) animateBoardImpact(end, impact);
  }, playbackDelay(520));
}

function animateBoardImpact(point, impact) {
  const effect = document.createElement("div");
  effect.className = `board-impact ${impact === "hit" ? "hit-impact" : "miss-impact"}`;
  effect.style.left = `${point.x}px`;
  effect.style.top = `${point.y}px`;
  document.body.append(effect);
  window.setTimeout(() => effect.remove(), playbackDelay(impact === "hit" ? 620 : 420));
}

function animateBoardShip(playerId, fromHex, toHex, context) {
  const start = boardScreenPoint(fromHex);
  const end = boardScreenPoint(toHex);
  if (!start || !end || !playerId) return;
  const staticToken = elements.boardSvg?.querySelector(`.ship-token[data-player-id="${playerId}"]`);
  if (staticToken) {
    staticToken.style.opacity = "0";
    context?.hiddenTokens?.add(staticToken);
  }
  context?.shipGhosts?.get(playerId)?.remove();
  const ship = document.createElement("div");
  ship.className = "board-motion-ship";
  ship.style.background = SHIP_COLORS[playerId] || "#6f5ab8";
  ship.style.left = `${start.x}px`;
  ship.style.top = `${start.y}px`;
  ship.style.setProperty("--motion-x", `${end.x - start.x}px`);
  ship.style.setProperty("--motion-y", `${end.y - start.y}px`);
  ship.textContent = titleCase(playerId).charAt(0);
  document.body.append(ship);
  context?.shipGhosts?.set(playerId, ship);
  window.setTimeout(() => {
    ship.classList.add("settled");
    ship.style.left = `${end.x}px`;
    ship.style.top = `${end.y}px`;
    ship.style.setProperty("--motion-x", "0px");
    ship.style.setProperty("--motion-y", "0px");
  }, playbackDelay(820));
}

function boardScreenPoint(hex) {
  const svg = elements.boardSvg;
  if (!svg || !hex) return null;
  const [x, y] = axialToPixel(hex.q, hex.r);
  const matrix = svg.getScreenCTM();
  if (!matrix) return null;
  const point = svg.createSVGPoint();
  point.x = x;
  point.y = y;
  const screenPoint = point.matrixTransform(matrix);
  return { x: screenPoint.x, y: screenPoint.y };
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
  const detached = (shot.detached_component_ids || []).map(formatComponentId);
  const detachedText = detached.length ? `; detached ${detached.join(", ")}` : "";
  return `<span>Lane ${shot.lane}: ${result}${detachedText}</span>`;
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
  if (state.isPhone && state.mobileStatusPlayerId && colors.includes(state.mobileStatusPlayerId)) {
    colors.sort((left, right) => {
      if (left === state.mobileStatusPlayerId) return -1;
      if (right === state.mobileStatusPlayerId) return 1;
      return PLAYER_ORDER.indexOf(left) - PLAYER_ORDER.indexOf(right);
    });
  }
  elements.leftMiniBoards.replaceChildren(...colors.map((color) => createMiniBoardCard(color, game)));
}

function createMiniBoardCard(color, game) {
  const player = game.players[color];
  const isInactive = !player;

  const card = document.createElement("div");
  card.className = `mini-ship-board ${isInactive ? "inactive" : ""}`;
  card.dataset.playerId = color;
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
  svgContainer.innerHTML = miniShipSvgMarkup(player, game);
  card.append(svgContainer);

  const footer = document.createElement("div");
  footer.className = "mini-ship-footer";
  const overheatStat = hasOverheatPile(game)
    ? `<span class="mini-stat" title="Cards in overheat"><span class="mini-icon overheat-icon">O</span>${player ? player.overheat.length : 0}</span>`
    : "";
  footer.innerHTML = `
    <span class="mini-stat" title="Cards in hand"><span class="mini-icon hand-icon">H</span>${player ? (player.hand?.length ?? 0) : 0}</span>
    <span class="mini-stat" title="Cards in deck"><span class="mini-icon deck-icon">D</span>${player ? player.deck.length : 0}</span>
    <span class="mini-stat" title="Cards in discard"><span class="mini-icon discard-icon">X</span>${player ? (player.discard?.length ?? 0) : 0}</span>
    ${overheatStat}
  `;
  card.append(footer);
  return card;
}

function miniShipSvgMarkup(player, game) {
  let layout = player?.ship?.component_layout;
  if (!layout) {
    const anyActivePlayer = Object.values(game.players || {})[0];
    layout = anyActivePlayer?.ship?.component_layout;
  }
  const destroyedSet = new Set(player?.ship?.destroyed_components || []);
  const shieldCount = player?.ship?.shields || 0;
  const cells = (layout || []).map((comp) => {
    const size = 7;
    const x = size * 1.5 * comp.q;
    const y = size * SQRT3 * (comp.r + comp.q / 2);
    const isDestroyed = destroyedSet.has(comp.id);
    const fill = isDestroyed
      ? MINI_COMPONENT_FILLS.destroyed
      : MINI_COMPONENT_FILLS[comp.type] || MINI_COMPONENT_FILLS.default;
    const points = getMiniHexPoints(x, y, size).map((point) => point.join(",")).join(" ");
    const title = `${comp.name}${isDestroyed ? " (DESTROYED)" : ""}`;
    return `<polygon points="${points}" stroke="#000000" stroke-width="1" fill="${fill}" class="mini-hex-cell ${escapeHtml(comp.type)} ${isDestroyed ? "destroyed" : ""}"><title>${escapeHtml(title)}</title></polygon>`;
  }).join("");
  return `<svg viewBox="-34 -35 68 70" class="mini-ship-svg" role="img" aria-label="Ship component hexes">${miniShieldRingsMarkup(shieldCount)}${cells}</svg>`;
}

function miniShieldRingsMarkup(shieldCount) {
  return [0, 1].map((index) => {
    const isActive = shieldCount > index;
    return `<circle cx="0" cy="0" r="${32 - index * 3}" fill="none" stroke="${isActive ? "#2f8fde" : "#c8cfcc"}" stroke-width="${isActive ? "1.6" : "1.2"}" stroke-dasharray="${isActive ? "" : "3 3"}" opacity="${isActive ? "0.95" : "0.5"}"></circle>`;
  }).join("");
}

function getMiniHexPoints(x, y, size) {
  return Array.from({ length: 6 }, (_, index) => {
    const angle = (Math.PI / 180) * (60 * index);
    return [x + size * Math.cos(angle), y + size * Math.sin(angle)];
  });
}

refreshGames().catch(showError);
