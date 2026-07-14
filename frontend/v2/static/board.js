/* SVG hex board renderer: hex field, baubles, pirate ships, facing, zoom/pan. */
(function () {
  const HEX = 16;               // hex size in svg units
  const SQRT3 = Math.sqrt(3);
  const RADIUS = 14;            // board radius (matches engine hex.py)
  const DIRECTIONS = [[1, 0], [1, -1], [0, -1], [-1, 0], [-1, 1], [0, 1]];
  const SEAT_COLORS = ["#d15252", "#4f86d1", "#3ea86b", "#d4a748"];

  const svg = document.getElementById("board");
  const NS = "http://www.w3.org/2000/svg";

  let zoom = 1, panX = 0, panY = 0;
  let shipLayer = null, baubleLayer = null, hexLayer = null, previewLayer = null, bossLayer = null;
  let seatColorByPlayer = {};
  let nameMap = {};
  let titleMap = {};
  let onShipClick = null;
  let onBossClick = null;
  const shipEls = {};

  function hexDistance(aq, ar, bq, br) {
    return Math.max(Math.abs(aq - bq), Math.abs(ar - br), Math.abs((-aq - ar) - (-bq - br)));
  }

  function axialToXY(q, r) {
    return [HEX * 1.5 * q, HEX * SQRT3 * (r + q / 2)];
  }

  function facingAngle(facing) {
    const [dq, dr] = DIRECTIONS[((facing % 6) + 6) % 6];
    const [x, y] = [1.5 * dq, SQRT3 * (dr + dq / 2)];
    return (Math.atan2(y, x) * 180) / Math.PI;
  }

  function hexPoints(cx, cy, size) {
    const pts = [];
    for (let i = 0; i < 6; i++) {
      const angle = (Math.PI / 180) * (60 * i);
      pts.push(`${cx + size * Math.cos(angle)},${cy + size * Math.sin(angle)}`);
    }
    return pts.join(" ");
  }

  function el(tag, attrs, parent) {
    const node = document.createElementNS(NS, tag);
    for (const key in attrs) node.setAttribute(key, attrs[key]);
    if (parent) parent.appendChild(node);
    return node;
  }

  function applyViewBox() {
    const extent = HEX * SQRT3 * (RADIUS + 2);
    const w = (extent * 2) / zoom;
    svg.setAttribute("viewBox", `${-extent / zoom + panX} ${-extent / zoom + panY} ${w} ${w}`);
  }

  function buildBoard() {
    svg.innerHTML = "";
    hexLayer = el("g", {}, svg);
    baubleLayer = el("g", {}, svg);
    bossLayer = el("g", {}, svg);
    previewLayer = el("g", { "pointer-events": "none" }, svg);
    shipLayer = el("g", {}, svg);
    for (let q = -RADIUS; q <= RADIUS; q++) {
      const rMin = Math.max(-RADIUS, -q - RADIUS);
      const rMax = Math.min(RADIUS, -q + RADIUS);
      for (let r = rMin; r <= rMax; r++) {
        const [x, y] = axialToXY(q, r);
        const rim = Math.max(Math.abs(q), Math.abs(r), Math.abs(-q - r)) === RADIUS;
        el("polygon", { points: hexPoints(x, y, HEX - 0.8), class: "hex-cell" + (rim ? " rim" : "") }, hexLayer);
      }
    }
    applyViewBox();
  }

  function renderBaubles(baubles, roundNumber, options = {}) {
    baubleLayer.innerHTML = "";
    const activeNumbers = new Set(options.activeNumbers || []);
    for (const bauble of baubles || []) {
      const [x, y] = axialToXY(bauble.q, bauble.r);
      const active = bauble.is_fang || bauble.number === roundNumber || activeNumbers.has(bauble.number);
      const group = el("g", { opacity: active ? 1 : 0.55 }, baubleLayer);
      // Scoring zone: the full 7-hex cluster (within 1 hex of the bauble).
      const zoneColor = bauble.is_fang ? "195,62,62" : "212,167,72";
      for (const [dq, dr] of [[0, 0], ...DIRECTIONS]) {
        const [cx, cy] = axialToXY(bauble.q + dq, bauble.r + dr);
        if (hexDistance(0, 0, bauble.q + dq, bauble.r + dr) > RADIUS) continue;
        el("polygon", {
          points: hexPoints(cx, cy, HEX - 0.8),
          fill: `rgba(${zoneColor},${active ? 0.13 : 0.06})`,
          stroke: `rgba(${zoneColor},${active ? 0.45 : 0.2})`,
          "stroke-width": 0.7,
        }, group);
      }
      if (bauble.is_fang) {
        el("circle", { cx: x, cy: y, r: HEX * 0.72, fill: "rgba(195,62,62,.18)", stroke: "#c33e3e", "stroke-width": 1.2, "stroke-dasharray": "3 2" }, group);
        el("text", { x, y: y + 5, "text-anchor": "middle", "font-size": 14, fill: "#ff7d6a" }, group).textContent = "𓆝";
        el("text", { x, y: y + 5, "text-anchor": "middle", "font-size": 13, fill: "#ff9d8a", "font-weight": "700" }, group).textContent = "⋀";
      } else {
        el("circle", { cx: x, cy: y, r: HEX * 0.62, fill: "url(#baubleGrad)", class: "bauble-core", stroke: "#8a6620", "stroke-width": 1 }, group);
        el("text", { x, y: y + 4.5, "text-anchor": "middle", "font-size": 12, "font-weight": 700, fill: "#241a05" }, group).textContent = bauble.number;
      }
      if (bauble.claimed_by && bauble.claimed_by.length) {
        el("text", { x, y: y - HEX * 0.8, "text-anchor": "middle", "font-size": 8, fill: "#d4a748" }, group).textContent = "⚑";
      }
      const title = el("title", {}, group);
      title.textContent = bauble.is_fang
        ? `The Fang — ${roundNumber >= 6 ? 6 : 1} VP, bites for 1 damage`
        : `Bauble ${bauble.number} — ${bauble.victory_points} VP in round ${bauble.number}`;
    }
    ensureDefs();
  }

  function ensureDefs() {
    if (svg.querySelector("defs")) return;
    const defs = el("defs", {}, svg);
    const grad = el("radialGradient", { id: "baubleGrad", cx: "35%", cy: "30%" }, defs);
    el("stop", { offset: "0%", "stop-color": "#f6d98a" }, grad);
    el("stop", { offset: "100%", "stop-color": "#c08a2e" }, grad);
  }

  /* StarBreach: the boss hull, its components, and the enemy fleet dice. */
  const AREA_TINT = {
    forward: "106,140,190", port: "170,110,190", rear: "190,120,80", starboard: "110,170,120",
  };
  const CRAFT_COLORS = { blue: "#4f86d1", green: "#3ea86b", yellow: "#d4c748" };
  const COMPONENT_BADGE = {
    shield_generator: "SG", firing_computer: "FC", fuel_tank: "FT", core: "◉",
  };

  function renderStarBreach(sb, options = {}) {
    if (!bossLayer) return;
    bossLayer.innerHTML = "";
    if (!sb || !sb.boss_layout) return;
    const destroyed = new Set((sb.destroyed_hexes || []).map(([q, r]) => q + "," + r));
    const componentsByHex = {};
    for (const component of sb.boss_layout.components || []) {
      componentsByHex[component.q + "," + component.r] = component;
    }
    for (const cell of sb.boss_layout.footprint || []) {
      const q = sb.anchor_q + cell.q, r = sb.anchor_r + cell.r;
      if (hexDistance(0, 0, q, r) > RADIUS) continue;
      const [x, y] = axialToXY(q, r);
      const dead = destroyed.has(cell.q + "," + cell.r);
      const tint = AREA_TINT[cell.area] || "120,120,120";
      const poly = el("polygon", {
        points: hexPoints(x, y, HEX - 1.2),
        fill: dead ? "rgba(30,30,38,.85)" : `rgba(${tint},.55)`,
        stroke: dead ? "#333" : `rgb(${tint})`,
        "stroke-width": 1,
        class: "boss-hull",
        "data-area": cell.area,
      }, bossLayer);
      poly.addEventListener("click", () => { if (onBossClick) onBossClick(cell.area); });
      const component = componentsByHex[cell.q + "," + cell.r];
      if (component) {
        const badge = el("text", {
          x, y: y + 3.5, "text-anchor": "middle", "font-size": 9, "font-weight": 700,
          fill: dead ? "#666" : "#0a0f1e", "pointer-events": "none",
        }, bossLayer);
        badge.textContent = COMPONENT_BADGE[component.type] || "?";
        const tip = el("title", {}, poly);
        tip.textContent = `${component.name}${dead ? " (destroyed)" : ""} — ${cell.area} section`;
      } else if (dead) {
        el("text", { x, y: y + 4, "text-anchor": "middle", "font-size": 10, fill: "#555", "pointer-events": "none" }, bossLayer)
          .textContent = "✕";
      } else {
        const tip = el("title", {}, poly);
        tip.textContent = `StarBreacher hull — ${cell.area} section (shield ${sb.shield_hp?.[cell.area] ?? 0})`;
      }
    }
    for (const craft of sb.fleet || []) {
      if (craft.destroyed) continue;
      const [x, y] = axialToXY(craft.q, craft.r);
      const color = CRAFT_COLORS[craft.color] || "#999";
      const group = el("g", { transform: `translate(${x},${y})` }, bossLayer);
      el("rect", { x: -7, y: -7, width: 14, height: 14, rx: 3, fill: color, stroke: "#0a0f1e", "stroke-width": 1.4 }, group);
      el("text", { x: 0, y: 4, "text-anchor": "middle", "font-size": 10, "font-weight": 700, fill: "#0a0f1e" }, group)
        .textContent = String(craft.hp);
      const tip = el("title", {}, group);
      tip.textContent = `${craft.color} Hunter-Killer — ${craft.hp}/${craft.max_hp} HP`;
      el("text", { x: 0, y: 17, class: "ship-label", "font-size": 7.5 }, group).textContent = "HK " + craft.color;
    }
    if (options.preyPos) {
      const [x, y] = axialToXY(options.preyPos.q, options.preyPos.r);
      el("circle", {
        cx: x, cy: y, r: HEX * 1.05, fill: "none", stroke: "#ff5a5a",
        "stroke-width": 1.4, "stroke-dasharray": "5 3", opacity: 0.9, "pointer-events": "none",
      }, bossLayer);
      el("text", { x, y: y - HEX * 1.2, "text-anchor": "middle", "font-size": 8, fill: "#ff8a7a", "pointer-events": "none" }, bossLayer)
        .textContent = "PREY";
    }
  }

  function shipMarkup(color) {
    // Angular corsair hull, drawn facing +x.
    return `
      <polygon class="ship-hull" points="14,0 -6,8 -2,3 -10,4 -10,-4 -2,-3 -6,-8"
        fill="${color}" stroke="#0a0f1e" stroke-width="1.4"/>
      <polygon points="1,0 -5,3.4 -5,-3.4" fill="rgba(10,15,30,.55)"/>
      <circle cx="4" cy="0" r="2.1" fill="#0a0f1e"/>
      <circle cx="4" cy="0" r="1.1" fill="#f2c96a"/>`;
  }

  function renderShips(players, seatOrder, youId) {
    shipLayer.innerHTML = "";
    seatColorByPlayer = {};
    Object.keys(shipEls).forEach((key) => delete shipEls[key]);
    (seatOrder || Object.keys(players)).forEach((playerId, index) => {
      const player = players[playerId];
      if (!player) return;
      const color = SEAT_COLORS[index % SEAT_COLORS.length];
      seatColorByPlayer[playerId] = color;
      const ship = player.ship || {};
      const [x, y] = axialToXY(ship.q || 0, ship.r || 0);
      const group = el("g", {
        class: "ship-token" + (ship.destroyed ? " dead" : "") + (playerId !== youId && !ship.destroyed ? " targetable" : ""),
        transform: `translate(${x},${y})`,
        "data-player": playerId,
      }, shipLayer);
      const body = el("g", { transform: `rotate(${facingAngle(ship.facing || 0)})` }, group);
      body.innerHTML = shipMarkup(color);
      if ((ship.shields || 0) > 0 && !ship.destroyed) {
        el("circle", { cx: 0, cy: 0, r: 17, fill: "none", stroke: "#3ea8d8", "stroke-width": 1.1, "stroke-dasharray": "4 3", opacity: 0.8 }, group);
        if (ship.shields > 1) {
          el("circle", { cx: 0, cy: 0, r: 20, fill: "none", stroke: "#3ea8d8", "stroke-width": 0.8, "stroke-dasharray": "3 4", opacity: 0.5 }, group);
        }
      }
      const label = el("text", { x: 0, y: 29, class: "ship-label" }, group);
      label.textContent =
        (playerId === youId ? "★ " : "") + shortName(playerId);
      if (titleMap[playerId] === "Pirate King") label.textContent = "Cpt.";
      group.addEventListener("click", () => { if (onShipClick) onShipClick(playerId); });
      shipEls[playerId] = { group, body };
    });
  }

  function shortName(playerId) {
    const mapped = nameMap[playerId];
    if (mapped) {
      // Last word of the display name reads best on the board ("Ironjaw").
      const words = mapped.split(" ");
      return words[words.length - 1];
    }
    if (playerId.startsWith("ai:")) return "Drone";
    return playerId.length > 12 ? playerId.slice(0, 11) + "…" : playerId;
  }

  /* Move a ship token (used by the replay animator). */
  function placeShip(playerId, q, r, facing) {
    const entry = shipEls[playerId];
    if (!entry) return;
    const [x, y] = axialToXY(q, r);
    entry.group.setAttribute("transform", `translate(${x},${y})`);
    entry.body.setAttribute("transform", `rotate(${facingAngle(facing)})`);
  }

  /* Toggle the destroyed look during replays: ships sail alive until the
     moment the replay sinks them, regardless of the final state. */
  function setShipDead(playerId, dead) {
    const entry = shipEls[playerId];
    if (!entry) return;
    entry.group.classList.toggle("dead", !!dead);
  }

  /* Hex coord -> pixel position within the board-wrap element (for canvas FX). */
  function hexToScreen(q, r) {
    const [x, y] = axialToXY(q, r);
    const point = svg.createSVGPoint();
    point.x = x; point.y = y;
    const ctm = svg.getScreenCTM();
    if (!ctm) return { x: 0, y: 0 };
    const screen = point.matrixTransform(ctm);
    const rect = svg.getBoundingClientRect();
    return { x: screen.x - rect.left, y: screen.y - rect.top };
  }

  function setZoom(delta) {
    zoom = Math.min(3.2, Math.max(0.55, zoom * delta));
    applyViewBox();
  }
  function resetView() { zoom = 1; panX = 0; panY = 0; applyViewBox(); }

  function isPhoneBoard() {
    return document.documentElement.dataset.device === "phone";
  }

  function viewScale() {
    const rect = svg.getBoundingClientRect();
    const extent = HEX * SQRT3 * (RADIUS + 2);
    return rect.width ? (extent * 2) / zoom / rect.width : 1;
  }

  // drag to pan
  let dragging = false, lastX = 0, lastY = 0;
  svg.addEventListener("mousedown", (event) => {
    if (isPhoneBoard()) return;
    dragging = true; lastX = event.clientX; lastY = event.clientY;
  });
  window.addEventListener("mouseup", () => { dragging = false; });
  window.addEventListener("mousemove", (event) => {
    if (!dragging) return;
    const scale = viewScale();
    panX -= (event.clientX - lastX) * scale;
    panY -= (event.clientY - lastY) * scale;
    lastX = event.clientX; lastY = event.clientY;
    applyViewBox();
  });
  svg.addEventListener("wheel", (event) => { event.preventDefault(); setZoom(event.deltaY < 0 ? 1.12 : 0.89); }, { passive: false });

  let touchGesture = null;
  const touchPoints = (event) => [...event.touches].map((touch) => ({ x: touch.clientX, y: touch.clientY }));
  const midpoint = (points) => ({
    x: points.reduce((total, point) => total + point.x, 0) / points.length,
    y: points.reduce((total, point) => total + point.y, 0) / points.length,
  });
  const distance = (left, right) => Math.hypot(left.x - right.x, left.y - right.y);

  svg.addEventListener("touchstart", (event) => {
    if (!isPhoneBoard()) return;
    const points = touchPoints(event);
    if (!points.length) return;
    event.preventDefault();
    touchGesture = {
      points,
      center: midpoint(points),
      distance: points.length > 1 ? distance(points[0], points[1]) : 0,
      zoom,
      panX,
      panY,
    };
  }, { passive: false });
  svg.addEventListener("touchmove", (event) => {
    if (!isPhoneBoard() || !touchGesture) return;
    const points = touchPoints(event);
    if (!points.length) return;
    event.preventDefault();
    const center = midpoint(points);
    if (points.length > 1 && touchGesture.points.length > 1) {
      const ratio = touchGesture.distance ? distance(points[0], points[1]) / touchGesture.distance : 1;
      zoom = Math.min(3.2, Math.max(0.62, touchGesture.zoom * ratio));
    }
    const scale = viewScale();
    panX = touchGesture.panX - (center.x - touchGesture.center.x) * scale;
    panY = touchGesture.panY - (center.y - touchGesture.center.y) * scale;
    applyViewBox();
  }, { passive: false });
  svg.addEventListener("touchend", () => { touchGesture = null; });
  svg.addEventListener("touchcancel", () => { touchGesture = null; });

  document.getElementById("zoom-in").addEventListener("click", () => setZoom(1.2));
  document.getElementById("zoom-out").addEventListener("click", () => setZoom(0.83));
  document.getElementById("zoom-fit").addEventListener("click", resetView);

  /* Order-preview drawing. items: array of
     {kind:"path", points:[{q,r}...], color}
     {kind:"ghost", q, r, facing, label, color}
     {kind:"shot", from:{q,r}, to:{q,r}, label, color} */
  function renderPreview(items) {
    if (!previewLayer) return;
    previewLayer.innerHTML = "";
    const shotCounts = new Map();
    for (const item of items || []) {
      if (item.kind === "path" && item.points.length > 1) {
        const pts = item.points.map((p) => axialToXY(p.q, p.r).join(",")).join(" ");
        el("polyline", {
          points: pts, fill: "none", stroke: item.color || "#d4a748",
          "stroke-width": 1.6, "stroke-dasharray": "5 4", opacity: 0.85,
        }, previewLayer);
      } else if (item.kind === "ghost") {
        const [x, y] = axialToXY(item.q, item.r);
        const group = el("g", { transform: `translate(${x},${y})`, opacity: 0.85 }, previewLayer);
        el("polygon", {
          points: "10,0 -6,6 -6,-6",
          transform: `rotate(${facingAngle(item.facing)})`,
          fill: "none", stroke: item.color || "#d4a748", "stroke-width": 1.6, "stroke-dasharray": "3 2",
        }, group);
        el("text", { x: 0, y: -13, class: "ship-label", "font-size": 8.5 }, group).textContent = item.label || "";
      } else if (item.kind === "shot") {
        const [x1, y1] = axialToXY(item.from.q, item.from.r);
        const [x2, y2] = axialToXY(item.to.q, item.to.r);
        const angle = Math.atan2(y2 - y1, x2 - x1);
        const trimX = x2 - Math.cos(angle) * 14;
        const trimY = y2 - Math.sin(angle) * 14;
        const curve = shotCurve(x1, y1, trimX, trimY, shotCounts);
        el("path", {
          d: `M ${x1} ${y1} Q ${curve.cx} ${curve.cy} ${trimX} ${trimY}`,
          fill: "none", stroke: item.color || "#ff6a4a",
          "stroke-width": 1.6, "stroke-dasharray": "2 3", opacity: 0.9,
        }, previewLayer);
        const headAngle = Math.atan2(trimY - curve.cy, trimX - curve.cx);
        const headA = headAngle + 2.6, headB = headAngle - 2.6;
        el("polygon", {
          points: `${trimX},${trimY} ${trimX + Math.cos(headA) * 6},${trimY + Math.sin(headA) * 6} ${trimX + Math.cos(headB) * 6},${trimY + Math.sin(headB) * 6}`,
          fill: item.color || "#ff6a4a", opacity: 0.9,
        }, previewLayer);
        const label = el("text", { x: curve.lx, y: curve.ly, class: "ship-label", "font-size": 9.5, fill: "#ffd7a0" }, previewLayer);
        label.textContent = item.label || "";
        if (item.title) {
          const title = el("title", {}, label);
          title.textContent = item.title;
        }
      }
    }
  }

  function shotCurve(x1, y1, x2, y2, counts) {
    const dx = x2 - x1, dy = y2 - y1;
    const length = Math.hypot(dx, dy) || 1;
    const nx = -dy / length, ny = dx / length;
    const key = `${Math.round(x1)},${Math.round(y1)}>${Math.round(x2)},${Math.round(y2)}`;
    const index = counts.get(key) || 0;
    counts.set(key, index + 1);
    const side = index % 2 === 0 ? 1 : -1;
    const rank = Math.floor(index / 2);
    const offset = side * (HEX * (1.15 + rank * 0.75));
    const midX = (x1 + x2) / 2, midY = (y1 + y2) / 2;
    return {
      cx: midX + nx * offset,
      cy: midY + ny * offset,
      lx: midX + nx * (offset + HEX * 0.58),
      ly: midY + ny * (offset + HEX * 0.58) - 4,
    };
  }

  window.Board = {
    build: buildBoard,
    renderBaubles,
    renderStarBreach,
    setBossClickHandler: (fn) => { onBossClick = fn; },
    renderShips,
    placeShip,
    setShipDead,
    hexToScreen,
    renderPreview,
    clearPreview: () => renderPreview([]),
    resetView,
    colorOf: (playerId) => seatColorByPlayer[playerId] || "#d4a748",
    shortName,
    setNameMap: (map) => { nameMap = map || {}; },
    setTitleMap: (map) => { titleMap = map || {}; },
    setShipClickHandler: (fn) => { onShipClick = fn; },
    hexDistance,
    DIRECTIONS,
    RADIUS,
  };
})();
