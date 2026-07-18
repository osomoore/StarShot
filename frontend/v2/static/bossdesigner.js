/* Boss Ship Designer.
 *
 * Self-contained: builds its own DOM inside a host element and talks only to
 * its design API. Two instances exist:
 *   - admin  (admin page tab #tab-bossdesign, /api/v2/admin/boss-designs),
 *     which also gets a player-design browse/clone bar
 *   - player (full-screen overlay on the main app, /api/v2/my/boss-designs,
 *     capped library — players may fight their own creations)
 * Edit modes over one SVG hex board:
 *   structure     — paint hull tiles (generic / shield gen / cannon /
 *                   engine / core)
 *   shields+lanes — per shield region: protected hexes, powering generator,
 *                   and the seven d8 damage lanes (rolls 2-8)
 *   progression   — progression triggers and the step track
 *   stacks        — the battle-board organizer with a mini ship view
 */
(function () {
  "use strict";

  function createBossDesigner(config) {
  const API = config.apiBase;
  const isAdmin = !!config.isAdmin;
  const root = config.root;
  const SQ = Math.sqrt(3);
  const SIZE = 17; // hex circumradius in svg units
  const DIRS = [[1, 0], [1, -1], [0, -1], [-1, 0], [-1, 1], [0, 1]];

  // Server meta (refreshed from the list endpoint; these are the fallbacks).
  let META = {
    grid_radius: 7,
    action_stacks: ["0.5", "1.5", "2.5", "3.5", "starbreach"],
    lane_rolls: [2, 3, 4, 5, 6, 7, 8],
    trigger_types: [
      "vault_pickup_boss", "vault_pickup_fleet",
      "prey_hull_damage_boss", "prey_hull_damage_fleet", "player_kill",
    ],
    spawn_locations: ["boss_front", "vault", "fang"],
    spawn_max_count: 3,
    fleet_max_action_count: 9,
    player_design_limit: 10,
  };

  const TILE_TOOLS = [
    { type: "generic", label: "Generic", badge: "" },
    { type: "shield_gen", label: "Shield Gen", badge: "SG" },
    { type: "cannon", label: "Cannon", badge: "C" },
    { type: "engine", label: "Engine", badge: "E" },
    { type: "docking_bay", label: "Docking Bay", badge: "D" },
    { type: "core", label: "Core", badge: "◉" },
    { type: "signal_jammer", label: "Sig. Jammer", badge: "J" },
    { type: "targeting_sensors", label: "Targeting", badge: "T" },
    { type: "erase", label: "Eraser", badge: "✕" },
  ];
  const TILE_FILL = {
    generic: "154,163,184", shield_gen: "120,190,255", cannon: "255,140,120",
    engine: "255,205,110", docking_bay: "255,122,208", core: "222,160,255",
    signal_jammer: "120,240,205", targeting_sensors: "255,150,210",
  };
  // Passive abilities: no action-stack element; active while the component is
  // intact, or granted by an "ability link" progression square.
  const ABILITY_LABELS = {
    signal_jammer: "Signal Jammer (+2 defense)",
    targeting_sensors: "Targeting Sensors (+2 Aim)",
  };
  const ABILITY_SHORT = { signal_jammer: "J", targeting_sensors: "T" };
  const REGION_COLORS = ["#59c8ff", "#ff9d6b", "#9dff8a", "#ffd75e", "#ff7ad0",
    "#8f9dff", "#6bffd8", "#ff6b6b", "#d0ff5e"];
  const STACK_SHORT = { "0.5": "0.5", "1.5": "1.5", "2.5": "2.5", "3.5": "3.5", starbreach: "SB" };
  const FLEET_STACKS = ["0.5", "1.5", "2.5", "3.5"];
  const FLEET_MAX_ACTION_COUNT = 9;
  const TRIGGER_LABELS = {
    vault_pickup_boss: "Vault pickup — boss",
    vault_pickup_fleet: "Vault pickup — boss fleet",
    prey_hull_damage_boss: "Prey hull damage — boss",
    prey_hull_damage_fleet: "Prey hull damage — boss fleet",
    player_kill: "Kill a player ship",
  };
  const ACTION_SYMBOL = { attack: "☄", move: "➤", shoot: "☄", breacher: "◉", spawn: "□", ability: "⚡", filler: "·", super: "✹" };
  const AI_LABELS = {
    hunter_killer: "Hunter-Killer — close on the Prey, shoot the Prey",
    vault_runner: "Vault Runner — harvest the current vault, or next round's if out of reach",
    blaster: "Blaster — move to and shoot the nearest player ship",
    dynamic: "Dynamic — reacts to player activity, switching targets up to once per round",
  };
  const SUPER_LABELS = {
    immobilizer_shot: "Immobilizer Shot — cancel target's movement this round",
    tractor_beam: "Tractor Beam — pull target inward 2 hexes",
    knockback: "Knockback — push target outward 2 hexes",
    inferno_zone: "Inferno Zone — damage all ships within 3 hexes",
    infuser: "Infuser — fleet gets 3 immediate move actions",
    chain_shot: "Chain Shot — attack arcs between ships within 4 hexes",
    scattershot: "ScatterShot — attack all players in a 120° spread",
    mark_the_prey: "Mark the Prey — Prey takes -5 defense this round",
    mine_dropper: "Mine Dropper — drop a mine (3 dmg within 2 hexes)",
  };
  const SUPER_TRIGGER_LABELS = {
    round: "from round",
    progress: "from progression step",
  };
  const GOAL_LABELS = {
    escape_fang: "Escape — The Prey reaches The Fang by round 6 (classic)",
    capture_vaults: "Heist — capture at least N vaults as a crew",
    destroy_fleet: "Fleet wipe — eliminate the entire fleet (boss optional)",
  };

  // ── state ────────────────────────────────────────────────────────────────
  let booted = false;
  let designs = [];        // list summaries
  let design = null;       // the open design document (canonical schema)
  let dirty = false;
  let mode = "structure";  // structure | shields | progression
  let tool = { type: "generic", number: 1, stack: "0.5" };
  let currentRegion = null; // ship region number being edited
  let shieldSub = "hexes";  // hexes | power | lanes
  let stackLanes = false;   // lanes sub-mode: clicks stack a second lane on a hex
  let printTone = "color";  // color | bw
  let printOptions = {
    lanes: true, laneList: false, stacks: true, stackLinks: false, coords: false,
    components: false, progression: true, fleet: true,
  };
  let printZoom = 1; // ship-drawing scale multiplier (0.5 - 2.0)
  let boardView = null; // {x, y, w, h} viewBox while zoomed/panned; null = fit all

  // ── tiny helpers ─────────────────────────────────────────────────────────
  const esc = (v) => String(v ?? "").replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[c]));
  const key = (q, r) => q + "," + r;
  const xy = (q, r) => [SIZE * 1.5 * q, SIZE * SQ * (r + q / 2)];

  async function call(path, options = {}) {
    const response = await fetch(API + path, {
      headers: { "Content-Type": "application/json" },
      credentials: "same-origin",
      ...options,
    });
    let payload = null;
    try { payload = await response.json(); } catch (err) { /* none */ }
    if (!response.ok) {
      let detail = (payload && payload.detail) || `Request failed (${response.status})`;
      if (response.status === 404 && detail === "Not Found") {
        detail = "Not Found — the running server predates the Boss Designer; restart the server.";
      }
      throw new Error(detail);
    }
    return payload;
  }

  const el = (id) => root().querySelector("#" + id);

  function setStatus(message, ok) {
    const node = el("bd-status");
    node.textContent = message || "";
    node.className = "admin-status " + (ok ? "ok" : "err");
  }

  function markDirty() {
    dirty = true;
    el("bd-save").classList.add("attention");
  }

  // ── design geometry helpers ──────────────────────────────────────────────
  const footprintSet = () => new Set(design.tiles.map((t) => key(t.q, t.r)));
  const tileAt = (q, r) => design.tiles.find((t) => t.q === q && t.r === r) || null;

  /* Components auto-number per type in placement order (matches the game
     engine), so the organizer can say "Engine 1" instead of coordinates. */
  const COMPONENT_LABEL = {
    cannon: "Cannon", engine: "Engine", docking_bay: "Docking Bay", shield_gen: "Shield Gen", core: "Core",
    signal_jammer: "Signal Jammer", targeting_sensors: "Targeting Sensors",
  };
  function componentNumbers() {
    const counts = {};
    const map = {};
    for (const tile of design.tiles) {
      if (tile.type === "generic") continue;
      counts[tile.type] = (counts[tile.type] || 0) + 1;
      map[key(tile.q, tile.r)] = counts[tile.type];
    }
    return map;
  }
  function componentLabel(tile, numbers = null) {
    const n = tile.type === "shield_gen" || tile.type === "core"
      ? tile.number
      : (numbers || componentNumbers())[key(tile.q, tile.r)];
    return `${COMPONENT_LABEL[tile.type] || tile.type} ${n ?? ""}`.trim();
  }
  const regionByNumber = (number) =>
    design.shield_regions.find((region) => region.number === number) || null;
  const regionColor = (number) => REGION_COLORS[(number - 1) % REGION_COLORS.length];
  /* Lanes per region are configurable (1..max_lane_count); rolls run 2..N+1
     on an (N+1)-sided die where 1 is always a glancing blow. */
  const regionLaneCount = (region) =>
    Math.max(1, Math.min(META.max_lane_count || 12, region.lane_count || META.default_lane_count || 7));
  const regionRolls = (region) =>
    Array.from({ length: regionLaneCount(region) }, (_unused, index) => index + 2);

  function edgeFacings(q, r, footprint) {
    const facings = [];
    for (let i = 0; i < 6; i++) {
      if (!footprint.has(key(q + DIRS[i][0], r + DIRS[i][1]))) facings.push(i);
    }
    return facings;
  }

  /* Endpoints of the hex edge shared with the neighbor in `facing`,
     pushed outward from the hex center by `offset` svg units. */
  function edgeSegment(q, r, facing, offset) {
    const [cx, cy] = xy(q, r);
    const [dq, dr] = DIRS[facing];
    const [nx, ny] = xy(q + dq, r + dr);
    let ux = nx - cx, uy = ny - cy;
    const len = Math.hypot(ux, uy);
    ux /= len; uy /= len;
    const mx = cx + ux * (len / 2 + offset), my = cy + uy * (len / 2 + offset);
    const px = -uy, py = ux; // perpendicular
    const half = SIZE / 2;
    return [[mx + px * half, my + py * half], [mx - px * half, my - py * half]];
  }

  // ── board rendering ──────────────────────────────────────────────────────
  function hexPoints(cx, cy, radius) {
    const points = [];
    for (let i = 0; i < 6; i++) {
      const a = (Math.PI / 180) * (60 * i);
      points.push(`${(cx + radius * Math.cos(a)).toFixed(1)},${(cy + radius * Math.sin(a)).toFixed(1)}`);
    }
    return points.join(" ");
  }

  function gridCells() {
    const cells = [];
    const R = META.grid_radius;
    for (let q = -R; q <= R; q++) {
      for (let r = Math.max(-R, -q - R); r <= Math.min(R, -q + R); r++) {
        cells.push([q, r]);
      }
    }
    return cells;
  }

  function tileBadge(tile, numbers = null) {
    if (tile.type === "shield_gen") return "SG" + tile.number;
    if (tile.type === "core") return "◉" + tile.number;
    const n = (numbers || componentNumbers())[key(tile.q, tile.r)] || "";
    if (tile.type === "cannon") return "C" + n + " " + (STACK_SHORT[tile.stack] || tile.stack);
    if (tile.type === "engine") return "E" + n + " " + (STACK_SHORT[tile.stack] || tile.stack);
    if (tile.type === "docking_bay") return "D" + n + " " + (STACK_SHORT[tile.stack] || tile.stack);
    if (tile.type === "signal_jammer") return "J" + n;
    if (tile.type === "targeting_sensors") return "T" + n;
    return "";
  }

  function renderBoard() {
    const footprint = footprintSet();
    const numbers = componentNumbers();
    const regionHexes = {}; // "q,r" -> region number (for shield mode tinting)
    for (const region of design.shield_regions) {
      for (const [q, r] of region.hexes) regionHexes[key(q, r)] = region.number;
    }
    const active = mode === "shields" ? regionByNumber(currentRegion) : null;
    const activeHexes = new Set(active ? active.hexes.map(([q, r]) => key(q, r)) : []);

    let cellsSvg = "";
    for (const [q, r] of gridCells()) {
      const [x, y] = xy(q, r);
      const tile = tileAt(q, r);
      let fill = "rgba(120,130,160,.06)";
      let stroke = "rgba(120,130,160,.18)";
      let extra = "";
      if (tile) {
        const tint = TILE_FILL[tile.type];
        fill = `rgba(${tint},.42)`;
        stroke = `rgb(${tint})`;
        if (mode === "shields") {
          const owner = regionHexes[key(q, r)];
          if (owner && owner !== currentRegion) {
            fill = `rgba(${tint},.16)`;
            stroke = "rgba(150,160,190,.5)";
          }
          if (activeHexes.has(key(q, r))) {
            extra = `<polygon points="${hexPoints(x, y, SIZE - 3.2)}" fill="none"
              stroke="${regionColor(currentRegion)}" stroke-width="2.2" pointer-events="none"/>`;
          }
        }
      }
      const isGen = active && active.generator &&
        active.generator[0] === q && active.generator[1] === r;
      cellsSvg += `<g class="bd-cell" data-q="${q}" data-r="${r}">
        <polygon points="${hexPoints(x, y, SIZE - 0.9)}" fill="${fill}" stroke="${stroke}" stroke-width="1.1">
          <title>(${q},${r})${tile && tile.type !== "generic" ? " — " + componentLabel(tile, numbers) : ""}</title></polygon>
        ${extra}
        ${tile && tileBadge(tile, numbers) ? `<text x="${x}" y="${y + 3.6}" text-anchor="middle" class="bd-badge"
          fill="${isGen ? "#fff" : "#0a0f1e"}">${esc(tileBadge(tile, numbers))}</text>` : ""}
        ${isGen ? `<polygon points="${hexPoints(x, y, SIZE - 1.8)}" fill="none" stroke="#fff"
          stroke-width="1.6" stroke-dasharray="3 3" pointer-events="none"/>` : ""}
      </g>`;
    }

    // Shield arcs: every region's outer edge, brightest for the active one.
    let arcsSvg = "";
    for (const region of design.shield_regions) {
      const color = regionColor(region.number);
      const isActive = mode === "shields" && region.number === currentRegion;
      for (const [q, r] of region.hexes) {
        if (!footprint.has(key(q, r))) continue;
        for (const facing of edgeFacings(q, r, footprint)) {
          for (let layer = 0; layer < 2; layer++) {
            const [[x1, y1], [x2, y2]] = edgeSegment(q, r, facing, SIZE * (0.36 + layer * 0.22));
            arcsSvg += `<line x1="${x1.toFixed(1)}" y1="${y1.toFixed(1)}" x2="${x2.toFixed(1)}" y2="${y2.toFixed(1)}"
              stroke="${color}" stroke-width="${layer ? 2 : 3.4}" stroke-linecap="round"
              opacity="${(isActive ? 0.9 : 0.4) - layer * 0.18}" pointer-events="none"/>`;
          }
        }
      }
    }

    // Damage lanes: number outside the entry face, arrow in, faint ray through
    // the hull. Only drawn while actually assigning lanes (Shields & Lanes →
    // Damage Lanes); everywhere else they just add clutter.
    let lanesSvg = "";
    const showLanes = mode === "shields" && shieldSub === "lanes";
    for (const region of showLanes ? design.shield_regions : []) {
      const color = regionColor(region.number);
      const isActive = region.number === currentRegion;
      const opacity = isActive ? 1 : 0.25;
      for (const lane of region.lanes) {
        const [cx, cy] = xy(lane.q, lane.r);
        const [odq, odr] = DIRS[lane.facing];
        const [ox, oy] = xy(lane.q + odq, lane.r + odr);
        let ux = ox - cx, uy = oy - cy;
        const len = Math.hypot(ux, uy);
        ux /= len; uy /= len;
        const labelX = cx + ux * SIZE * 1.9, labelY = cy + uy * SIZE * 1.9;
        // Ray through the hull, entering opposite the labeled face.
        let rayQ = lane.q, rayR = lane.r;
        const ray = [[cx, cy]];
        while (footprint.has(key(rayQ - odq, rayR - odr))) {
          rayQ -= odq; rayR -= odr;
          ray.push(xy(rayQ, rayR));
        }
        const points = ray.map(([x, y]) => `${x.toFixed(1)},${y.toFixed(1)}`).join(" ");
        lanesSvg += `<g opacity="${opacity}" pointer-events="none">
          ${ray.length > 1 ? `<polyline points="${points}" fill="none" stroke="${color}"
            stroke-width="1.4" opacity=".35" stroke-linecap="round"/>` : ""}
          <line x1="${(labelX - ux * SIZE * 0.55).toFixed(1)}" y1="${(labelY - uy * SIZE * 0.55).toFixed(1)}"
            x2="${(cx + ux * SIZE * 0.85).toFixed(1)}" y2="${(cy + uy * SIZE * 0.85).toFixed(1)}"
            stroke="#e8e0cc" stroke-width="1.4" marker-end="url(#bdLaneArrow)"/>
          <text x="${labelX.toFixed(1)}" y="${(labelY + 5).toFixed(1)}" text-anchor="middle"
            class="bd-lane-num" fill="${color}">${lane.roll}</text>
        </g>`;
      }
    }

    const R = META.grid_radius;
    const extent = SIZE * 1.5 * R + SIZE * 3.2;
    const extentY = SIZE * SQ * R + SIZE * 3.2;
    const view = boardView || { x: -extent, y: -extentY, w: extent * 2, h: extentY * 2 };
    el("bd-board").innerHTML = `
      <svg viewBox="${view.x} ${view.y} ${view.w} ${view.h}">
        <defs><marker id="bdLaneArrow" markerWidth="7" markerHeight="7" refX="5" refY="2.5" orient="auto">
          <polygon points="0 0, 6 2.5, 0 5" fill="#e8e0cc"/></marker></defs>
        <g class="bd-lanes">${lanesSvg}</g>
        <g class="bd-cells">${cellsSvg}</g>
        <g class="bd-arcs">${arcsSvg}</g>
      </svg>`;
    el("bd-board").querySelectorAll(".bd-cell").forEach((node) => {
      node.addEventListener("click", () =>
        handleCellClick(parseInt(node.dataset.q, 10), parseInt(node.dataset.r, 10)));
      node.addEventListener("contextmenu", (event) => {
        event.preventDefault();
        handleCellRightClick(parseInt(node.dataset.q, 10), parseInt(node.dataset.r, 10));
      });
    });
  }

  // ── board interaction ────────────────────────────────────────────────────
  function handleCellClick(q, r) {
    if (!design) return;
    if (mode === "structure") return structureClick(q, r);
    if (mode === "shields") return shieldsClick(q, r);
  }

  function handleCellRightClick(q, r) {
    if (!design || mode !== "structure") return;
    removeTile(q, r);
  }

  function removeTile(q, r) {
    const before = design.tiles.length;
    design.tiles = design.tiles.filter((t) => !(t.q === q && t.r === r));
    if (design.tiles.length !== before) {
      scrubMissingHexes();
      markDirty();
      renderBoard();
    }
  }

  function structureClick(q, r) {
    if (tool.type === "erase") return removeTile(q, r);
    const tile = { q, r, type: tool.type };
    if (tool.type === "shield_gen" || tool.type === "core") tile.number = tool.number;
    if (tool.type === "cannon" || tool.type === "engine" || tool.type === "docking_bay") tile.stack = tool.stack;
    design.tiles = design.tiles.filter((t) => !(t.q === q && t.r === r));
    design.tiles.push(tile);
    scrubMissingHexes();
    markDirty();
    renderBoard();
  }

  /* Drop region hexes/generators/lanes that point at removed or overwritten tiles. */
  function scrubMissingHexes() {
    const footprint = footprintSet();
    for (const region of design.shield_regions) {
      region.hexes = region.hexes.filter(([q, r]) => footprint.has(key(q, r)));
      const inRegion = new Set(region.hexes.map(([q, r]) => key(q, r)));
      region.lanes = region.lanes.filter((lane) => inRegion.has(key(lane.q, lane.r)));
      if (region.generator) {
        const tile = tileAt(region.generator[0], region.generator[1]);
        if (!tile || tile.type !== "shield_gen") region.generator = null;
      }
    }
  }

  function shieldsClick(q, r) {
    const region = regionByNumber(currentRegion);
    if (!region) { setStatus("Add a ship region first.", false); return; }
    const tile = tileAt(q, r);
    if (!tile) return;
    if (shieldSub === "hexes") {
      const index = region.hexes.findIndex(([hq, hr]) => hq === q && hr === r);
      if (index >= 0) {
        region.hexes.splice(index, 1);
        region.lanes = region.lanes.filter((lane) => !(lane.q === q && lane.r === r));
      } else {
        region.hexes.push([q, r]);
      }
    } else if (shieldSub === "power") {
      if (tile.type !== "shield_gen") {
        setStatus("Pick a Shield Gen tile as this region's power source.", false);
        return;
      }
      if (tile.number !== region.number) {
        setStatus(`That generator is numbered ${tile.number}; Region ${region.number} needs SG${region.number}.`, false);
        return;
      }
      region.generator = [q, r];
    } else {
      laneClick(region, q, r);
    }
    markDirty();
    renderBoard();
    renderShieldPanel();
  }

  /* Click an unassigned region hex: next free roll enters from its first edge
     face. Click again: same roll, next edge face. Past the last face: unassign.
     With "second lane" ticked, clicking a laned hex stacks another lane on it
     (a different roll) instead of cycling the existing one. */
  function laneClick(region, q, r) {
    if (!region.hexes.some(([hq, hr]) => hq === q && hr === r)) {
      setStatus("That hex is not in this ship region — add it in Protected Hexes first.", false);
      return;
    }
    const facings = edgeFacings(q, r, footprintSet());
    if (!facings.length) {
      setStatus("That hex has no ship-edge face; lanes must enter from outside.", false);
      return;
    }
    const hexLanes = region.lanes.filter((lane) => lane.q === q && lane.r === r);
    if (hexLanes.length && !stackLanes) {
      const lane = hexLanes[hexLanes.length - 1];
      const at = facings.indexOf(lane.facing);
      if (at >= 0 && at < facings.length - 1) {
        lane.facing = facings[at + 1];
      } else {
        region.lanes = region.lanes.filter((entry) => entry !== lane);
      }
      return;
    }
    const rolls = regionRolls(region);
    const used = new Set(region.lanes.map((lane) => lane.roll));
    const next = rolls.find((roll) => !used.has(roll));
    if (next === undefined) {
      setStatus(`All ${rolls.length} lanes (2-${rolls[rolls.length - 1]}) are assigned — click an assigned hex to adjust or clear it.`, false);
      return;
    }
    // A stacked lane defaults to an entry face the hex isn't using yet.
    const takenFacings = new Set(hexLanes.map((lane) => lane.facing));
    const facing = facings.find((candidate) => !takenFacings.has(candidate)) ?? facings[0];
    region.lanes.push({ roll: next, q, r, facing });
  }

  /* Walk the hull perimeter and return a Map "q,r,facing" -> position index,
     so lane numbering can follow the ship edge continuously. Flat-top hexes
     have vertices at 60°·k; edge k (vertices k → k+1) borders the neighbor in
     facing (6-k)%6. Taking each hex's edges with a consistent winding, the
     shared (interior) edges cancel and the leftover boundary half-edges chain
     end-corner to start-corner into the perimeter loop. */
  function perimeterEdgeOrder(footprint) {
    const cornerKey = (q, r, k) => {
      const [cx, cy] = xy(q, r);
      const angle = (Math.PI / 180) * (60 * k);
      const x = cx + SIZE * Math.cos(angle);
      const y = cy + SIZE * Math.sin(angle);
      return `${Math.round(x * 100)},${Math.round(y * 100)}`;
    };
    // startCorner -> { end, edgeId }. One outgoing boundary edge per corner
    // except at rare pinch points (two hulls meeting at a single corner),
    // where one is dropped and its lanes fall back to the end of the order.
    const edges = new Map();
    for (const cellKey of footprint) {
      const [q, r] = cellKey.split(",").map(Number);
      for (let k = 0; k < 6; k++) {
        const facing = (6 - k) % 6;
        const [dq, dr] = DIRS[facing];
        if (footprint.has(key(q + dq, r + dr))) continue; // shared edge cancels
        edges.set(cornerKey(q, r, k), { end: cornerKey(q, r, (k + 1) % 6), edgeId: `${q},${r},${facing}` });
      }
    }
    // Start from the topmost-leftmost corner so numbering begins near the bow.
    const starts = [...edges.keys()].sort((a, b) => {
      const [ax, ay] = a.split(",").map(Number);
      const [bx, by] = b.split(",").map(Number);
      return ay - by || ax - bx;
    });
    const order = new Map();
    const visited = new Set();
    let index = 0;
    for (const first of starts) {
      let corner = first;
      let guard = 0;
      while (corner !== undefined && !visited.has(corner) && guard++ <= edges.size) {
        visited.add(corner);
        const edge = edges.get(corner);
        if (!edge) break;
        if (!order.has(edge.edgeId)) order.set(edge.edgeId, index++);
        corner = edge.end;
      }
    }
    return order;
  }

  /* Reassign rolls 2..N to this region's lanes in perimeter order, so numbers
     run continuously as you move along the ship's faces. The numbering seam is
     placed in the largest gap between this region's lanes (not at the hull's
     fixed start corner), so a lane arc that straddles that start corner isn't
     split — the sequence only wraps once, across the biggest empty stretch. */
  function renumberLanes(region) {
    const order = perimeterEdgeOrder(footprintSet());
    const total = order.size || 1;
    const placed = region.lanes
      .map((lane) => ({ lane, idx: order.get(`${lane.q},${lane.r},${lane.facing}`) }))
      .filter((entry) => entry.idx !== undefined)
      .sort((a, b) => a.idx - b.idx);
    const unplaced = region.lanes.filter(
      (lane) => order.get(`${lane.q},${lane.r},${lane.facing}`) === undefined);
    let sequence = placed.map((entry) => entry.lane);
    if (placed.length > 1) {
      let startPos = 0, maxGap = -1;
      for (let i = 0; i < placed.length; i++) {
        const gap = (placed[(i + 1) % placed.length].idx - placed[i].idx + total) % total;
        if (gap > maxGap) { maxGap = gap; startPos = (i + 1) % placed.length; }
      }
      sequence = placed.map((_entry, n) => placed[(startPos + n) % placed.length].lane);
    }
    const rolls = regionRolls(region);
    sequence.concat(unplaced).forEach((lane, index) => {
      lane.roll = rolls[index % rolls.length];
    });
  }

  /* Auto-assign a full set of lanes for a region: spread the region's
     lane_count entries evenly along its stretch of hull perimeter (coverage +
     symmetry), preferring within each slot the entry face whose ray pierces
     the most hull and whose direction differs from the previous pick (a mix
     of straight and angled lanes). Replaces the region's current lanes. */
  function autonumberLanes(region) {
    const footprint = footprintSet();
    const inRegion = new Set(region.hexes.map(([q, r]) => key(q, r)));
    const order = perimeterEdgeOrder(footprint);
    const edges = [];
    for (const [edgeId, idx] of order.entries()) {
      const parts = edgeId.split(",").map(Number);
      const [q, r, facing] = parts;
      if (!inRegion.has(key(q, r))) continue;
      // Ray depth = how much hull a hit entering this face can chew through.
      let rayLen = 1;
      let rq = q, rr = r;
      const [dq, dr] = DIRS[facing];
      while (footprint.has(key(rq - dq, rr - dr))) {
        rq -= dq; rr -= dr; rayLen++;
      }
      edges.push({ q, r, facing, idx, rayLen });
    }
    if (!edges.length) return false;
    edges.sort((a, b) => a.idx - b.idx);
    const count = Math.min(regionLaneCount(region), edges.length);
    const spacing = edges.length / count;
    const chosen = [];
    const used = new Set();
    let lastFacing = null;
    for (let k = 0; k < count; k++) {
      const center = (k + 0.5) * spacing - 0.5;
      const window = Math.max(1, Math.round(spacing / 2));
      let best = null;
      let bestScore = -Infinity;
      for (let off = -window; off <= window; off++) {
        const i = Math.round(center) + off;
        if (i < 0 || i >= edges.length || used.has(i)) continue;
        const edge = edges[i];
        const score = edge.rayLen
          + (edge.facing !== lastFacing ? 0.8 : 0)   // vary the entry angle
          - Math.abs(i - center) * 0.55;             // stay near the even slot
        if (score > bestScore) { bestScore = score; best = i; }
      }
      if (best === null) continue;
      used.add(best);
      lastFacing = edges[best].facing;
      chosen.push(edges[best]);
    }
    region.lanes = chosen.map((edge) => ({ roll: 2, q: edge.q, r: edge.r, facing: edge.facing }));
    renumberLanes(region);
    return true;
  }

  // ── panels ───────────────────────────────────────────────────────────────
  function renderModePanel() {
    el("bd-panel-structure").classList.toggle("hidden", mode !== "structure");
    el("bd-panel-shields").classList.toggle("hidden", mode !== "shields");
    el("bd-panel-progression").classList.toggle("hidden", mode !== "progression");
    el("bd-panel-stacks").classList.toggle("hidden", mode !== "stacks");
    el("bd-panel-behavior").classList.toggle("hidden", mode !== "behavior");
    el("bd-panel-print").classList.toggle("hidden", mode !== "print");
    // The stacks and print views take over the board area; every other mode shows the hex board.
    el("bd-board").classList.toggle("hidden", mode === "stacks" || mode === "print");
    el("bd-stacks").classList.toggle("hidden", mode !== "stacks");
    el("bd-print").classList.toggle("hidden", mode !== "print");
    root().querySelectorAll(".bd-mode").forEach((button) =>
      button.classList.toggle("active", button.dataset.mode === mode));
    if (mode === "shields") renderShieldPanel();
    if (mode === "progression") renderProgressionPanel();
    if (mode === "structure") renderStructurePanel();
    if (mode === "behavior") renderBehaviorPanel();
    if (mode === "stacks") renderStacksView();
    if (mode === "print") renderPrintView();
  }

  function actionStackItems() {
    const numbers = componentNumbers();
    const byStack = {};
    for (const stack of META.action_stacks) byStack[stack] = [];
    for (const tile of design.tiles) {
      if (!tile.stack || !byStack[tile.stack]) continue;
      if (tile.type === "cannon") {
        byStack[tile.stack].push({
          kind: "attack", label: componentLabel(tile, numbers), source: "component",
          q: tile.q, r: tile.r,
        });
      } else if (tile.type === "engine") {
        byStack[tile.stack].push({
          kind: "move", label: componentLabel(tile, numbers), source: "component",
          q: tile.q, r: tile.r,
        });
      } else if (tile.type === "docking_bay") {
        byStack[tile.stack].push({
          kind: "spawn", label: componentLabel(tile, numbers), source: "component",
          q: tile.q, r: tile.r,
        });
      }
    }
    design.progression.steps.forEach((step, index) => {
      if (step.kind === "action_link" && byStack[step.stack]) {
        byStack[step.stack].push({
          kind: step.action === "shoot" ? "attack" : "move",
          label: `Step ${index + 1}: ${step.action}`,
          source: "progression",
        });
      } else if (step.kind === "breacher_link" && byStack.starbreach) {
        const bits = [];
        if (step.core !== undefined) bits.push(`core ${step.core}`);
        if (step.round !== undefined) bits.push(`round >= ${step.round}`);
        byStack.starbreach.push({
          kind: "breacher",
          label: `Step ${index + 1}: Breacher`,
          source: bits.length ? bits.join(", ") : "progression",
        });
      } else if (step.kind === "spawn_fleet") {
        const bay = design.tiles.find((tile) => tile.type === "docking_bay");
        const bayStack = bay?.stack || "starbreach";
        if (byStack[bayStack]) {
          byStack[bayStack].push({
            kind: "spawn",
            label: `Step ${index + 1}: spawn fleet`,
            source: bay ? `linked to ${componentLabel(bay, numbers)}` : "needs Docking Bay",
          });
        }
      }
    });
    const fleet = design.behavior?.fleet || defaultBehavior().fleet;
    if (fleet.count > 0) {
      for (const entry of fleet.actions || []) {
        if (byStack[entry.stack]) {
          const count = Math.max(1, parseInt(entry.count, 10) || 1);
          const symbol = entry.action === "shoot" ? ACTION_SYMBOL.shoot : ACTION_SYMBOL.move;
          byStack[entry.stack].push({
            kind: "fleet", action: entry.action,
            label: `Fleet ${Array.from({ length: count }, () => symbol).join(" ")}`, source: "behavior",
          });
        }
      }
    }
    (design.supers || []).forEach((sup, index) => {
      const stack = sup.stack || "starbreach";
      if (!byStack[stack]) return;
      byStack[stack].push({
        kind: "super",
        label: `Super: ${superShortName(sup.effect)}`,
        source: superRequirementText(sup),
      });
    });
    return byStack;
  }

  const superShortName = (effect) => (SUPER_LABELS[effect] || effect).split(" — ")[0];
  const superRequirementText = (sup) =>
    `core ${sup.core || 1}, ${sup.trigger?.kind === "progress" ? "step" : "round"} ≥ ${sup.trigger?.value ?? 1}`;

  // ── action stacks view (drag components/steps between boss stacks) ───────
  let dragPayload = null; // {type: "tile"|"step"|"chip", ...}

  function stepLabel(step) {
    if (step.kind === "action_link") return `Action link — ${step.action} @ ${step.stack}`;
    if (step.kind === "breacher_link") {
      const bits = [];
      if (step.core !== undefined) bits.push(`core ${step.core}`);
      if (step.round !== undefined) bits.push(`round ≥ ${step.round}`);
      return `Breacher link${bits.length ? " (" + bits.join(", ") + ")" : ""}`;
    }
    if (step.kind === "ability_trigger") return `⚡ ${step.name || "Ability"}`;
    if (step.kind === "ability_link") return `⚡ ${ABILITY_LABELS[step.ability] || step.ability}`;
    if (step.kind === "spawn_fleet") {
      const where = { boss_front: "front of boss", vault: "current vault", fang: "The Fang" }[step.location] || step.location;
      return `▣ Spawn ${step.count || 1} fleet craft — ${where}`;
    }
    return "Filler";
  }

  /* Letter/number drawn inside a printed progression square; empty = filler.
     C/E = boss gains a cannon/engine action, B = breacher strike, F = fleet
     spawn, ⚡ = ability trigger. */
  function progressionBoxBadge(step) {
    if (step.kind === "action_link") {
      return {
        main: step.action === "shoot" ? "C" : "E",
        sub: STACK_SHORT[step.stack] || step.stack || "",
      };
    }
    if (step.kind === "breacher_link") {
      return { main: "B", sub: step.core !== undefined ? "core " + step.core : "" };
    }
    if (step.kind === "spawn_fleet") return { main: "F", sub: "×" + (step.count || 1) };
    if (step.kind === "ability_trigger") return { main: "⚡", sub: (step.name || "").slice(0, 7) };
    if (step.kind === "ability_link") {
      return {
        main: ABILITY_SHORT[step.ability] || "⚡",
        sub: step.ability === "signal_jammer" ? "+2 def" : step.ability === "targeting_sensors" ? "+2 aim" : "",
      };
    }
    return { main: "", sub: "" };
  }

  function abilityStepText(step) {
    return step.name || "see design notes";
  }

  function moveStep(fromIndex, toIndex) {
    const steps = design.progression.steps;
    if (fromIndex === toIndex || fromIndex < 0 || fromIndex >= steps.length) return;
    const [step] = steps.splice(fromIndex, 1);
    if (!step || typeof step !== "object") return;
    steps.splice(toIndex > fromIndex ? toIndex - 1 : toIndex, 0, step);
    markDirty();
  }

  /* Light up the stack cards fed by progression step `index`. */
  function highlightStepItems(index, on) {
    el("bd-stacks").querySelectorAll(`.bd-stack-item[data-step="${index}"]`)
      .forEach((node) => node.classList.toggle("bd-stack-hot", !!on));
  }

  /* Light up every mini-ship cell whose component has a slot in `stack`. */
  function highlightStackHexes(stack, on) {
    for (const tile of design.tiles) {
      if (tile.stack === stack && (tile.type === "cannon" || tile.type === "engine" || tile.type === "docking_bay")) {
        highlightMiniHex(tile.q, tile.r, on);
      }
    }
  }

  /* The progression track as two balanced columns; the wrap arrow shows the
     track reading order (bottom of column 1 continues at the top of column 2). */
  function buildProgressionTrack() {
    const wrap = document.createElement("div");
    wrap.className = "bd-prog-track";
    const label = document.createElement("div");
    label.className = "bd-strip-label";
    label.textContent = "Progression track:";
    wrap.appendChild(label);
    const steps = design.progression.steps;
    if (!steps.length) {
      const empty = document.createElement("span");
      empty.className = "admin-note";
      empty.textContent = "no steps yet (add them in Progression)";
      wrap.appendChild(empty);
      return wrap;
    }
    const makeChip = (step, index) => {
      const chip = document.createElement("div");
      chip.className = "bd-prog-chip bd-kind-" + step.kind;
      chip.draggable = true;
      chip.innerHTML = `<b>${index + 1}</b> ${esc(stepLabel(step))}`;
      chip.addEventListener("dragstart", () => { dragPayload = { type: "chip", index }; });
      chip.addEventListener("dragover", (event) => {
        if (dragPayload && dragPayload.type === "chip") event.preventDefault();
      });
      chip.addEventListener("drop", (event) => {
        event.preventDefault();
        if (!dragPayload || dragPayload.type !== "chip") return;
        moveStep(dragPayload.index, index);
        dragPayload = null;
        renderStacksView();
      });
      // Hovering a step lights up the stack cards it feeds.
      chip.addEventListener("mouseenter", () => highlightStepItems(index, true));
      chip.addEventListener("mouseleave", () => highlightStepItems(index, false));
      return chip;
    };
    const grid = document.createElement("div");
    grid.className = "bd-prog-cols";
    const colA = document.createElement("div");
    colA.className = "bd-prog-col";
    const colB = document.createElement("div");
    colB.className = "bd-prog-col";
    const half = Math.ceil(steps.length / 2);
    steps.forEach((step, index) => (index < half ? colA : colB).appendChild(makeChip(step, index)));
    const arrow = document.createElement("div");
    arrow.className = "bd-prog-wrap-arrow";
    arrow.innerHTML = `<svg viewBox="0 0 40 100" preserveAspectRatio="none" aria-hidden="true">
      <defs><marker id="bdProgArrow" markerWidth="8" markerHeight="8" refX="5" refY="3" orient="auto">
        <path d="M0,0 L6,3 L0,6 Z" fill="currentColor"/></marker></defs>
      <path d="M4 88 C 30 88, 10 12, 32 10" fill="none" stroke="currentColor" stroke-width="2.4"
        stroke-linecap="round" stroke-dasharray="5 4" marker-end="url(#bdProgArrow)"/>
    </svg>`;
    grid.appendChild(colA);
    grid.appendChild(arrow);
    grid.appendChild(colB);
    wrap.appendChild(grid);
    return wrap;
  }

  function renderStacksView() {
    const container = el("bd-stacks");
    container.innerHTML = "";
    container.appendChild(buildProgressionTrack());

    const cols = document.createElement("div");
    cols.className = "bd-stack-cols";
    for (const stack of META.action_stacks) {
      const col = document.createElement("div");
      col.className = "bd-stack-col";
      col.innerHTML = `<div class="bd-stack-head">${stack === "starbreach" ? "StarBreach" : "Action " + stack}</div>`;
      // Hovering a stack header lights up its components in the ship view.
      const head = col.querySelector(".bd-stack-head");
      head.addEventListener("mouseenter", () => highlightStackHexes(stack, true));
      head.addEventListener("mouseleave", () => highlightStackHexes(stack, false));
      col.addEventListener("dragover", (event) => {
        if (!dragPayload || dragPayload.type === "chip") return;
        event.preventDefault();
        col.classList.add("drop-hover");
      });
      col.addEventListener("dragleave", () => col.classList.remove("drop-hover"));
      col.addEventListener("drop", (event) => {
        event.preventDefault();
        col.classList.remove("drop-hover");
        if (!dragPayload) return;
        if (dragPayload.type === "tile") {
          const tile = tileAt(dragPayload.q, dragPayload.r);
          if (tile) tile.stack = stack;
        } else if (dragPayload.type === "step") {
          const step = design.progression.steps[dragPayload.index];
          if (step && step.kind === "action_link") step.stack = stack;
        }
        dragPayload = null;
        markDirty();
        renderStacksView();
        renderBoard();
      });

      const addItem = (label, sub, payload, extraClass, hoverHex, stepIndex) => {
        const item = document.createElement("div");
        item.className = "bd-stack-item" + (extraClass ? " " + extraClass : "");
        if (stepIndex !== undefined) item.dataset.step = stepIndex;
        item.innerHTML = `<div class="bd-stack-line">${label}</div>${sub ? `<div class="bd-item-sub">${sub}</div>` : ""}`;
        if (payload) {
          item.draggable = true;
          item.addEventListener("dragstart", () => { dragPayload = payload; });
          item.addEventListener("dragend", () => { dragPayload = null; });
        }
        if (hoverHex) {
          // Mousing over a card lights up its component in the mini ship view.
          item.addEventListener("mouseenter", () => highlightMiniHex(hoverHex[0], hoverHex[1], true));
          item.addEventListener("mouseleave", () => highlightMiniHex(hoverHex[0], hoverHex[1], false));
        }
        col.appendChild(item);
      };

      const numbers = componentNumbers();
      for (const tile of design.tiles) {
        if (tile.stack !== stack) continue;
        if (tile.type === "cannon") {
          addItem(`${esc(componentLabel(tile, numbers))} <span class="bd-stack-symbol">${ACTION_SYMBOL.attack}</span>`, "", { type: "tile", q: tile.q, r: tile.r }, "bd-item-attack", [tile.q, tile.r]);
        } else if (tile.type === "engine") {
          addItem(`${esc(componentLabel(tile, numbers))} <span class="bd-stack-symbol">${ACTION_SYMBOL.move}</span>`, "", { type: "tile", q: tile.q, r: tile.r }, "bd-item-move", [tile.q, tile.r]);
        } else if (tile.type === "docking_bay") {
          addItem(`${esc(componentLabel(tile, numbers))} <span class="bd-stack-symbol">${ACTION_SYMBOL.spawn}</span>`, "", { type: "tile", q: tile.q, r: tile.r }, "bd-item-spawn", [tile.q, tile.r]);
        }
      }
      design.progression.steps.forEach((step, index) => {
        if (step.kind === "action_link" && step.stack === stack) {
          addItem(
            `Track ${index + 1} <span class="bd-stack-symbol">${ACTION_SYMBOL[step.action]}</span>`,
            "",
            { type: "step", index },
            step.action === "shoot" ? "bd-item-attack" : "bd-item-move",
            null,
            index
          );
        } else if (step.kind === "breacher_link" && stack === "starbreach") {
          const bits = [];
          if (step.core !== undefined) bits.push(`core ${step.core}`);
          if (step.round !== undefined) bits.push(`round ≥ ${step.round}`);
          addItem(
            `Track ${index + 1} <span class="bd-stack-symbol">${ACTION_SYMBOL.breacher}</span>`,
            "",
            null,
            "bd-item-breacher",
            null,
            index
          );
        } else if (step.kind === "spawn_fleet") {
          const bay = design.tiles.find((tile) => tile.type === "docking_bay");
          const bayStack = bay?.stack || "starbreach";
          if (stack === bayStack) {
            addItem(
              `Track ${index + 1} <span class="bd-stack-symbol">${ACTION_SYMBOL.spawn}</span>`,
              bay ? `linked to ${esc(componentLabel(bay, numbers))}` : "needs Docking Bay",
              null,
              "bd-item-spawn",
              bay ? [bay.q, bay.r] : null,
              index
            );
          }
        }
      });
      (design.supers || []).forEach((sup) => {
        if ((sup.stack || "starbreach") !== stack) return;
        addItem(
          `${esc(superShortName(sup.effect))} <span class="bd-stack-symbol">${ACTION_SYMBOL.super}</span>`,
          esc(superRequirementText(sup)),
          null,
          "bd-item-super"
        );
      });
      const fleetKinds = (design.behavior.fleet.actions || [])
        .filter((entry) => entry.stack === stack)
        .flatMap((entry) => Array.from(
          { length: Math.max(1, parseInt(entry.count, 10) || 1) },
          () => entry.action === "shoot" ? ACTION_SYMBOL.shoot : ACTION_SYMBOL.move
        ));
      if (design.behavior.fleet.count > 0 && fleetKinds.length) {
        addItem(`Fleet <span class="bd-stack-symbols">${fleetKinds.join(" ")}</span>`, "", null, "bd-item-fleet");
      }
      cols.appendChild(col);
    }
    container.appendChild(cols);

    // Mini ship view: rendered in the right-hand panel so it stays alongside
    // the stacks. Hover a card or a stack header to light up components here.
    const mini = el("bd-stacks-mini");
    if (mini) {
      mini.innerHTML = `<div class="bd-mini-ship-label">Ship view — hover a card or stack header to locate its components</div>${miniShipSVG()}`;
    }
  }

  function miniShipSVG() {
    if (!design.tiles.length) return '<span class="admin-note">no hull tiles yet</span>';
    const size = 9;
    const mxy = (q, r) => [size * 1.5 * q, size * SQ * (r + q / 2)];
    const numbers = componentNumbers();
    let body = "";
    for (const tile of design.tiles) {
      const [x, y] = mxy(tile.q, tile.r);
      const tint = TILE_FILL[tile.type];
      const badge = tile.type === "cannon" ? "C" + numbers[key(tile.q, tile.r)]
        : tile.type === "engine" ? "E" + numbers[key(tile.q, tile.r)]
        : tile.type === "docking_bay" ? "D" + numbers[key(tile.q, tile.r)]
        : tile.type === "shield_gen" ? "S" + tile.number
        : tile.type === "core" ? "◉"
        : tile.type === "signal_jammer" ? "J" + numbers[key(tile.q, tile.r)]
        : tile.type === "targeting_sensors" ? "T" + numbers[key(tile.q, tile.r)] : "";
      body += `<g><polygon data-hex="${tile.q},${tile.r}" points="${hexPoints(x, y, size - 0.5)}"
        fill="rgba(${tint},.42)" stroke="rgb(${tint})" stroke-width="1">
        <title>${esc(tile.type === "generic" ? "hull" : componentLabel(tile, numbers))} (${tile.q},${tile.r})</title></polygon>
        ${badge ? `<text x="${x}" y="${y + 2.6}" text-anchor="middle" font-size="6.4" font-weight="700"
          fill="#0a0f1e" pointer-events="none">${esc(badge)}</text>` : ""}</g>`;
    }
    const xs = design.tiles.map((t) => size * 1.5 * t.q);
    const ys = design.tiles.map((t) => size * SQ * (t.r + t.q / 2));
    const pad = size * 1.6;
    const minX = Math.min(...xs) - pad, maxX = Math.max(...xs) + pad;
    const minY = Math.min(...ys) - pad, maxY = Math.max(...ys) + pad;
    return `<svg class="bd-mini-svg" viewBox="${minX} ${minY} ${maxX - minX} ${maxY - minY}">${body}</svg>`;
  }

  function highlightMiniHex(q, r, on) {
    const node = el("bd-stacks-mini")?.querySelector(`[data-hex="${q},${r}"]`);
    if (node) node.classList.toggle("bd-mini-hot", !!on);
  }

  function printPalette() {
    if (printTone === "bw") {
      return {
        page: "#ffffff", text: "#111111", dim: "#555555", line: "#111111",
        hull: "#f4f4f4", generic: "#ffffff", attack: "#eeeeee", move: "#dddddd",
        shieldGen: "#e8e8e8", core: "#cfcfcf", lane: "#111111", fleet: "#f0f0f0",
        progression: "#ffffff", breacher: "#e6e6e6", spawn: "#d6d6d6", jammer: "#f8f8f8", sensors: "#e2e2e2",
      };
    }
    return {
      page: "#fffaf0", text: "#151923", dim: "#5f6675", line: "#283246",
      hull: "#f2ead8", generic: "#f8f3e7", attack: "#ffd2c7", move: "#ffe2a8",
      shieldGen: "#c7eaff", core: "#e8c8ff", lane: "#c54530", fleet: "#d6f3ff",
      progression: "#ddd2ff", breacher: "#f3c4f0", spawn: "#ffd3ec", jammer: "#c9f5e4", sensors: "#ffd3ec",
    };
  }

  /* What kind of ability a stack card is: component-granted, progression-track,
     fleet, or breacher. Drives the printed card's icon and colour stripe. */
  function stackItemType(item) {
    if (item.kind === "fleet") return "fleet";
    if (item.kind === "breacher") return "breacher";
    if (item.kind === "super") return "super";
    return item.source === "progression" ? "progression" : "component";
  }

  function printTileFill(tile, colors) {
    if (tile.type === "cannon") return colors.attack;
    if (tile.type === "engine") return colors.move;
    if (tile.type === "docking_bay") return colors.spawn || "#ff7ad0";
    if (tile.type === "shield_gen") return colors.shieldGen;
    if (tile.type === "core") return colors.core;
    if (tile.type === "signal_jammer") return colors.jammer;
    if (tile.type === "targeting_sensors") return colors.sensors;
    return colors.generic;
  }

  function printSheetSVG() {
    if (!design) return "";
    const colors = printPalette();
    const numbers = componentNumbers();
    const stacks = actionStackItems();
    const pageW = 1400;
    let pageH = 1900;
    // Full-page-width ship box; the progression track and everything else
    // flow horizontally beneath it.
    const breachBox = { x: 55, y: 175, w: pageW - 110, h: 640 };
    const baseShipSize = 34;
    const baseXy = (q, r) => [baseShipSize * 1.5 * q, baseShipSize * SQ * (r + q / 2)];
    const basePoints = design.tiles.length ? design.tiles.map((tile) => baseXy(tile.q, tile.r)) : [[0, 0]];
    const baseMinX = Math.min(...basePoints.map(([x]) => x)) - baseShipSize;
    const baseMaxX = Math.max(...basePoints.map(([x]) => x)) + baseShipSize;
    const baseMinY = Math.min(...basePoints.map(([, y]) => y)) - baseShipSize;
    const baseMaxY = Math.max(...basePoints.map(([, y]) => y)) + baseShipSize;
    const shipScale = Math.min(
      1,
      (breachBox.w - 54) / Math.max(1, baseMaxX - baseMinX),
      (breachBox.h - 54) / Math.max(1, baseMaxY - baseMinY),
    ) * printZoom;
    const shipSize = baseShipSize * shipScale;
    const rawXy = (q, r) => [shipSize * 1.5 * q, shipSize * SQ * (r + q / 2)];
    const rawPoints = design.tiles.length ? design.tiles.map((tile) => rawXy(tile.q, tile.r)) : [[0, 0]];
    const minRawX = Math.min(...rawPoints.map(([x]) => x)) - shipSize;
    const maxRawX = Math.max(...rawPoints.map(([x]) => x)) + shipSize;
    const minRawY = Math.min(...rawPoints.map(([, y]) => y)) - shipSize;
    const maxRawY = Math.max(...rawPoints.map(([, y]) => y)) + shipSize;
    const shipX = breachBox.x + breachBox.w / 2 - (minRawX + maxRawX) / 2;
    const shipY = breachBox.y + breachBox.h / 2 - (minRawY + maxRawY) / 2;
    const pxy = (q, r) => {
      const [x, y] = rawXy(q, r);
      return [shipX + x, shipY + y];
    };
    const tileMap = new Map(design.tiles.map((tile) => [key(tile.q, tile.r), tile]));
    const componentBadge = (tile) => {
      if (tile.type === "cannon") return "C" + numbers[key(tile.q, tile.r)];
      if (tile.type === "engine") return "E" + numbers[key(tile.q, tile.r)];
      if (tile.type === "docking_bay") return "D" + numbers[key(tile.q, tile.r)];
      if (tile.type === "shield_gen") return "SG" + tile.number;
      if (tile.type === "core") return "◎" + tile.number;
      if (tile.type === "signal_jammer") return "J" + numbers[key(tile.q, tile.r)];
      if (tile.type === "targeting_sensors") return "T" + numbers[key(tile.q, tile.r)];
      return "";
    };

    let ship = "";
    for (const tile of design.tiles) {
      const [x, y] = pxy(tile.q, tile.r);
      const badge = componentBadge(tile);
      const title = tile.type === "generic" ? "Hull" : componentLabel(tile, numbers);
      ship += `<g>
        <polygon points="${hexPoints(x, y, shipSize - 1.2)}" fill="${printTileFill(tile, colors)}" stroke="${colors.line}" stroke-width="2"/>
        ${badge ? `<text x="${x}" y="${y + 6}" text-anchor="middle" class="ps-badge">${esc(badge)}</text>` : ""}
        ${printOptions.coords ? `<text x="${x}" y="${y + shipSize - 5}" text-anchor="middle" class="ps-coord">${tile.q},${tile.r}</text>` : ""}
        <title>${esc(title)} (${tile.q},${tile.r})</title>
      </g>`;
    }

    if (printOptions.lanes && design.tiles.length) {
      // Numbered bubbles sit at their natural radial spot just off each entry
      // face. Only bubbles that would overlap a neighbour move: they back off
      // ~0.75 hex along their own lane and then separate, so every other bubble
      // stays exactly where it was. The shaft runs to the BACK of the arrowhead
      // (an explicit triangle straddling the face), which always points straight
      // into its own entry face.
      const bubbleR = 12.5;
      const normalDist = shipSize * 1.72;   // natural bubble distance from the hex centre
      const backOff = shipSize * SQ * 0.75; // ~0.75 hex, for bubbles that must move
      const headHalf = shipSize * 0.16;     // arrowhead half-width
      const entries = [];
      for (const region of design.shield_regions) {
        for (const lane of region.lanes) {
          const [lx, ly] = pxy(lane.q, lane.r);
          const [dq, dr] = DIRS[lane.facing];
          const [ox, oy] = pxy(lane.q + dq, lane.r + dr);
          let ux = ox - lx, uy = oy - ly;
          const len = Math.hypot(ux, uy) || 1;
          ux /= len; uy /= len;
          entries.push({
            roll: lane.roll, ux, uy,
            tipX: lx + ux * shipSize * 0.72, tipY: ly + uy * shipSize * 0.72,  // arrowhead tip, just inside the face
            hX: lx + ux * shipSize * 1.08, hY: ly + uy * shipSize * 1.08,       // back of the arrowhead, just outside
            bx: lx + ux * normalDist, by: ly + uy * normalDist,                  // number bubble at its natural spot
            displaced: false,
          });
        }
      }
      // Only bubbles that collide move: back each off along its lane, then push
      // the collided ones apart. Untouched bubbles keep their natural position.
      const minDist = bubbleR * 2.15;
      for (let iter = 0; iter < 120; iter++) {
        let moved = false;
        for (let i = 0; i < entries.length; i++) {
          for (let j = i + 1; j < entries.length; j++) {
            const a = entries[i], b = entries[j];
            let dx = b.bx - a.bx, dy = b.by - a.by;
            let dist = Math.hypot(dx, dy);
            if (dist >= minDist) continue;
            if (!a.displaced) { a.bx += a.ux * backOff; a.by += a.uy * backOff; a.displaced = true; moved = true; }
            if (!b.displaced) { b.bx += b.ux * backOff; b.by += b.uy * backOff; b.displaced = true; moved = true; }
            dx = b.bx - a.bx; dy = b.by - a.by; dist = Math.hypot(dx, dy);
            if (dist < minDist) {
              if (dist < 0.01) { dx = 1; dy = 0; dist = 1; }
              const push = (minDist - dist) / 2 + 0.3;
              dx /= dist; dy /= dist;
              a.bx -= dx * push; a.by -= dy * push;
              b.bx += dx * push; b.by += dy * push;
              moved = true;
            }
          }
        }
        if (!moved) break;
      }
      // Uncross the leaders: if two shafts cross, swap those two bubbles'
      // positions. Each swap strictly shortens total leader length, so this
      // settles. Leaders may sit at an angle, but none cross each other.
      const ccw = (ax, ay, bx, by, cx, cy) => (cy - ay) * (bx - ax) - (by - ay) * (cx - ax);
      const shaftsCross = (a, b) => {
        const d1 = ccw(a.bx, a.by, a.hX, a.hY, b.bx, b.by);
        const d2 = ccw(a.bx, a.by, a.hX, a.hY, b.hX, b.hY);
        const d3 = ccw(b.bx, b.by, b.hX, b.hY, a.bx, a.by);
        const d4 = ccw(b.bx, b.by, b.hX, b.hY, a.hX, a.hY);
        return (d1 > 0) !== (d2 > 0) && (d3 > 0) !== (d4 > 0);
      };
      for (let pass = 0; pass < 80; pass++) {
        let swapped = false;
        for (let i = 0; i < entries.length; i++) {
          for (let j = i + 1; j < entries.length; j++) {
            if (shaftsCross(entries[i], entries[j])) {
              const a = entries[i], b = entries[j];
              const bx = a.bx, by = a.by;
              a.bx = b.bx; a.by = b.by; b.bx = bx; b.by = by;
              swapped = true;
            }
          }
        }
        if (!swapped) break;
      }
      for (const e of entries) {
        // Shaft: bubble edge → back of the arrowhead (a straight leader).
        let sx = e.hX - e.bx, sy = e.hY - e.by;
        const slen = Math.hypot(sx, sy) || 1;
        const startX = e.bx + (sx / slen) * bubbleR, startY = e.by + (sy / slen) * bubbleR;
        const perpX = -e.uy, perpY = e.ux;
        const tri = `${e.tipX.toFixed(1)},${e.tipY.toFixed(1)} `
          + `${(e.hX + perpX * headHalf).toFixed(1)},${(e.hY + perpY * headHalf).toFixed(1)} `
          + `${(e.hX - perpX * headHalf).toFixed(1)},${(e.hY - perpY * headHalf).toFixed(1)}`;
        ship += `<g class="ps-lane">
          <line x1="${startX.toFixed(1)}" y1="${startY.toFixed(1)}" x2="${e.hX.toFixed(1)}" y2="${e.hY.toFixed(1)}" stroke="${colors.lane}" stroke-width="2.6"/>
          <polygon points="${tri}" fill="${colors.lane}"/>
          <circle cx="${e.bx.toFixed(1)}" cy="${e.by.toFixed(1)}" r="${bubbleR}" fill="${colors.page}" stroke="${colors.lane}" stroke-width="2"/>
          <text x="${e.bx.toFixed(1)}" y="${(e.by + 5).toFixed(1)}" text-anchor="middle" class="ps-lane-num">${e.roll}</text>
        </g>`;
      }
    }

    // Action iconography for the printed stack cards. Drawn as SVG shapes (no
    // small text on shaded fills) so they read the same in colour and B&W:
    //   arrow = move, star = shoot; filled = ship component, outline =
    //   progression track; a trio of glyphs = the fleet; diamond = breacher.
    const GLYPH_INK = colors.line;
    const itemAction = (item) =>
      item.kind === "move" ? "move"
      : item.kind === "attack" || item.kind === "breacher" ? "shoot"
      : item.kind === "fleet" ? (item.action === "shoot" ? "shoot" : "move")
      : "move";
    function glyphMove(cx, cy, s, filled) {
      const d = `M ${(cx - s * 0.5).toFixed(1)} ${(cy - s * 0.66).toFixed(1)} `
        + `L ${(cx + s * 0.66).toFixed(1)} ${cy.toFixed(1)} `
        + `L ${(cx - s * 0.5).toFixed(1)} ${(cy + s * 0.66).toFixed(1)} Z`;
      return `<path d="${d}" fill="${filled ? GLYPH_INK : "none"}" stroke="${GLYPH_INK}" stroke-width="1.6" stroke-linejoin="round"/>`;
    }
    function glyphShoot(cx, cy, s, filled) {
      const R = s * 0.9, ir = s * 0.36;
      const pts = [[cx + R, cy], [cx + ir, cy - ir], [cx, cy - R], [cx - ir, cy - ir],
        [cx - R, cy], [cx - ir, cy + ir], [cx, cy + R], [cx + ir, cy + ir]];
      return `<path d="M ${pts.map((p) => p[0].toFixed(1) + " " + p[1].toFixed(1)).join(" L ")} Z" `
        + `fill="${filled ? GLYPH_INK : "none"}" stroke="${GLYPH_INK}" stroke-width="1.5" stroke-linejoin="round"/>`;
    }
    function glyphBreacher(cx, cy, s) {
      const d = `M ${cx} ${(cy - s * 0.95).toFixed(1)} L ${(cx + s * 0.95).toFixed(1)} ${cy} `
        + `L ${cx} ${(cy + s * 0.95).toFixed(1)} L ${(cx - s * 0.95).toFixed(1)} ${cy} Z`;
      return `<path d="${d}" fill="${GLYPH_INK}"/><circle cx="${cx}" cy="${cy}" r="${(s * 0.3).toFixed(1)}" fill="${colors.page}"/>`;
    }
    function actionIcon(item, cx, cy) {
      const source = stackItemType(item);
      if (source === "breacher") return glyphBreacher(cx, cy, 9);
      if (source === "super") {
        // Filled starburst with a hollow eye: the boss Super mark.
        return glyphShoot(cx, cy, 9, true) + `<circle cx="${cx}" cy="${cy}" r="2.6" fill="${colors.page}"/>`;
      }
      const shoot = itemAction(item) === "shoot";
      if (source === "fleet") {
        const one = (gx) => shoot ? glyphShoot(gx, cy, 5.4, true) : glyphMove(gx, cy, 5.4, true);
        return one(cx - 7.5) + one(cx) + one(cx + 7.5);
      }
      const filled = source === "component";
      return shoot ? glyphShoot(cx, cy, 9, filled) : glyphMove(cx, cy, 9, filled);
    }
    const cardStripe = (item) => {
      if (printTone === "bw") return colors.line;
      const source = stackItemType(item);
      if (source === "progression") return colors.progression;
      if (source === "fleet") return colors.fleet;
      if (source === "breacher") return colors.breacher;
      if (source === "super") return colors.core;
      return itemAction(item) === "shoot" ? colors.attack : colors.move;
    };

    // Everything under the ship flows top-to-bottom: progression track first,
    // then action stacks, optional lists, and the fleet/table aid at the very
    // bottom of the page.
    let cursorY = breachBox.y + breachBox.h + 56;
    let side = "";

    if (printOptions.progression) {
      // The physical progress track: one square per step, marked left to
      // right as the boss advances. Filler squares stay empty; linked squares
      // carry the letter/number of the element they power.
      side += `<text x="70" y="${cursorY}" class="ps-section">Progression Track</text>`;
      cursorY += 24;
      const triggers = design.progression.triggers || [];
      const trigText = triggers.length
        ? "Advance the marker one square each time: " + triggers.map((trigger) => TRIGGER_LABELS[trigger] || trigger).join(", ")
        : "No progress triggers set.";
      side += `<text x="70" y="${cursorY}" class="ps-small">${esc(trigText)}</text>`;
      cursorY += 18;
      const steps = design.progression.steps;
      if (!steps.length) {
        side += `<text x="70" y="${cursorY + 18}" class="ps-small">No progression steps.</text>`;
        cursorY += 40;
      }
      const box = 46, boxGap = 10, boxRowH = box + 32;
      const perRow = Math.max(1, Math.floor((pageW - 140 + boxGap) / (box + boxGap)));
      steps.forEach((step, index) => {
        const bx = 70 + (index % perRow) * (box + boxGap);
        const by = cursorY + Math.floor(index / perRow) * boxRowH;
        const badge = progressionBoxBadge(step);
        side += `<g>
          <rect x="${bx}" y="${by}" width="${box}" height="${box}" fill="${colors.page}" stroke="${colors.line}" stroke-width="2"/>
          ${badge.main ? `<text x="${bx + box / 2}" y="${by + (badge.sub ? 22 : 29)}" text-anchor="middle" class="ps-badge">${esc(badge.main)}</text>` : ""}
          ${badge.sub ? `<text x="${bx + box / 2}" y="${by + 38}" text-anchor="middle" class="ps-coord">${esc(badge.sub)}</text>` : ""}
          <text x="${bx + box / 2}" y="${by + box + 16}" text-anchor="middle" class="ps-tier">${index + 1}</text>
          <title>${esc(stepLabel(step))}</title>
        </g>`;
      });
      if (steps.length) cursorY += Math.ceil(steps.length / perRow) * boxRowH + 26;
    }

    const stackX = 70;
    const stackY = cursorY;
    const colW = 244;
    const colGap = 10;
    const rowH = 34;
    const maxStackItems = Math.max(0, ...META.action_stacks.map((stack) => (stacks[stack] || []).length));
    const stackHeight = Math.max(320, 54 + maxStackItems * rowH + 18);
    let stackSvg = "";
    if (printOptions.stacks) {
      META.action_stacks.forEach((stack, stackIndex) => {
        const x = stackX + stackIndex * (colW + colGap);
        const items = stacks[stack] || [];
        stackSvg += `<g>
          <rect x="${x}" y="${stackY}" width="${colW}" height="${stackHeight}" rx="8" fill="${colors.generic}" stroke="${colors.line}" stroke-width="2"/>
          <text x="${x + colW / 2}" y="${stackY + 27}" text-anchor="middle" class="ps-stack-title">${stack === "starbreach" ? "StarBreach" : "Action " + stack}</text>`;
        if (!items.length) {
          stackSvg += `<text x="${x + colW / 2}" y="${stackY + 70}" text-anchor="middle" class="ps-small">empty</text>`;
        }
        items.forEach((item, itemIndex) => {
          const y = stackY + 48 + itemIndex * rowH;
          const cardH = rowH - 7;
          let sub = "";
          if (item.q !== undefined) sub = printOptions.coords ? `hex ${item.q},${item.r}` : "";
          else if (item.kind === "breacher" && item.source && item.source !== "progression") sub = item.source;
          // White card so the label stays crisp; the type reads from the icon
          // and the coloured left stripe instead of a shaded background.
          stackSvg += `<rect x="${x + 8}" y="${y}" width="${colW - 16}" height="${cardH}" rx="6"
              fill="${colors.page}" stroke="${colors.line}" stroke-width="1.5"/>
            <rect x="${x + 8}" y="${y}" width="7" height="${cardH}" rx="3" fill="${cardStripe(item)}"/>
            ${actionIcon(item, x + 32, y + cardH / 2)}
            <text x="${x + 48}" y="${y + (sub ? 14 : cardH / 2 + 4)}" class="ps-card">${esc(item.label)}</text>
            ${sub ? `<text x="${x + 48}" y="${y + 28}" class="ps-small">${esc(sub)}</text>` : ""}`;
          if (item.q !== undefined && printOptions.stackLinks) {
            const tile = tileMap.get(key(item.q, item.r));
            const [tx, ty] = pxy(item.q, item.r);
            stackSvg += `<line x1="${x + colW / 2}" y1="${y}" x2="${tx}" y2="${ty}"
              stroke="${colors.line}" stroke-width="1.4" stroke-dasharray="5 5" opacity=".55"/>
              <circle cx="${tx}" cy="${ty}" r="${shipSize - 8}" fill="none" stroke="${colors.line}" stroke-width="4" opacity=".5">
                <title>${esc(tile ? componentLabel(tile, numbers) : "component")}</title>
              </circle>`;
          }
        });
        stackSvg += "</g>";
      });
      const legY = stackY + stackHeight + 22;
      stackSvg += `<g class="ps-legend">
        ${glyphMove(stackX + 9, legY, 8, true)}<text x="${stackX + 22}" y="${legY + 4}" class="ps-small">move</text>
        ${glyphShoot(stackX + 74, legY, 8, true)}<text x="${stackX + 87}" y="${legY + 4}" class="ps-small">shoot</text>
        <text x="${stackX + 150}" y="${legY + 4}" class="ps-small">Filled = ship component</text>
        ${glyphMove(stackX + 330, legY, 8, false)}<text x="${stackX + 343}" y="${legY + 4}" class="ps-small">Outline = progression track</text>
      </g>`;
      const legY2 = legY + 22;
      stackSvg += `<g class="ps-legend">
        ${glyphMove(stackX + 4, legY2, 5.4, true)}${glyphMove(stackX + 13, legY2, 5.4, true)}${glyphMove(stackX + 22, legY2, 5.4, true)}<text x="${stackX + 34}" y="${legY2 + 4}" class="ps-small">Trio = fleet acts as a squadron</text>
        ${glyphBreacher(stackX + 330, legY2, 8)}<text x="${stackX + 343}" y="${legY2 + 4}" class="ps-small">Diamond = breacher core strike</text>
      </g>`;
      cursorY = legY2 + 48;
    }

    if (printOptions.components) {
      side += `<text x="70" y="${cursorY}" class="ps-section">Components</text>`;
      cursorY += 28;
      const components = design.tiles.filter((tile) => tile.type !== "generic");
      if (!components.length) {
        side += `<text x="70" y="${cursorY}" class="ps-small">No special components placed.</text>`;
        cursorY += 24;
      }
      components.forEach((tile) => {
        side += `<text x="70" y="${cursorY}" class="ps-list">${esc(componentBadge(tile))}</text>
          <text x="150" y="${cursorY}" class="ps-list">${esc(componentLabel(tile, numbers))} (${tile.q},${tile.r})</text>`;
        cursorY += 23;
      });
      cursorY += 20;
    }
    if (printOptions.laneList) {
      side += `<text x="70" y="${cursorY}" class="ps-section">Damage Lanes</text>`;
      cursorY += 28;
      for (const region of design.shield_regions) {
        const gen = region.generator ? `SG at ${region.generator[0]},${region.generator[1]}` : "no generator";
        side += `<text x="70" y="${cursorY}" class="ps-list">Area ${region.number}: ${esc(gen)}</text>`;
        cursorY += 22;
        const lanes = [...region.lanes].sort((a, b) => a.roll - b.roll);
        const laneText = lanes.length
          ? lanes.map((lane) => `${lane.roll}->${lane.q},${lane.r}`).join("  ")
          : "no lane arrows";
        side += `<text x="96" y="${cursorY}" class="ps-small">${esc(laneText)}</text>`;
        cursorY += 24;
      }
      cursorY += 12;
    }
    if (printOptions.fleet) {
      // Table aid: sits below every other section, summarizing the enemy
      // fleet and how the progression track changes what it does.
      const fleet = design.behavior?.fleet || defaultBehavior().fleet;
      side += `<text x="70" y="${cursorY}" class="ps-section">Fleet / Table Aid</text>`;
      cursorY += 28;
      side += `<text x="70" y="${cursorY}" class="ps-list">Fleet: ${fleet.count || 0} ${esc(fleet.kind || "craft")} at ${fleet.hp || 0} HP each</text>`;
      cursorY += 24;
      const actionText = (stack) => (fleet.actions || [])
        .filter((entry) => entry.stack === stack && (parseInt(entry.count, 10) || 0) > 0)
        .map((entry) => `${entry.action === "shoot" ? "shoot" : "move"} ×${entry.count}`)
        .join(", ");
      const actionLines = FLEET_STACKS
        .map((stack) => ({ stack, text: actionText(stack) }))
        .filter((line) => line.text);
      if (fleet.count > 0 && actionLines.length) {
        side += `<text x="70" y="${cursorY}" class="ps-list">Fleet actions each boss stage:</text>`;
        cursorY += 22;
        for (const line of actionLines) {
          side += `<text x="96" y="${cursorY}" class="ps-list">Action ${line.stack}: ${esc(line.text)}</text>`;
          cursorY += 22;
        }
      }
      const trackNotes = design.progression.steps
        .map((step, index) => ({ step, index }))
        .filter(({ step }) => ["spawn_fleet", "action_link", "ability_trigger", "ability_link"].includes(step.kind));
      if (trackNotes.length) {
        side += `<text x="70" y="${cursorY}" class="ps-list">When the progress marker reaches a numbered square:</text>`;
        cursorY += 22;
        for (const { step, index } of trackNotes) {
          let note;
          if (step.kind === "spawn_fleet") {
            const where = { boss_front: "front of boss", vault: "current vault", fang: "The Fang" }[step.location] || step.location;
            note = `spawn ${step.count || 1} fleet craft at ${where}`;
          } else if (step.kind === "action_link") {
            note = `the boss gains a ${step.action === "shoot" ? "shoot" : "move"} action in stack ${step.stack}`;
          } else if (step.kind === "ability_link") {
            note = `the boss gains ${ABILITY_LABELS[step.ability] || step.ability}`;
          } else {
            note = `ability comes online — ${abilityStepText(step)}`;
          }
          side += `<text x="96" y="${cursorY}" class="ps-list">Square ${index + 1}: ${esc(note)}</text>`;
          cursorY += 22;
        }
      }
      if ((design.supers || []).length) {
        side += `<text x="70" y="${cursorY}" class="ps-list">Super abilities (each fires every round in its stack while its Core lives):</text>`;
        cursorY += 22;
        for (const sup of design.supers) {
          const gate = sup.trigger?.kind === "progress" ? `progression step ${sup.trigger.value}` : `round ${sup.trigger?.value ?? 1}`;
          side += `<text x="96" y="${cursorY}" class="ps-list">${esc(superShortName(sup.effect))} — stack ${esc(STACK_SHORT[sup.stack] || sup.stack)}, from ${esc(gate)}, synced to Core ${sup.core || 1}.</text>`;
          cursorY += 22;
        }
      }
      side += `<text x="70" y="${cursorY}" class="ps-list">Damage-lane roll of 1 is always a glancing blow.</text>`;
      cursorY += 24;
    }

    pageH = Math.max(breachBox.y + breachBox.h + 220, cursorY + 130);

    return `<svg xmlns="http://www.w3.org/2000/svg" width="${pageW}" height="${pageH}" viewBox="0 0 ${pageW} ${pageH}">
      <defs>
        <style>
          .ps-title{font:700 44px 'Space Grotesk',Arial,sans-serif;fill:${colors.text}}
          .ps-sub{font:600 18px 'Space Grotesk',Arial,sans-serif;fill:${colors.dim}}
          .ps-section{font:700 24px 'Space Grotesk',Arial,sans-serif;fill:${colors.text}}
          .ps-badge{font:700 18px 'Space Grotesk',Arial,sans-serif;fill:${colors.text}}
          .ps-coord{font:600 10px 'Space Grotesk',Arial,sans-serif;fill:${colors.dim}}
          .ps-lane-num{font:700 14px 'Space Grotesk',Arial,sans-serif;fill:${colors.lane}}
          .ps-tier{font:700 13px 'Space Grotesk',Arial,sans-serif;fill:${colors.dim}}
          .ps-stack-title{font:700 17px 'Space Grotesk',Arial,sans-serif;fill:${colors.text}}
          .ps-card{font:700 12px 'Space Grotesk',Arial,sans-serif;fill:${colors.text}}
          .ps-small{font:500 12px 'Space Grotesk',Arial,sans-serif;fill:${colors.dim}}
          .ps-list{font:600 16px 'Space Grotesk',Arial,sans-serif;fill:${colors.text}}
        </style>
      </defs>
      <rect width="${pageW}" height="${pageH}" fill="${colors.page}"/>
      <text x="70" y="78" class="ps-title">${esc(design.name || "Boss Ship")}</text>
      <text x="72" y="112" class="ps-sub">StarShot printable boss ship sheet - ${printTone === "bw" ? "black and white" : "color"}</text>
      <text x="70" y="155" class="ps-section">Hull, Components, and Damage Lane Arrows</text>
      <rect x="${breachBox.x}" y="${breachBox.y}" width="${breachBox.w}" height="${breachBox.h}" rx="14" fill="${colors.hull}" stroke="${colors.line}" stroke-width="2"/>
      ${ship}
      ${stackSvg}
      ${side}
      <text x="70" y="${pageH - 90}" class="ps-sub">Physical play checklist: boss sheet, a damage-lane die per region (lanes + 1 sides), component damage markers, progression marker, fleet HP markers, vaults/objectives, and player ships/cards.</text>
    </svg>`;
  }

  function renderPrintView() {
    const container = el("bd-print");
    container.innerHTML = `<div class="bd-print-preview">${printSheetSVG()}</div>`;
  }

  function downloadPrintSheet() {
    const blob = new Blob([printSheetSVG()], { type: "image/svg+xml;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = `starshot-${(design.id || "boss").replace(/[^a-z0-9_-]+/gi, "-")}-print-sheet.svg`;
    document.body.appendChild(link);
    link.click();
    link.remove();
    URL.revokeObjectURL(url);
  }

  function printSheet() {
    const win = window.open("", "_blank");
    if (!win) {
      setStatus("Popup blocked. Use Download SVG and print the exported image.", false);
      return;
    }
    win.document.write(`<!doctype html><html><head><title>${esc(design.name)} print sheet</title>
      <style>body{margin:0;background:white}svg{width:100%;height:auto;display:block}@media print{body{margin:0}}</style>
      </head><body>${printSheetSVG()}<script>window.onload=function(){window.focus();window.print();};<\/script></body></html>`);
    win.document.close();
  }

  function fillSelect(node, values, labels, selected) {
    node.innerHTML = values.map((value) =>
      `<option value="${value}" ${value === selected ? "selected" : ""}>${esc(labels[value] || value)}</option>`).join("");
  }

  function renderBehaviorPanel() {
    const fleet = design.behavior.fleet;
    fillSelect(el("bd-boss-ai"), META.boss_ais || ["hunter_killer"], AI_LABELS, design.behavior.boss_ai);
    fillSelect(el("bd-fleet-ai"), META.fleet_ais || ["hunter_killer"], AI_LABELS, fleet.ai);
    el("bd-fleet-count").value = fleet.count;
    el("bd-fleet-hp").value = fleet.hp;
    el("bd-fleet-kind").value = fleet.kind;
    fillSelect(el("bd-goal-kind"), META.goal_kinds || ["escape_fang", "capture_vaults", "destroy_fleet"], GOAL_LABELS, design.goal.kind);
    el("bd-goal-count-wrap").classList.toggle("hidden", design.goal.kind !== "capture_vaults");
    el("bd-goal-count").value = design.goal.count || META.default_vault_goal_count || 8;
    renderSupersPanel();
    const table = el("bd-fleet-actions");
    table.querySelectorAll("tr:not(:first-child)").forEach((row) => row.remove());
    for (const stack of FLEET_STACKS) {
      const row = document.createElement("tr");
      const cells = ["move", "shoot"].map((action) => {
        const entry = fleet.actions.find((item) => item.stack === stack && item.action === action);
        const maxCount = META.fleet_max_action_count || FLEET_MAX_ACTION_COUNT;
        const count = entry ? Math.max(1, parseInt(entry.count, 10) || 1) : 0;
        return `<td><input type="number" min="0" max="${maxCount}" value="${count}" data-stack="${stack}" data-action="${action}"></td>`;
      });
      row.innerHTML = `<td>Action ${stack}</td>${cells.join("")}`;
      table.appendChild(row);
    }
    table.querySelectorAll("input[type=number]").forEach((box) => {
      box.addEventListener("change", () => {
        const maxCount = META.fleet_max_action_count || FLEET_MAX_ACTION_COUNT;
        const count = Math.max(0, Math.min(maxCount, parseInt(box.value, 10) || 0));
        box.value = count;
        const entry = { stack: box.dataset.stack, action: box.dataset.action, count };
        fleet.actions = fleet.actions.filter(
          (item) => !(item.stack === entry.stack && item.action === entry.action));
        if (count > 0) fleet.actions.push(entry);
        markDirty();
      });
    });
  }

  function shipCoreNumbers() {
    return [...new Set(design.tiles
      .filter((tile) => tile.type === "core").map((tile) => tile.number))].sort();
  }

  function renderSupersPanel() {
    const list = el("bd-supers");
    if (!list) return;
    list.innerHTML = design.supers.length ? "" : '<div class="admin-note">No Supers yet — this boss fights fair.</div>';
    const effects = META.super_effects || Object.keys(SUPER_LABELS);
    const triggerKinds = META.super_trigger_kinds || ["round", "progress"];
    const coreNumbers = shipCoreNumbers();
    design.supers.forEach((sup, index) => {
      const row = document.createElement("div");
      row.className = "bd-super-row";
      const coreOptions = (coreNumbers.length ? coreNumbers : [sup.core || 1]).map((n) =>
        `<option value="${n}" ${(sup.core || 1) === n ? "selected" : ""}>${n}</option>`);
      if (!coreNumbers.includes(sup.core || 1) && coreNumbers.length) {
        coreOptions.unshift(`<option value="${sup.core || 1}" selected>${sup.core || 1} (missing!)</option>`);
      }
      row.innerHTML = `
        <select data-f="effect">${effects.map((effect) =>
          `<option value="${effect}" ${sup.effect === effect ? "selected" : ""}>${esc(SUPER_LABELS[effect] || effect)}</option>`).join("")}</select>
        <span class="bd-super-when">
          <label>core <select data-f="core">${coreOptions.join("")}</select></label>
          <label>stack <select data-f="stack">${META.action_stacks.map((stack) =>
            `<option value="${stack}" ${(sup.stack || "starbreach") === stack ? "selected" : ""}>${STACK_SHORT[stack] || stack}</option>`).join("")}</select></label>
          <select data-f="kind">${triggerKinds.map((kind) =>
            `<option value="${kind}" ${sup.trigger.kind === kind ? "selected" : ""}>${esc(SUPER_TRIGGER_LABELS[kind] || kind)}</option>`).join("")}</select>
          <input data-f="value" type="number" min="1" max="99" value="${sup.trigger.value ?? 1}">
          <button class="btn ghost small" data-a="del" title="Remove this Super">✕</button>
        </span>`;
      row.querySelector('[data-f="effect"]').addEventListener("change", (event) => {
        sup.effect = event.target.value;
        markDirty();
      });
      row.querySelector('[data-f="core"]').addEventListener("change", (event) => {
        sup.core = parseInt(event.target.value, 10) || 1;
        markDirty();
      });
      row.querySelector('[data-f="stack"]').addEventListener("change", (event) => {
        sup.stack = event.target.value;
        markDirty();
        if (mode === "stacks") renderStacksView();
      });
      row.querySelector('[data-f="kind"]').addEventListener("change", (event) => {
        sup.trigger.kind = event.target.value;
        markDirty();
      });
      row.querySelector('[data-f="value"]').addEventListener("change", (event) => {
        sup.trigger.value = Math.max(1, Math.min(99, parseInt(event.target.value, 10) || 1));
        event.target.value = sup.trigger.value;
        markDirty();
      });
      row.querySelector('[data-a="del"]').addEventListener("click", () => {
        design.supers.splice(index, 1);
        markDirty();
        renderSupersPanel();
      });
      list.appendChild(row);
    });
  }

  function renderStructurePanel() {
    root().querySelectorAll(".bd-tool").forEach((button) =>
      button.classList.toggle("active", button.dataset.tool === tool.type));
    const numbered = tool.type === "shield_gen" || tool.type === "core";
    const stacked = tool.type === "cannon" || tool.type === "engine" || tool.type === "docking_bay";
    el("bd-tool-number-wrap").classList.toggle("hidden", !numbered);
    el("bd-tool-stack-wrap").classList.toggle("hidden", !stacked);
    el("bd-tool-number-label").textContent =
      tool.type === "core" ? "Core number" : "Ship region number";
  }

  function renderShieldPanel() {
    const select = el("bd-region-select");
    select.innerHTML = "";
    for (const region of design.shield_regions) {
      const option = document.createElement("option");
      option.value = region.number;
      option.textContent = `Region ${region.number} - ${region.hexes.length} hexes, ${region.lanes.length}/${regionLaneCount(region)} lanes`;
      if (region.number === currentRegion) option.selected = true;
      select.appendChild(option);
    }
    root().querySelectorAll(".bd-shieldsub").forEach((button) =>
      button.classList.toggle("active", button.dataset.sub === shieldSub));
    el("bd-lane-tools").classList.toggle("hidden", shieldSub !== "lanes");
    el("bd-lane-stack").checked = stackLanes;

    const region = regionByNumber(currentRegion);
    const info = el("bd-region-info");
    if (!region) {
      info.innerHTML = '<span class="admin-note">No ship region selected. Add one to begin.</span>';
      return;
    }
    const generatorText = region.generator
      ? `shield gen at (${region.generator[0]},${region.generator[1]})`
      : "<b>none - use Power Source, then click an SG tile</b>";
    const rolls = regionRolls(region);
    const laneCount = rolls.length;
    const topRoll = rolls[rolls.length - 1];
    const used = region.lanes.map((lane) => lane.roll).sort((a, b) => a - b);
    const missing = rolls.filter((roll) => !used.includes(roll));
    info.innerHTML = `
      <div><span class="bd-swatch" style="background:${regionColor(region.number)}"></span>
        Powered by: ${generatorText}</div>
      <div class="bd-charges-row">
        <label>Start charges <input id="bd-region-charges" type="number" min="0" max="9" value="${region.charges ?? 3}"></label>
        <label>Max charges <input id="bd-region-maxcharges" type="number" min="0" max="9" value="${region.max_charges ?? 3}"></label>
        ${shieldSub === "hexes" ? '<button class="btn ghost small" id="bd-region-unshielded" type="button">Unshielded</button>' : ""}
        ${shieldSub === "power" && region.generator ? '<button class="btn ghost small" id="bd-region-clear-generator" type="button">Clear source</button>' : ""}
      </div>
      <div class="bd-charges-row">
        <label>Damage lanes <input id="bd-region-lanecount" type="number" min="1" max="${META.max_lane_count || 12}" value="${laneCount}"></label>
        <span class="admin-note" style="margin:0">d${laneCount + 1}: 1 misses, 2-${topRoll} are lanes</span>
      </div>
      <div>Lanes assigned: ${used.join(", ") || "none"}${missing.length ? ` · ${used.length}/${laneCount}` : ` · all ${laneCount}`}</div>
      <div class="admin-note">${shieldSub === "hexes"
        ? "Click hull hexes to add/remove them from this protected region. Shield Gen tiles can be protected here like any other hull tile."
        : shieldSub === "power"
          ? `Click SG${region.number} to set the generator that powers this region. The generator may belong to another protected region.`
          : `Click a region hex to assign the next lane (2-${topRoll}). Click again to rotate its entry face; past the last face, the lane is cleared. Tick the box to stack a second lane on a laned hex.`}</div>`;
    const chargesInput = info.querySelector("#bd-region-charges");
    const maxInput = info.querySelector("#bd-region-maxcharges");
    const applyCharges = () => {
      region.max_charges = Math.max(0, Math.min(9, parseInt(maxInput.value, 10) || 0));
      region.charges = Math.max(0, Math.min(region.max_charges, parseInt(chargesInput.value, 10) || 0));
      chargesInput.value = region.charges;
      maxInput.value = region.max_charges;
      markDirty();
    };
    chargesInput.addEventListener("change", applyCharges);
    maxInput.addEventListener("change", applyCharges);
    info.querySelector("#bd-region-unshielded")?.addEventListener("click", () => {
      region.charges = 0;
      region.max_charges = 0;
      markDirty();
      renderShieldPanel();
      renderBoard();
    });
    info.querySelector("#bd-region-clear-generator")?.addEventListener("click", () => {
      region.generator = null;
      markDirty();
      renderShieldPanel();
      renderBoard();
    });
    info.querySelector("#bd-region-lanecount").addEventListener("change", (event) => {
      const next = Math.max(1, Math.min(META.max_lane_count || 12, parseInt(event.target.value, 10) || laneCount));
      region.lane_count = next;
      // Lanes whose roll no longer fits the smaller die are dropped.
      region.lanes = region.lanes.filter((lane) => lane.roll <= next + 1);
      markDirty();
      renderShieldPanel();
      renderBoard();
    });
  }

  function nextRegionNumber() {
    const used = new Set(design.shield_regions.map((region) => region.number));
    for (let number = 1; number <= 9; number++) if (!used.has(number)) return number;
    return null;
  }

  function renderProgressionPanel() {
    const triggerBox = el("bd-triggers");
    triggerBox.innerHTML = "";
    for (const trigger of META.trigger_types) {
      const label = document.createElement("label");
      label.className = "bd-trigger";
      const checkbox = document.createElement("input");
      checkbox.type = "checkbox";
      checkbox.checked = design.progression.triggers.includes(trigger);
      checkbox.addEventListener("change", () => {
        const set = new Set(design.progression.triggers);
        checkbox.checked ? set.add(trigger) : set.delete(trigger);
        design.progression.triggers = META.trigger_types.filter((t) => set.has(t));
        markDirty();
      });
      label.appendChild(checkbox);
      label.appendChild(document.createTextNode(" " + (TRIGGER_LABELS[trigger] || trigger)));
      triggerBox.appendChild(label);
    }

    const list = el("bd-steps");
    list.innerHTML = design.progression.steps.length
      ? '<div class="bd-step-header"><span></span><span>#</span><span>Slot Type</span><span>Action Number / Type</span><span></span></div>'
      : '<div class="admin-note">No steps yet — the track is empty.</div>';
    design.progression.steps.forEach((step, index) => list.appendChild(stepRow(step, index)));
  }

  function stepRow(step, index) {
    const row = document.createElement("div");
    row.className = "bd-step";
    const coreNumbers = [...new Set(design.tiles
      .filter((tile) => tile.type === "core").map((tile) => tile.number))].sort();

    let fields = "";
    if (step.kind === "action_link") {
      fields = `
        <select data-f="stack" title="Action number">${META.action_stacks.map((stack) =>
          `<option ${step.stack === stack ? "selected" : ""}>${stack}</option>`).join("")}</select>
        <select data-f="action" title="Action type">
          <option ${step.action === "move" ? "selected" : ""}>move</option>
          <option ${step.action === "shoot" ? "selected" : ""}>shoot</option></select>`;
    } else if (step.kind === "breacher_link") {
      fields = `
        <label>core <select data-f="core"><option value="">—</option>${coreNumbers.map((number) =>
          `<option ${step.core === number ? "selected" : ""}>${number}</option>`).join("")}</select></label>
        <label>round ≥ <input data-f="round" type="number" min="1" max="99" value="${step.round ?? ""}" placeholder="—"></label>`;
    } else if (step.kind === "ability_trigger") {
      fields = `<label>name <input data-f="name" maxlength="80" value="${esc(step.name || "")}"></label>`;
    } else if (step.kind === "ability_link") {
      const abilities = META.ability_types || Object.keys(ABILITY_LABELS);
      fields = `<label>grants <select data-f="ability">${abilities.map((ability) =>
        `<option value="${ability}" ${step.ability === ability ? "selected" : ""}>${ABILITY_LABELS[ability] || ability}</option>`).join("")}</select></label>`;
    } else if (step.kind === "spawn_fleet") {
      const locations = META.spawn_locations || ["boss_front", "vault", "fang"];
      const locationLabels = { boss_front: "front of boss", vault: "current vault", fang: "The Fang" };
      const counts = Array.from({ length: META.spawn_max_count || 3 }, (_v, i) => i + 1);
      fields = `
        <label>craft <select data-f="count">${counts.map((n) =>
          `<option ${(step.count || 1) === n ? "selected" : ""}>${n}</option>`).join("")}</select></label>
        <label>at <select data-f="location">${locations.map((location) =>
          `<option value="${location}" ${step.location === location ? "selected" : ""}>${locationLabels[location] || location}</option>`).join("")}</select></label>`;
    }

    row.innerHTML = `
      <span class="bd-step-drag" draggable="true" title="Drag to reorder">⠿</span>
      <span class="bd-step-index">${index + 1}</span>
      <select data-f="kind">
        <option value="filler" ${step.kind === "filler" ? "selected" : ""}>Filler</option>
        <option value="action_link" ${step.kind === "action_link" ? "selected" : ""}>Action link</option>
        <option value="breacher_link" ${step.kind === "breacher_link" ? "selected" : ""}>Breacher link</option>
        <option value="ability_trigger" ${step.kind === "ability_trigger" ? "selected" : ""}>Ability trigger</option>
        <option value="ability_link" ${step.kind === "ability_link" ? "selected" : ""}>Ability link</option>
        <option value="spawn_fleet" ${step.kind === "spawn_fleet" ? "selected" : ""}>Spawn fleet</option>
      </select>
      <span class="bd-step-fields">${fields}</span>
      <span class="bd-step-actions">
        <button class="btn ghost small" data-a="up" ${index === 0 ? "disabled" : ""}>↑</button>
        <button class="btn ghost small" data-a="down" ${index === design.progression.steps.length - 1 ? "disabled" : ""}>↓</button>
        <button class="btn ghost small" data-a="del">✕</button>
      </span>`;

    row.querySelector(".bd-step-drag").addEventListener("dragstart", () => {
      dragPayload = { type: "steprow", index };
    });
    row.addEventListener("dragover", (event) => {
      if (dragPayload && dragPayload.type === "steprow") event.preventDefault();
    });
    row.addEventListener("drop", (event) => {
      event.preventDefault();
      if (!dragPayload || dragPayload.type !== "steprow") return;
      moveStep(dragPayload.index, index);
      dragPayload = null;
      renderProgressionPanel();
    });
    row.querySelector('[data-f="kind"]').addEventListener("change", (event) => {
      design.progression.steps[index] = defaultStep(event.target.value);
      markDirty();
      renderProgressionPanel();
    });
    row.querySelectorAll("[data-f]:not([data-f=kind])").forEach((node) => {
      node.addEventListener("change", () => {
        const field = node.dataset.f;
        if (field === "count") {
          step.count = Math.max(1, Math.min(META.spawn_max_count || 3, parseInt(node.value, 10) || 1));
        } else if (field === "core" || field === "round") {
          const value = parseInt(node.value, 10);
          if (Number.isNaN(value)) delete step[field];
          else step[field] = value;
        } else {
          step[field] = node.value;
        }
        markDirty();
      });
    });
    row.querySelectorAll("[data-a]").forEach((button) => {
      button.addEventListener("click", () => {
        const steps = design.progression.steps;
        if (button.dataset.a === "del") steps.splice(index, 1);
        if (button.dataset.a === "up" && index > 0) {
          [steps[index - 1], steps[index]] = [steps[index], steps[index - 1]];
        }
        if (button.dataset.a === "down" && index < steps.length - 1) {
          [steps[index + 1], steps[index]] = [steps[index], steps[index + 1]];
        }
        markDirty();
        renderProgressionPanel();
      });
    });
    return row;
  }

  function defaultStep(kind) {
    if (kind === "action_link") return { kind, stack: META.action_stacks[0], action: "shoot" };
    if (kind === "breacher_link") return { kind, round: 1 };
    if (kind === "ability_trigger") return { kind, name: "New ability", notes: "" };
    if (kind === "ability_link") return { kind, ability: (META.ability_types || ["signal_jammer"])[0] };
    if (kind === "spawn_fleet") return { kind, count: 1, location: "boss_front" };
    return { kind: "filler" };
  }

  function renderProblems(problems) {
    const box = el("bd-problems");
    if (!problems || !problems.length) {
      box.innerHTML = '<span class="ok-note">✔ No design problems.</span>';
      return;
    }
    box.innerHTML = "<b>Design warnings</b>" +
      problems.map((problem) => `<div class="bd-problem">⚠ ${esc(problem)}</div>`).join("");
  }

  // ── design management ────────────────────────────────────────────────────
  function renderDesignList() {
    const select = el("bd-design-select");
    select.innerHTML = designs.length ? "" : "<option value=''>— no designs yet —</option>";
    for (const entry of designs) {
      const option = document.createElement("option");
      option.value = entry.id;
      const badge = entry.valid ? "✔" : "⚠";
      option.textContent = `${badge} ${entry.name} (${entry.tile_count} tiles, ${entry.region_count} regions, ${entry.step_count} steps)` +
        (entry.valid ? "" : " — not battle-ready");
      if (design && entry.id === design.id) option.selected = true;
      select.appendChild(option);
    }
  }

  function defaultBehavior() {
    return {
      boss_ai: "hunter_killer",
      fleet: { count: 0, kind: "hunter_killer", hp: 3, ai: "hunter_killer", actions: [] },
    };
  }

  function normalizeProgression() {
    if (!design.progression) design.progression = { triggers: [], steps: [] };
    if (!Array.isArray(design.progression.triggers)) design.progression.triggers = [];
    if (!Array.isArray(design.progression.steps)) design.progression.steps = [];
    design.progression.steps = design.progression.steps.map((step) => {
      if (!step || typeof step !== "object") return defaultStep("filler");
      const kind = step.kind || step.type || "filler";
      return (META.step_kinds || []).includes(kind) ? { ...step, kind } : defaultStep("filler");
    });
  }

  function openDesign(document_) {
    design = document_;
    normalizeProgression();
    if (!design.behavior) design.behavior = defaultBehavior();
    if (!Array.isArray(design.supers)) design.supers = [];
    // Migrate any pre-core-sync Supers: default to core 1 / StarBreach stack.
    design.supers = design.supers.map((sup) => ({
      effect: sup.effect,
      core: sup.core || 1,
      stack: sup.stack || "starbreach",
      trigger: sup.trigger && SUPER_TRIGGER_LABELS[sup.trigger.kind]
        ? { kind: sup.trigger.kind, value: sup.trigger.value || 1 }
        : { kind: "round", value: 1 },
    }));
    if (!design.goal || !design.goal.kind) design.goal = { kind: "escape_fang" };
    for (const region of design.shield_regions) {
      if (region.max_charges === undefined) region.max_charges = region.charges ?? 3;
      if (region.charges === undefined) region.charges = region.max_charges;
      if (region.lane_count === undefined) region.lane_count = META.default_lane_count || 7;
    }
    dirty = false;
    el("bd-save").classList.remove("attention");
    currentRegion = design.shield_regions.length ? design.shield_regions[0].number : null;
    el("bd-name").value = design.name;
    el("bd-editor").classList.remove("hidden");
    renderBoard();
    renderModePanel();
  }

  async function refreshList(selectId) {
    const data = await call("");
    if (data.meta) META = data.meta;
    designs = data.designs || [];
    renderDesignList();
    if (selectId) el("bd-design-select").value = selectId;
  }

  async function loadSelected() {
    const id = el("bd-design-select").value;
    if (!id) return;
    try {
      const data = await call("/" + encodeURIComponent(id));
      openDesign(data.design);
      renderProblems(data.problems);
      setStatus("", true);
    } catch (error) { setStatus("✘ " + error.message, false); }
  }

  async function saveDesign() {
    if (!design) return;
    design.name = el("bd-name").value.trim() || design.name;
    normalizeProgression();
    try {
      const result = await call("", { method: "PUT", body: JSON.stringify(design) });
      dirty = false;
      el("bd-save").classList.remove("attention");
      renderProblems(result.problems);
      setStatus(`✔ Saved "${result.design.name}".`, true);
      await refreshList(design.id);
    } catch (error) { setStatus("✘ " + error.message, false); }
  }

  // ── boot / markup ────────────────────────────────────────────────────────
  async function publishDefaultDesign() {
    if (!isAdmin || !design) return;
    if (dirty) {
      setStatus("Save this boss before publishing it as public/default.", false);
      return;
    }
    try {
      const result = await call("/" + encodeURIComponent(design.id) + "/publish", { method: "POST", body: "{}" });
      setStatus(`✔ "${result.design.name}" is public and the default StarBreach boss.`, true);
      await refreshList(design.id);
    } catch (error) { setStatus("✘ " + error.message, false); }
  }

  function buildMarkup() {
    const transferTools = isAdmin ? `
        <span class="deck-set-sep">|</span>
        <button class="btn ghost small" id="bd-download">⬇ Download</button>
        <input id="bd-import-file" type="file" accept=".json,application/json">
        <button class="btn ghost small" id="bd-upload">⬆ Upload</button>` : "";
    const publishButton = isAdmin ? '<button class="btn gold" id="bd-publish-default">Public + Default</button>' : "";
    const playerLibrary = isAdmin ? `
      <div class="bd-designbar bd-player-library">
        <span class="bd-strip-label">Player bosses:</span>
        <select id="bd-player-design-select"><option value="">— loading… —</option></select>
        <button class="btn ghost small" id="bd-player-refresh">↻</button>
        <button class="btn gold small" id="bd-player-clone">⧉ Clone to shared library</button>
      </div>` : `
      <p class="admin-note">Design up to ${META.player_design_limit || 10} of yer own bosses and launch
        StarBreach raids against them. The admiralty may clone favorites into everyone's library.</p>`;
    root().innerHTML = `
      <h2 class="panel-title">Boss Ship Designer</h2>
      <div class="bd-designbar">
        <select id="bd-design-select"></select>
        <button class="btn ghost small" id="bd-load">Open</button>
        <input id="bd-new-name" placeholder="New boss name…" maxlength="80">
        <button class="btn gold small" id="bd-new">＋ New design</button>${transferTools}
        <span class="deck-set-sep">|</span>
        <button class="btn crimson small" id="bd-delete">🗑 Delete</button>
      </div>
      ${playerLibrary}
      <div id="bd-editor" class="hidden">
        <div class="bd-topbar">
          <label>Name <input id="bd-name" maxlength="80"></label>
          <div class="bd-modes">
            <button class="btn ghost bd-mode active" data-mode="structure">⬡ Structure</button>
            <button class="btn ghost bd-mode" data-mode="shields">🛡 Ship Regions</button>
            <button class="btn ghost bd-mode" data-mode="progression">📈 Progression</button>
            <button class="btn ghost bd-mode" data-mode="stacks">🗂 Action Stacks</button>
            <button class="btn ghost bd-mode" data-mode="behavior">⚙ Behavior</button>
            <button class="btn ghost bd-mode" data-mode="print">Print Sheets</button>
          </div>
          <button class="btn gold" id="bd-save">💾 Save design</button>
          ${publishButton}
        </div>
        <div class="bd-grid">
          <div class="bd-board-wrap">
            <div id="bd-board" class="bd-board"></div>
            <button class="btn ghost small bd-view-reset hidden" id="bd-view-reset" title="Reset zoom and pan">⤢ Fit</button>
            <div id="bd-stacks" class="bd-stacks hidden"></div>
            <div id="bd-print" class="bd-print hidden"></div>
          </div>
          <div class="bd-side">
            <div id="bd-panel-structure">
              <h3 class="panel-sub">Tile palette</h3>
              <div class="bd-tools">${TILE_TOOLS.map((entry) =>
                `<button class="btn ghost small bd-tool" data-tool="${entry.type}">${entry.badge ? entry.badge + " " : ""}${entry.label}</button>`).join("")}
              </div>
              <label id="bd-tool-number-wrap" class="hidden">
                <span id="bd-tool-number-label">Number</span>
                <select id="bd-tool-number">${[1, 2, 3, 4, 5, 6, 7, 8, 9].map((n) => `<option>${n}</option>`).join("")}</select>
              </label>
              <label id="bd-tool-stack-wrap" class="hidden">Action stack
                <select id="bd-tool-stack">${META.action_stacks.map((stack) => `<option>${stack}</option>`).join("")}</select>
              </label>
              <p class="admin-note">Click a hex to place the selected tile (overwrites).
                Right-click or use the eraser to remove. Shield Gens number a ship region;
                Cannons grant an attack, Engines grant a move, and Docking Bays launch enemies in their action stack;
                Cores anchor Breacher-stack abilities.</p>
            </div>
            <div id="bd-panel-shields" class="hidden">
              <h3 class="panel-sub">Ship Regions</h3>
              <div class="bd-regionbar">
                <select id="bd-region-select"></select>
                <button class="btn ghost small" id="bd-region-add">＋ Region</button>
                <button class="btn ghost small" id="bd-region-del">✕</button>
              </div>
              <div class="bd-shieldsubs">
                <button class="btn ghost small bd-shieldsub active" data-sub="hexes">Protected Hexes</button>
                <button class="btn ghost small bd-shieldsub" data-sub="power">Power Source</button>
                <button class="btn ghost small bd-shieldsub" data-sub="lanes">Damage Lanes</button>
              </div>
              <div id="bd-lane-tools" class="bd-lane-tools hidden">
                <label><input type="checkbox" id="bd-lane-stack"> Allow a second lane on a laned hex</label>
                <button class="btn ghost small" id="bd-lane-renumber">⇢ Renumber lanes left-to-right</button>
                <button class="btn ghost small" id="bd-lane-autonumber">✨ Autonumber lanes</button>
              </div>
              <div id="bd-region-info" class="bd-region-info"></div>
            </div>
            <div id="bd-panel-stacks" class="hidden">
              <h3 class="panel-sub">Ship view</h3>
              <div id="bd-stacks-mini" class="bd-mini-ship bd-mini-side"></div>
            </div>
            <div id="bd-panel-behavior" class="hidden">
              <h3 class="panel-sub">Boss behavior</h3>
              <label class="bd-field">Boss AI
                <select id="bd-boss-ai"></select>
              </label>
              <h3 class="panel-sub">Fleet craft</h3>
              <div class="bd-fleet-row">
                <label>Count <input id="bd-fleet-count" type="number" min="0" max="6"></label>
                <label>HP <input id="bd-fleet-hp" type="number" min="1" max="9"></label>
              </div>
              <div class="bd-fleet-row">
                <label>Type <select id="bd-fleet-kind"><option value="hunter_killer">Mini Hunter-Killer</option></select></label>
              </div>
              <label class="bd-field">Fleet AI
                <select id="bd-fleet-ai"></select>
              </label>
              <p class="admin-note">The boss and its fleet may run the same or different AI programs.</p>
              <h3 class="panel-sub">Fleet actions per boss stage</h3>
              <p class="admin-note">Set how many times the fleet moves or shoots at each boss action stage.</p>
              <table class="bd-fleet-actions" id="bd-fleet-actions">
                <tr><th>Stage</th><th>Move</th><th>Shoot</th></tr>
              </table>
              <h3 class="panel-sub">Super abilities</h3>
              <p class="admin-note">Each Super is synced to a Core and joins an action stack like any
                other boss action: it fires every round in that stack once its round or
                progression-step requirement is met — and falls silent if its Core is destroyed.</p>
              <div id="bd-supers" class="bd-supers"></div>
              <button class="btn ghost small" id="bd-super-add">＋ Add Super</button>
              <h3 class="panel-sub">Player goal</h3>
              <label class="bd-field">Victory condition
                <select id="bd-goal-kind"></select>
              </label>
              <label class="bd-field" id="bd-goal-count-wrap">Vaults needed
                <input id="bd-goal-count" type="number" min="1" max="30">
              </label>
            </div>
            <div id="bd-panel-print" class="hidden">
              <h3 class="panel-sub">Printable export</h3>
              <p class="admin-note">Export a table-ready boss sheet with component labels,
                damage lane arrows, action stacks, and the reference pieces needed for
                in-person play. Shield arcs are not drawn on the sheet.</p>
              <div class="bd-print-controls">
                <label>Tone
                  <select id="bd-print-tone">
                    <option value="color">Color</option>
                    <option value="bw">Black and white</option>
                  </select>
                </label>
                <label><input type="checkbox" data-print-opt="lanes" ${printOptions.lanes ? "checked" : ""}> Damage lane arrows (on ship)</label>
                <label><input type="checkbox" data-print-opt="laneList" ${printOptions.laneList ? "checked" : ""}> Damage lane list (sidebar)</label>
                <label><input type="checkbox" data-print-opt="stacks" ${printOptions.stacks ? "checked" : ""}> Action stacks</label>
                <label><input type="checkbox" data-print-opt="stackLinks" ${printOptions.stackLinks ? "checked" : ""}> Action stack links to ship</label>
                <label><input type="checkbox" data-print-opt="coords" ${printOptions.coords ? "checked" : ""}> Hex coordinates</label>
                <label><input type="checkbox" data-print-opt="components" ${printOptions.components ? "checked" : ""}> Component legend</label>
                <label><input type="checkbox" data-print-opt="progression" ${printOptions.progression ? "checked" : ""}> Progression track</label>
                <label><input type="checkbox" data-print-opt="fleet" ${printOptions.fleet ? "checked" : ""}> Fleet and table aids</label>
                <label>Ship scale
                  <input id="bd-print-zoom" type="range" min="50" max="200" step="5" value="100">
                  <span id="bd-print-zoom-value">100%</span>
                </label>
              </div>
              <div class="bd-print-actions">
                <button class="btn gold" id="bd-print-download">Download SVG</button>
                <button class="btn ghost" id="bd-print-now">Print</button>
              </div>
            </div>
            <div id="bd-panel-progression" class="hidden">
              <h3 class="panel-sub">Progression triggers</h3>
              <div id="bd-triggers" class="bd-triggers"></div>
              <h3 class="panel-sub">Progression track</h3>
              <div id="bd-steps" class="bd-steps"></div>
              <button class="btn ghost small" id="bd-step-add">＋ Add step</button>
            </div>
          </div>
        </div>
        <div id="bd-problems" class="bd-problems"></div>
      </div>
      <div id="bd-status" class="admin-status"></div>`;
  }

  function wireEvents() {
    el("bd-load").addEventListener("click", loadSelected);
    el("bd-design-select").addEventListener("change", loadSelected);
    el("bd-new").addEventListener("click", async () => {
      const name = el("bd-new-name").value.trim();
      if (!name) { setStatus("Name the boss first.", false); return; }
      const id = name.toLowerCase().replace(/[^a-z0-9]+/g, "_").replace(/^_+|_+$/g, "");
      if (!id) { setStatus("Use some letters or digits in the name.", false); return; }
      openDesign({
        id, name, description: "", tiles: [], shield_regions: [],
        progression: { triggers: [], steps: [] },
        behavior: defaultBehavior(),
        supers: [],
        goal: { kind: "escape_fang" },
      });
      el("bd-new-name").value = "";
      markDirty();
      renderProblems([]);
      setStatus(`New design "${name}" — remember to save.`, true);
    });
    el("bd-delete").addEventListener("click", async () => {
      const id = el("bd-design-select").value;
      if (!id) { setStatus("Pick a design to delete.", false); return; }
      if (!window.confirm(`Delete boss design "${id}" for good?`)) return;
      try {
        await call("/" + encodeURIComponent(id), { method: "DELETE" });
        if (design && design.id === id) {
          design = null;
          el("bd-editor").classList.add("hidden");
        }
        await refreshList();
        setStatus("Design deleted.", true);
      } catch (error) { setStatus("✘ " + error.message, false); }
    });
    el("bd-save").addEventListener("click", saveDesign);
    el("bd-publish-default")?.addEventListener("click", publishDefaultDesign);
    el("bd-name").addEventListener("change", markDirty);

    root().querySelectorAll(".bd-mode").forEach((button) => {
      button.addEventListener("click", () => {
        mode = button.dataset.mode;
        renderModePanel();
        renderBoard();
      });
    });

    root().querySelectorAll(".bd-tool").forEach((button) => {
      button.addEventListener("click", () => {
        tool.type = button.dataset.tool;
        renderStructurePanel();
      });
    });
    el("bd-tool-number").addEventListener("change", (event) => {
      tool.number = parseInt(event.target.value, 10) || 1;
    });
    el("bd-tool-stack").addEventListener("change", (event) => {
      tool.stack = event.target.value;
    });

    el("bd-region-select").addEventListener("change", (event) => {
      currentRegion = parseInt(event.target.value, 10) || null;
      renderShieldPanel();
      renderBoard();
    });
    el("bd-region-add").addEventListener("click", () => {
      const number = nextRegionNumber();
      if (number === null) { setStatus("All nine region numbers are in use.", false); return; }
      design.shield_regions.push({
        number, hexes: [], generator: null, lanes: [],
        lane_count: META.default_lane_count || 7, charges: 3, max_charges: 3,
      });
      currentRegion = number;
      markDirty();
      renderShieldPanel();
      renderBoard();
    });
    el("bd-region-del").addEventListener("click", () => {
      if (currentRegion === null) return;
      design.shield_regions = design.shield_regions.filter((region) => region.number !== currentRegion);
      currentRegion = design.shield_regions.length ? design.shield_regions[0].number : null;
      markDirty();
      renderShieldPanel();
      renderBoard();
    });
    root().querySelectorAll(".bd-shieldsub").forEach((button) => {
      button.addEventListener("click", () => {
        shieldSub = button.dataset.sub;
        renderShieldPanel();
        renderBoard(); // lanes only draw while assigning them
      });
    });
    el("bd-lane-stack").addEventListener("change", (event) => {
      stackLanes = !!event.target.checked;
    });
    el("bd-lane-renumber").addEventListener("click", () => {
      const region = regionByNumber(currentRegion);
      if (!region || !region.lanes.length) { setStatus("No lanes to renumber in this region.", false); return; }
      renumberLanes(region);
      markDirty();
      renderBoard();
      renderShieldPanel();
      setStatus("Lanes renumbered left-to-right.", true);
    });
    el("bd-lane-autonumber").addEventListener("click", () => {
      const region = regionByNumber(currentRegion);
      if (!region) { setStatus("Add a ship region first.", false); return; }
      if (!region.hexes.length) { setStatus("Give this region some protected hexes first.", false); return; }
      if (!autonumberLanes(region)) {
        setStatus("No hull-edge faces found in this region — lanes need an outside entry face.", false);
        return;
      }
      markDirty();
      renderBoard();
      renderShieldPanel();
      setStatus(`✨ ${region.lanes.length} lanes laid out across region ${region.number}.`, true);
    });

    el("bd-boss-ai").addEventListener("change", (event) => {
      design.behavior.boss_ai = event.target.value;
      markDirty();
    });
    el("bd-fleet-count").addEventListener("change", (event) => {
      design.behavior.fleet.count = Math.max(0, Math.min(6, parseInt(event.target.value, 10) || 0));
      event.target.value = design.behavior.fleet.count;
      markDirty();
    });
    el("bd-fleet-hp").addEventListener("change", (event) => {
      design.behavior.fleet.hp = Math.max(1, Math.min(9, parseInt(event.target.value, 10) || 1));
      event.target.value = design.behavior.fleet.hp;
      markDirty();
    });
    el("bd-fleet-kind").addEventListener("change", (event) => {
      design.behavior.fleet.kind = event.target.value;
      markDirty();
    });
    el("bd-fleet-ai").addEventListener("change", (event) => {
      design.behavior.fleet.ai = event.target.value;
      markDirty();
    });
    el("bd-goal-kind").addEventListener("change", (event) => {
      design.goal.kind = event.target.value;
      if (design.goal.kind === "capture_vaults" && !design.goal.count) {
        design.goal.count = META.default_vault_goal_count || 8;
      }
      if (design.goal.kind !== "capture_vaults") delete design.goal.count;
      markDirty();
      renderBehaviorPanel();
    });
    el("bd-goal-count").addEventListener("change", (event) => {
      design.goal.count = Math.max(1, Math.min(META.max_vault_goal_count || 30,
        parseInt(event.target.value, 10) || META.default_vault_goal_count || 8));
      event.target.value = design.goal.count;
      markDirty();
    });
    el("bd-super-add").addEventListener("click", () => {
      if (design.supers.length >= (META.max_supers || 12)) {
        setStatus("That's the Super limit — this boss is dramatic enough.", false);
        return;
      }
      design.supers.push({
        effect: (META.super_effects || ["immobilizer_shot"])[0],
        core: shipCoreNumbers()[0] || 1,
        stack: "starbreach",
        trigger: { kind: "round", value: 2 },
      });
      markDirty();
      renderSupersPanel();
    });
    el("bd-print-tone").addEventListener("change", (event) => {
      printTone = event.target.value === "bw" ? "bw" : "color";
      renderPrintView();
    });
    root().querySelectorAll("[data-print-opt]").forEach((box) => {
      box.addEventListener("change", () => {
        printOptions[box.dataset.printOpt] = !!box.checked;
        renderPrintView();
      });
    });
    el("bd-print-zoom").addEventListener("input", (event) => {
      printZoom = Math.max(0.5, Math.min(2, (parseInt(event.target.value, 10) || 100) / 100));
      el("bd-print-zoom-value").textContent = Math.round(printZoom * 100) + "%";
      renderPrintView();
    });
    el("bd-print-download").addEventListener("click", downloadPrintSheet);
    el("bd-print-now").addEventListener("click", printSheet);

    if (isAdmin) {
      el("bd-download").addEventListener("click", async () => {
        const id = el("bd-design-select").value;
        if (!id) { setStatus("Pick a design to download.", false); return; }
        try {
          const response = await fetch(API + "/" + encodeURIComponent(id) + "/export", { credentials: "same-origin" });
          if (!response.ok) throw new Error(`Download failed (${response.status})`);
          const url = URL.createObjectURL(await response.blob());
          const link = document.createElement("a");
          link.href = url;
          link.download = `starshot-boss-${id}.json`;
          document.body.appendChild(link);
          link.click();
          link.remove();
          URL.revokeObjectURL(url);
        } catch (error) { setStatus("✘ " + error.message, false); }
      });
      el("bd-upload").addEventListener("click", async () => {
        const input = el("bd-import-file");
        const file = input.files && input.files[0];
        if (!file) { setStatus("Choose a boss design .json file first.", false); return; }
        try {
          const result = await call("/import", { method: "POST", body: await file.text() });
          input.value = "";
          await refreshList(result.design.id);
          openDesign(result.design);
          renderProblems(result.problems);
          setStatus(`✔ Imported as "${result.design.name}" (${result.design.id})` +
            (result.renamed ? " — renamed to avoid clobbering an existing design." : "."), true);
        } catch (error) { setStatus("✘ Upload failed: " + error.message, false); }
      });
      wirePlayerLibrary();
    }

    el("bd-step-add").addEventListener("click", () => {
      design.progression.steps.push(defaultStep("filler"));
      markDirty();
      renderProgressionPanel();
    });

    window.addEventListener("beforeunload", (event) => {
      if (dirty) event.preventDefault();
    });

    wireBoardZoomPan();
  }

  /* Zoom (mouse wheel, centered on the cursor) and pan (drag) over the hex
     editor board. A drag beyond a few pixels suppresses the click so painting
     tiles and panning don't fight over the mouse. */
  function wireBoardZoomPan() {
    const board = el("bd-board");
    const defaultView = () => {
      const R = META.grid_radius;
      const extent = SIZE * 1.5 * R + SIZE * 3.2;
      const extentY = SIZE * SQ * R + SIZE * 3.2;
      return { x: -extent, y: -extentY, w: extent * 2, h: extentY * 2 };
    };
    const applyView = () => {
      const svg = board.querySelector("svg");
      const view = boardView || defaultView();
      if (svg) svg.setAttribute("viewBox", `${view.x} ${view.y} ${view.w} ${view.h}`);
      el("bd-view-reset")?.classList.toggle("hidden", !boardView);
    };
    board.addEventListener("wheel", (event) => {
      if (!design) return;
      const svg = board.querySelector("svg");
      if (!svg) return;
      event.preventDefault();
      const base = defaultView();
      const view = boardView || { ...base };
      const rect = board.getBoundingClientRect();
      const fx = Math.min(1, Math.max(0, (event.clientX - rect.left) / rect.width));
      const fy = Math.min(1, Math.max(0, (event.clientY - rect.top) / rect.height));
      const factor = event.deltaY > 0 ? 1.18 : 1 / 1.18;
      const w = Math.min(base.w * 1.4, Math.max(base.w / 8, view.w * factor));
      const h = w * (base.h / base.w);
      boardView = {
        x: view.x + (view.w - w) * fx,
        y: view.y + (view.h - h) * fy,
        w, h,
      };
      if (Math.abs(w - base.w) < base.w * 0.02) boardView = null; // snapped back to fit
      applyView();
    }, { passive: false });

    let drag = null;
    let suppressClick = false;
    board.addEventListener("pointerdown", (event) => {
      if (!design || event.button !== 0) return;
      drag = { startX: event.clientX, startY: event.clientY, panned: false, view: boardView };
    });
    board.addEventListener("pointermove", (event) => {
      if (!drag) return;
      const dx = event.clientX - drag.startX;
      const dy = event.clientY - drag.startY;
      if (!drag.panned && Math.hypot(dx, dy) < 5) return;
      drag.panned = true;
      const base = defaultView();
      const view = drag.view || base;
      const rect = board.getBoundingClientRect();
      boardView = {
        x: view.x - dx * (view.w / rect.width),
        y: view.y - dy * (view.h / rect.height),
        w: view.w,
        h: view.h,
      };
      applyView();
    });
    const endDrag = () => {
      if (drag && drag.panned) {
        suppressClick = true;
        setTimeout(() => { suppressClick = false; }, 0);
      }
      drag = null;
    };
    board.addEventListener("pointerup", endDrag);
    board.addEventListener("pointerleave", endDrag);
    // Capture-phase: a pan must not paint the tile under the cursor.
    board.addEventListener("click", (event) => {
      if (suppressClick) {
        event.stopPropagation();
        event.preventDefault();
      }
    }, true);
    el("bd-view-reset").addEventListener("click", () => {
      boardView = null;
      applyView();
    });
  }

  // Admin only: browse every player's designs and clone one into the shared
  // library so all crews can fight it.
  let playerDesigns = [];
  async function refreshPlayerLibrary() {
    const select = el("bd-player-design-select");
    if (!select) return;
    try {
      const response = await fetch("/api/v2/admin/player-boss-designs", { credentials: "same-origin" });
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || `Request failed (${response.status})`);
      playerDesigns = data.designs || [];
      select.innerHTML = playerDesigns.length ? "" : "<option value=''>— no player designs yet —</option>";
      playerDesigns.forEach((entry, index) => {
        const option = document.createElement("option");
        option.value = String(index);
        option.textContent = `${entry.valid ? "✔" : "⚠"} ${entry.owner_name}: ${entry.name}` +
          ` (${entry.tile_count} tiles, ${entry.step_count} steps)` + (entry.valid ? "" : " — not battle-ready");
        select.appendChild(option);
      });
    } catch (error) { setStatus("✘ " + error.message, false); }
  }

  function wirePlayerLibrary() {
    refreshPlayerLibrary();
    el("bd-player-refresh").addEventListener("click", refreshPlayerLibrary);
    el("bd-player-clone").addEventListener("click", async () => {
      const entry = playerDesigns[parseInt(el("bd-player-design-select").value, 10)];
      if (!entry) { setStatus("Pick a player design to clone.", false); return; }
      try {
        const response = await fetch(
          `/api/v2/admin/player-boss-designs/${entry.owner_id}/${encodeURIComponent(entry.id)}/clone`,
          { method: "POST", credentials: "same-origin", headers: { "Content-Type": "application/json" } },
        );
        const data = await response.json();
        if (!response.ok) throw new Error(data.detail || `Request failed (${response.status})`);
        await refreshList(data.design.id);
        openDesign(data.design);
        renderProblems(data.problems);
        setStatus(`✔ Cloned "${data.design.name}" from ${entry.owner_name} into the shared library as "${data.design.id}".`, true);
      } catch (error) { setStatus("✘ Clone failed: " + error.message, false); }
    });
  }

  async function boot() {
    if (booted) return;
    booted = true;
    buildMarkup();
    wireEvents();
    try {
      await refreshList();
      setStatus("", true);
    } catch (error) {
      setStatus("✘ " + error.message + (isAdmin ? " (sign in as the admin first)" : ""), false);
      booted = false; // retry on next open
    }
  }

  return { boot };
  } // end createBossDesigner

  // Admin page: lazy-boot inside the #tab-bossdesign tab.
  const adminTabs = document.querySelectorAll('.admin-tab[data-tab="bossdesign"]');
  if (adminTabs.length) {
    const adminDesigner = createBossDesigner({
      apiBase: "/api/v2/admin/boss-designs",
      root: () => document.getElementById("tab-bossdesign"),
      isAdmin: true,
    });
    adminTabs.forEach((tab) => tab.addEventListener("click", adminDesigner.boot));
  }

  // Main app: full-screen "My Bosses" overlay, opened from the lobby.
  const LS_BUILD_CLICKED = "ss_build_content_clicked";
  const LS_BUILD_INTRO = "ss_build_content_intro_seen";
  const LS_BUILDER_HOWTO = "ss_bossdesigner_howto_seen";
  const lsGet = (key) => { try { return localStorage.getItem(key); } catch (err) { return null; } };
  const lsSet = (key) => { try { localStorage.setItem(key, "1"); } catch (err) { /* private mode */ } };

  let playerDesigner = null;
  function openPlayerDesigner() {
    let overlay = document.getElementById("player-bossdesigner-overlay");
    if (!overlay) {
      overlay = document.createElement("div");
      overlay.id = "player-bossdesigner-overlay";
      overlay.className = "bd-player-overlay";
      overlay.innerHTML = `
        <div class="bd-player-shell">
          <div class="bd-player-toprow">
            <button class="btn ghost small bd-player-close" id="bd-player-close">✕ Back to Port</button>
            <button class="btn ghost small" id="bd-player-help">❓ Help</button>
          </div>
          <div id="player-bossdesign"></div>
        </div>`;
      document.body.appendChild(overlay);
      overlay.querySelector("#bd-player-close").addEventListener("click", () => {
        overlay.classList.add("hidden");
      });
      overlay.querySelector("#bd-player-help").addEventListener("click", () => showBuilderHowto());
    }
    overlay.classList.remove("hidden");
    if (!playerDesigner) {
      playerDesigner = createBossDesigner({
        apiBase: "/api/v2/my/boss-designs",
        root: () => document.getElementById("player-bossdesign"),
        isAdmin: false,
      });
    }
    playerDesigner.boot();
    maybeShowBuilderHowto();
  }

  function showBuilderHowto() {
    const howto = document.createElement("div");
    howto.className = "overlay bd-howto-overlay";
    howto.innerHTML = `
      <div class="picker">
        <h3>🛠 StarBreach Ship Builder — how it works</h3>
        <div class="tutorial-steps">
          <div><b>1.</b> Name a new boss and hit <b>＋ New design</b>, then paint hull tiles in <b>Structure</b>. Cannons grant attacks, Engines grant moves, Docking Bays launch enemies, Shield Gens power ship regions, Cores anchor Breacher abilities.</div>
          <div><b>2.</b> In <b>Ship Regions</b>, group hexes into ship regions and give each one damage lanes — the numbered arrows attackers roll against.</div>
          <div><b>3.</b> <b>Progression</b> builds the boss's power-up track; <b>Action Stacks</b> shows which stack each ability feeds — drag cards between columns to reassign them.</div>
          <div><b>4.</b> <b>Save</b> your design, then pick it as the StarBreach Boss when you launch a raid. You can also export a printable sheet from <b>Print Sheets</b>.</div>
        </div>
        <button class="btn gold picker-cancel" id="bd-howto-ok">Got it</button>
      </div>`;
    document.body.appendChild(howto);
    howto.querySelector("#bd-howto-ok").addEventListener("click", () => howto.remove());
  }
  // One-time "how to" blurb the first time a player enters the builder.
  function maybeShowBuilderHowto() {
    if (lsGet(LS_BUILDER_HOWTO)) return;
    lsSet(LS_BUILDER_HOWTO);
    showBuilderHowto();
  }

  // Lobby topbar "Build New Content" button: twinkles until first clicked.
  // Opens a small hub so players can pick between the two designers.
  function openBuildContentHub() {
    const hub = document.createElement("div");
    hub.className = "overlay";
    hub.innerHTML = `
      <div class="picker">
        <h3>🛠 Build New Content</h3>
        <div class="bd-hub-actions">
          <button class="btn gold" id="bd-hub-bosses">StarBreach<span class="btn-sub">Build Bosses</span></button>
          <button class="btn gold" id="bd-hub-ships">StarDock<span class="btn-sub">Build Player Ships</span></button>
        </div>
        <button class="btn ghost picker-cancel" id="bd-hub-cancel">Never mind</button>
      </div>`;
    document.body.appendChild(hub);
    hub.querySelector("#bd-hub-cancel").addEventListener("click", () => hub.remove());
    hub.querySelector("#bd-hub-bosses").addEventListener("click", () => {
      hub.remove();
      openPlayerDesigner();
    });
    hub.querySelector("#bd-hub-ships").addEventListener("click", () => {
      hub.remove();
      window.ShipDesigner?.openPlayerDesigner?.();
    });
  }

  let twinkleTimer = null;
  function wireBuildContentButton() {
    const button = document.getElementById("btn-build-content");
    if (!button) return;
    if (!lsGet(LS_BUILD_CLICKED)) {
      twinkleTimer = setInterval(() => {
        button.classList.add("bd-twinkle");
        setTimeout(() => button.classList.remove("bd-twinkle"), 1300);
      }, 4200);
    }
    button.addEventListener("click", () => {
      lsSet(LS_BUILD_CLICKED);
      if (twinkleTimer) { clearInterval(twinkleTimer); twinkleTimer = null; }
      button.classList.remove("bd-twinkle");
      openBuildContentHub();
    });
  }
  wireBuildContentButton();

  // One-time popup pointing new users at the button (called on lobby entry).
  function offerBuildContentIntro() {
    if (lsGet(LS_BUILD_INTRO)) return;
    // If the first-visit rules tour is up, let it go first; this intro will
    // fire on the next lobby entry instead.
    const tour = document.getElementById("tutorial-overlay");
    if (tour && !tour.classList.contains("hidden")) return;
    lsSet(LS_BUILD_INTRO);
    const overlay = document.createElement("div");
    overlay.className = "overlay";
    overlay.innerHTML = `
      <div class="picker">
        <h3>🛠 New: Build Your Own Content</h3>
        <div class="tutorial-steps">
          <div>You can design your own <b>player ships</b> — spend 19 points on shields, card draw, and armor, then fly them in place of the standard ship.</div>
          <div>You can also design <b>StarBreach boss ships</b> — hull, shields, damage lanes, progression track, and fleet — then battle them with your crew.</div>
          <div>Find the <b>🛠 Build New Content</b> button at the top of the page, next to your captain's name. It'll sparkle until you've paid it a visit.</div>
        </div>
        <div class="bd-intro-actions">
          <button class="btn gold picker-cancel" id="bd-intro-open">🛠 Take me there</button>
          <button class="btn ghost picker-cancel" id="bd-intro-later">Later</button>
        </div>
      </div>`;
    document.body.appendChild(overlay);
    overlay.querySelector("#bd-intro-later").addEventListener("click", () => overlay.remove());
    overlay.querySelector("#bd-intro-open").addEventListener("click", () => {
      overlay.remove();
      lsSet(LS_BUILD_CLICKED);
      if (twinkleTimer) { clearInterval(twinkleTimer); twinkleTimer = null; }
      document.getElementById("btn-build-content")?.classList.remove("bd-twinkle");
      openBuildContentHub();
    });
  }

  window.BossDesigner = { openPlayerDesigner, offerBuildContentIntro };
})();
