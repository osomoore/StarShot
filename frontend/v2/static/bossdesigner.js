/* Boss Ship Designer.
 *
 * Self-contained: builds its own DOM inside a host element and talks only to
 * its design API. Two instances exist:
 *   - admin  (admin page tab #tab-bossdesign, /api/v2/admin/boss-designs),
 *     which also gets a player-design browse/clone bar
 *   - player (full-screen overlay on the main app, /api/v2/my/boss-designs,
 *     capped library — players may fight their own creations)
 * Edit modes over one SVG hex board:
 *   structure     — paint hull tiles (generic / shield gen / firing computer /
 *                   fuel tank / core)
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
      "bauble_pickup_boss", "bauble_pickup_fleet",
      "prey_hull_damage_boss", "prey_hull_damage_fleet", "player_kill",
    ],
    spawn_locations: ["boss_front", "bauble", "fang"],
    spawn_max_count: 3,
    player_design_limit: 10,
  };

  const TILE_TOOLS = [
    { type: "generic", label: "Generic", badge: "" },
    { type: "shield_gen", label: "Shield Gen", badge: "SG" },
    { type: "firing_computer", label: "Firing Computer", badge: "FC" },
    { type: "fuel_tank", label: "Fuel Tank", badge: "FT" },
    { type: "core", label: "Core", badge: "◉" },
    { type: "erase", label: "Eraser", badge: "✕" },
  ];
  const TILE_FILL = {
    generic: "154,163,184", shield_gen: "120,190,255", firing_computer: "255,140,120",
    fuel_tank: "255,205,110", core: "222,160,255",
  };
  const REGION_COLORS = ["#59c8ff", "#ff9d6b", "#9dff8a", "#ffd75e", "#ff7ad0",
    "#8f9dff", "#6bffd8", "#ff6b6b", "#d0ff5e"];
  const STACK_SHORT = { "0.5": "0.5", "1.5": "1.5", "2.5": "2.5", "3.5": "3.5", starbreach: "SB" };
  const FLEET_STACKS = ["0.5", "1.5", "2.5", "3.5"];
  const TRIGGER_LABELS = {
    bauble_pickup_boss: "Bauble pickup — boss",
    bauble_pickup_fleet: "Bauble pickup — boss fleet",
    prey_hull_damage_boss: "Prey hull damage — boss",
    prey_hull_damage_fleet: "Prey hull damage — boss fleet",
    player_kill: "Kill a player ship",
  };

  // ── state ────────────────────────────────────────────────────────────────
  let booted = false;
  let designs = [];        // list summaries
  let design = null;       // the open design document (canonical schema)
  let dirty = false;
  let mode = "structure";  // structure | shields | progression
  let tool = { type: "generic", number: 1, stack: "0.5" };
  let currentRegion = null; // shield region number being edited
  let shieldSub = "hexes";  // hexes | lanes
  let stackLanes = false;   // lanes sub-mode: clicks stack a second lane on a hex
  let printTone = "color";  // color | bw
  let printOptions = {
    lanes: true, stacks: true, stackLinks: true, components: true, progression: true, fleet: true,
  };

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
  const COMPONENT_LABEL = { firing_computer: "Cannon", fuel_tank: "Engine", shield_gen: "Shield Gen", core: "Core" };
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
    if (tile.type === "firing_computer") return "C" + n + " " + (STACK_SHORT[tile.stack] || tile.stack);
    if (tile.type === "fuel_tank") return "E" + n + " " + (STACK_SHORT[tile.stack] || tile.stack);
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
    el("bd-board").innerHTML = `
      <svg viewBox="${-extent} ${-extentY} ${extent * 2} ${extentY * 2}">
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
    if (tool.type === "firing_computer" || tool.type === "fuel_tank") tile.stack = tool.stack;
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
    if (!region) { setStatus("Add a shield region first.", false); return; }
    const tile = tileAt(q, r);
    if (!tile) return;
    if (shieldSub === "hexes") {
      if (tile.type === "shield_gen") {
        // Clicking a generator assigns it as the region's power source.
        region.generator = [q, r];
      } else {
        const index = region.hexes.findIndex(([hq, hr]) => hq === q && hr === r);
        if (index >= 0) {
          region.hexes.splice(index, 1);
          region.lanes = region.lanes.filter((lane) => !(lane.q === q && lane.r === r));
        } else {
          region.hexes.push([q, r]);
        }
      }
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
      setStatus("That hex is not in this shield region — add it in Protected Hexes first.", false);
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
    const used = new Set(region.lanes.map((lane) => lane.roll));
    const next = META.lane_rolls.find((roll) => !used.has(roll));
    if (next === undefined) {
      setStatus("All seven lanes (2-8) are assigned — click an assigned hex to adjust or clear it.", false);
      return;
    }
    // A stacked lane defaults to an entry face the hex isn't using yet.
    const takenFacings = new Set(hexLanes.map((lane) => lane.facing));
    const facing = facings.find((candidate) => !takenFacings.has(candidate)) ?? facings[0];
    region.lanes.push({ roll: next, q, r, facing });
  }

  /* Reassign rolls 2..8 to this region's lanes ordered by where their number
     labels sit on the board, left-to-right (top-to-bottom breaks ties). */
  function renumberLanes(region) {
    const labelPos = (lane) => {
      const [cx, cy] = xy(lane.q, lane.r);
      const [dq, dr] = DIRS[lane.facing];
      const [ox, oy] = xy(lane.q + dq, lane.r + dr);
      const len = Math.hypot(ox - cx, oy - cy) || 1;
      return [cx + ((ox - cx) / len) * SIZE * 1.9, cy + ((oy - cy) / len) * SIZE * 1.9];
    };
    const ordered = [...region.lanes].sort((a, b) => {
      const [ax, ay] = labelPos(a);
      const [bx, by] = labelPos(b);
      return ax - bx || ay - by;
    });
    ordered.forEach((lane, index) => {
      lane.roll = META.lane_rolls[index % META.lane_rolls.length];
    });
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
      if (tile.type === "firing_computer") {
        byStack[tile.stack].push({
          kind: "attack", label: componentLabel(tile, numbers), source: "component",
          q: tile.q, r: tile.r,
        });
      } else if (tile.type === "fuel_tank") {
        byStack[tile.stack].push({
          kind: "move", label: componentLabel(tile, numbers), source: "component",
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
      }
    });
    const fleet = design.behavior?.fleet || defaultBehavior().fleet;
    if (fleet.count > 0) {
      for (const entry of fleet.actions || []) {
        if (byStack[entry.stack]) {
          byStack[entry.stack].push({
            kind: "fleet", label: `Fleet x${fleet.count}: ${entry.action}`, source: "behavior",
          });
        }
      }
    }
    return byStack;
  }

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
    if (step.kind === "spawn_fleet") {
      const where = { boss_front: "front of boss", bauble: "current bauble", fang: "The Fang" }[step.location] || step.location;
      return `▣ Spawn ${step.count || 1} fleet craft — ${where}`;
    }
    return "Filler";
  }

  function moveStep(fromIndex, toIndex) {
    const steps = design.progression.steps;
    if (fromIndex === toIndex || fromIndex < 0 || fromIndex >= steps.length) return;
    const [step] = steps.splice(fromIndex, 1);
    if (!step || typeof step !== "object") return;
    steps.splice(toIndex > fromIndex ? toIndex - 1 : toIndex, 0, step);
    markDirty();
  }

  function renderStacksView() {
    const container = el("bd-stacks");
    container.innerHTML = "";

    // Progression strip: the track in order; drag a chip onto another to reorder.
    const strip = document.createElement("div");
    strip.className = "bd-prog-strip";
    const stripLabel = document.createElement("span");
    stripLabel.className = "bd-strip-label";
    stripLabel.textContent = "Progression track:";
    strip.appendChild(stripLabel);
    design.progression.steps.forEach((step, index) => {
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
      strip.appendChild(chip);
    });
    if (!design.progression.steps.length) {
      const empty = document.createElement("span");
      empty.className = "admin-note";
      empty.textContent = "no steps yet (add them in Progression)";
      strip.appendChild(empty);
    }
    container.appendChild(strip);

    const cols = document.createElement("div");
    cols.className = "bd-stack-cols";
    for (const stack of META.action_stacks) {
      const col = document.createElement("div");
      col.className = "bd-stack-col";
      col.innerHTML = `<div class="bd-stack-head">${stack === "starbreach" ? "StarBreach" : "Action " + stack}</div>`;
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

      const addItem = (label, sub, payload, extraClass, hoverHex) => {
        const item = document.createElement("div");
        item.className = "bd-stack-item" + (extraClass ? " " + extraClass : "");
        item.innerHTML = `<div>${label}</div>${sub ? `<div class="bd-item-sub">${sub}</div>` : ""}`;
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
        if (tile.type === "firing_computer") {
          addItem(esc(componentLabel(tile, numbers)), "component · attack", { type: "tile", q: tile.q, r: tile.r }, "bd-item-attack", [tile.q, tile.r]);
        } else if (tile.type === "fuel_tank") {
          addItem(esc(componentLabel(tile, numbers)), "component · move", { type: "tile", q: tile.q, r: tile.r }, "bd-item-move", [tile.q, tile.r]);
        }
      }
      design.progression.steps.forEach((step, index) => {
        if (step.kind === "action_link" && step.stack === stack) {
          addItem(
            `Step ${index + 1} — ${step.action}`,
            `progression · unlocks at ${index + 1}`,
            { type: "step", index },
            step.action === "shoot" ? "bd-item-attack" : "bd-item-move"
          );
        } else if (step.kind === "breacher_link" && stack === "starbreach") {
          const bits = [];
          if (step.core !== undefined) bits.push(`core ${step.core}`);
          if (step.round !== undefined) bits.push(`round ≥ ${step.round}`);
          addItem(
            `Step ${index + 1} — Breacher`,
            `progression · unlocks at ${index + 1}${bits.length ? " · " + bits.join(" · ") : ""}`,
            null,
            "bd-item-breacher"
          );
        }
      });
      const fleetKinds = (design.behavior.fleet.actions || [])
        .filter((entry) => entry.stack === stack)
        .map((entry) => entry.action);
      if (design.behavior.fleet.count > 0 && fleetKinds.length) {
        addItem(`Fleet ×${design.behavior.fleet.count}`, "fleet · " + fleetKinds.join(" + "), null, "bd-item-fleet");
      }
      cols.appendChild(col);
    }
    container.appendChild(cols);

    // Mini ship view: hover a component card above to see it light up here.
    const mini = document.createElement("div");
    mini.className = "bd-mini-ship";
    mini.innerHTML = `<div class="bd-mini-ship-label">Ship view — hover a component card to locate it</div>${miniShipSVG()}`;
    container.appendChild(mini);
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
      const badge = tile.type === "firing_computer" ? "C" + numbers[key(tile.q, tile.r)]
        : tile.type === "fuel_tank" ? "E" + numbers[key(tile.q, tile.r)]
        : tile.type === "shield_gen" ? "S" + tile.number
        : tile.type === "core" ? "◉" : "";
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
    const node = el("bd-stacks")?.querySelector(`[data-hex="${q},${r}"]`);
    if (node) node.classList.toggle("bd-mini-hot", !!on);
  }

  function printPalette() {
    if (printTone === "bw") {
      return {
        page: "#ffffff", text: "#111111", dim: "#555555", line: "#111111",
        hull: "#f4f4f4", generic: "#ffffff", attack: "#eeeeee", move: "#dddddd",
        shieldGen: "#e8e8e8", core: "#cfcfcf", lane: "#111111", fleet: "#f0f0f0",
      };
    }
    return {
      page: "#fffaf0", text: "#151923", dim: "#5f6675", line: "#283246",
      hull: "#f2ead8", generic: "#f8f3e7", attack: "#ffd2c7", move: "#ffe2a8",
      shieldGen: "#c7eaff", core: "#e8c8ff", lane: "#c54530", fleet: "#d6f3ff",
    };
  }

  function printTileFill(tile, colors) {
    if (tile.type === "firing_computer") return colors.attack;
    if (tile.type === "fuel_tank") return colors.move;
    if (tile.type === "shield_gen") return colors.shieldGen;
    if (tile.type === "core") return colors.core;
    return colors.generic;
  }

  function printSheetSVG() {
    if (!design) return "";
    const colors = printPalette();
    const numbers = componentNumbers();
    const stacks = actionStackItems();
    const pageW = 1400;
    const pageH = 1900;
    const breachBox = { x: 55, y: 175, w: 640, h: 640 };
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
    );
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
      if (tile.type === "firing_computer") return "C" + numbers[key(tile.q, tile.r)];
      if (tile.type === "fuel_tank") return "E" + numbers[key(tile.q, tile.r)];
      if (tile.type === "shield_gen") return "SG" + tile.number;
      if (tile.type === "core") return "CORE " + tile.number;
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
        <text x="${x}" y="${y + shipSize - 5}" text-anchor="middle" class="ps-coord">${tile.q},${tile.r}</text>
        <title>${esc(title)} (${tile.q},${tile.r})</title>
      </g>`;
    }

    if (printOptions.lanes) {
      for (const region of design.shield_regions) {
        for (const lane of region.lanes) {
          const [cx, cy] = pxy(lane.q, lane.r);
          const [dq, dr] = DIRS[lane.facing];
          const [ox, oy] = pxy(lane.q + dq, lane.r + dr);
          let ux = ox - cx, uy = oy - cy;
          const len = Math.hypot(ux, uy) || 1;
          ux /= len; uy /= len;
          const startX = cx + ux * shipSize * 1.48;
          const startY = cy + uy * shipSize * 1.48;
          const endX = cx + ux * shipSize * 1.04;
          const endY = cy + uy * shipSize * 1.04;
          ship += `<g class="ps-lane">
            <line x1="${startX.toFixed(1)}" y1="${startY.toFixed(1)}" x2="${endX.toFixed(1)}" y2="${endY.toFixed(1)}"
              stroke="${colors.lane}" stroke-width="2.4" marker-end="url(#psArrow)"/>
            <circle cx="${startX.toFixed(1)}" cy="${startY.toFixed(1)}" r="11" fill="${colors.page}" stroke="${colors.lane}" stroke-width="2"/>
            <text x="${startX.toFixed(1)}" y="${(startY + 5).toFixed(1)}" text-anchor="middle" class="ps-lane-num">${lane.roll}</text>
          </g>`;
        }
      }
    }

    const stackX = 70;
    const stackY = 875;
    const colW = 244;
    const colGap = 10;
    const rowH = 38;
    let stackSvg = "";
    if (printOptions.stacks) {
      META.action_stacks.forEach((stack, stackIndex) => {
        const x = stackX + stackIndex * (colW + colGap);
        const items = stacks[stack] || [];
        stackSvg += `<g>
          <rect x="${x}" y="${stackY}" width="${colW}" height="320" rx="8" fill="${colors.generic}" stroke="${colors.line}" stroke-width="2"/>
          <text x="${x + colW / 2}" y="${stackY + 27}" text-anchor="middle" class="ps-stack-title">${stack === "starbreach" ? "StarBreach" : "Action " + stack}</text>`;
        if (!items.length) {
          stackSvg += `<text x="${x + colW / 2}" y="${stackY + 70}" text-anchor="middle" class="ps-small">empty</text>`;
        }
        items.slice(0, 6).forEach((item, itemIndex) => {
          const y = stackY + 48 + itemIndex * rowH;
          const fill = item.kind === "attack" ? colors.attack
            : item.kind === "move" ? colors.move
            : item.kind === "fleet" ? colors.fleet
            : colors.hull;
          stackSvg += `<rect x="${x + 8}" y="${y}" width="${colW - 16}" height="${rowH - 7}" rx="6"
              fill="${fill}" stroke="${colors.line}" stroke-width="1.5"/>
            <text x="${x + 14}" y="${y + 15}" class="ps-card">${esc(item.label)}</text>
            <text x="${x + 14}" y="${y + 29}" class="ps-small">${esc(item.q !== undefined ? `hex ${item.q},${item.r}` : item.source)}</text>`;
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
        if (items.length > 6) {
          stackSvg += `<text x="${x + 14}" y="${stackY + 305}" class="ps-small">+ ${items.length - 6} more</text>`;
        }
        stackSvg += "</g>";
      });
    }

    let side = "";
    let sideY = 170;
    if (printOptions.components) {
      side += `<text x="760" y="${sideY}" class="ps-section">Components</text>`;
      sideY += 28;
      const components = design.tiles.filter((tile) => tile.type !== "generic");
      if (!components.length) {
        side += `<text x="760" y="${sideY}" class="ps-small">No special components placed.</text>`;
        sideY += 24;
      }
      components.forEach((tile) => {
        side += `<text x="760" y="${sideY}" class="ps-list">${esc(componentBadge(tile))}</text>
          <text x="840" y="${sideY}" class="ps-list">${esc(componentLabel(tile, numbers))} (${tile.q},${tile.r})</text>`;
        sideY += 23;
      });
      sideY += 20;
    }
    if (printOptions.lanes) {
      side += `<text x="760" y="${sideY}" class="ps-section">Damage Lanes</text>`;
      sideY += 28;
      for (const region of design.shield_regions) {
        const gen = region.generator ? `SG at ${region.generator[0]},${region.generator[1]}` : "no generator";
        side += `<text x="760" y="${sideY}" class="ps-list">Area ${region.number}: ${esc(gen)}</text>`;
        sideY += 22;
        const lanes = [...region.lanes].sort((a, b) => a.roll - b.roll);
        const laneText = lanes.length
          ? lanes.map((lane) => `${lane.roll}->${lane.q},${lane.r}`).join("  ")
          : "no lane arrows";
        side += `<text x="786" y="${sideY}" class="ps-small">${esc(laneText)}</text>`;
        sideY += 24;
      }
      sideY += 12;
    }
    if (printOptions.progression) {
      side += `<text x="760" y="${sideY}" class="ps-section">Progression Track</text>`;
      sideY += 28;
      if (!design.progression.steps.length) {
        side += `<text x="760" y="${sideY}" class="ps-small">No progression steps.</text>`;
        sideY += 24;
      }
      design.progression.steps.forEach((step, index) => {
        side += `<text x="760" y="${sideY}" class="ps-list">${index + 1}. ${esc(stepLabel(step))}</text>`;
        sideY += 22;
      });
      sideY += 12;
    }
    if (printOptions.fleet) {
      const fleet = design.behavior?.fleet || defaultBehavior().fleet;
      side += `<text x="760" y="${sideY}" class="ps-section">Fleet / Table Aids</text>`;
      sideY += 28;
      side += `<text x="760" y="${sideY}" class="ps-list">Fleet: ${fleet.count || 0} ${esc(fleet.kind || "craft")} at ${fleet.hp || 0} HP</text>`;
      sideY += 22;
      side += `<text x="760" y="${sideY}" class="ps-list">Use the arrows only for shield-area damage lanes; shield arcs are intentionally omitted.</text>`;
      sideY += 22;
      side += `<text x="760" y="${sideY}" class="ps-list">Unassigned d8 lane numbers reroll during play.</text>`;
    }

    return `<svg xmlns="http://www.w3.org/2000/svg" width="${pageW}" height="${pageH}" viewBox="0 0 ${pageW} ${pageH}">
      <defs>
        <marker id="psArrow" markerWidth="8" markerHeight="8" refX="7" refY="3" orient="auto">
          <path d="M0,0 L8,3 L0,6 Z" fill="${colors.lane}"/>
        </marker>
        <style>
          .ps-title{font:700 44px 'Space Grotesk',Arial,sans-serif;fill:${colors.text}}
          .ps-sub{font:600 18px 'Space Grotesk',Arial,sans-serif;fill:${colors.dim}}
          .ps-section{font:700 24px 'Space Grotesk',Arial,sans-serif;fill:${colors.text}}
          .ps-badge{font:700 18px 'Space Grotesk',Arial,sans-serif;fill:${colors.text}}
          .ps-coord{font:600 10px 'Space Grotesk',Arial,sans-serif;fill:${colors.dim}}
          .ps-lane-num{font:700 14px 'Space Grotesk',Arial,sans-serif;fill:${colors.lane}}
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
      <text x="70" y="1810" class="ps-sub">Physical play checklist: boss sheet, d8 for damage lanes, component damage markers, progression marker, fleet HP markers, baubles/objectives, and player ships/cards.</text>
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

  function renderBehaviorPanel() {
    const fleet = design.behavior.fleet;
    el("bd-boss-ai").value = design.behavior.boss_ai;
    el("bd-fleet-count").value = fleet.count;
    el("bd-fleet-hp").value = fleet.hp;
    el("bd-fleet-kind").value = fleet.kind;
    el("bd-fleet-ai").value = fleet.ai;
    const table = el("bd-fleet-actions");
    table.querySelectorAll("tr:not(:first-child)").forEach((row) => row.remove());
    for (const stack of FLEET_STACKS) {
      const row = document.createElement("tr");
      const cells = ["move", "shoot"].map((action) => {
        const ticked = fleet.actions.some((entry) => entry.stack === stack && entry.action === action);
        return `<td><input type="checkbox" data-stack="${stack}" data-action="${action}" ${ticked ? "checked" : ""}></td>`;
      });
      row.innerHTML = `<td>Action ${stack}</td>${cells.join("")}`;
      table.appendChild(row);
    }
    table.querySelectorAll("input[type=checkbox]").forEach((box) => {
      box.addEventListener("change", () => {
        const entry = { stack: box.dataset.stack, action: box.dataset.action };
        fleet.actions = fleet.actions.filter(
          (item) => !(item.stack === entry.stack && item.action === entry.action));
        if (box.checked) fleet.actions.push(entry);
        markDirty();
      });
    });
  }

  function renderStructurePanel() {
    root().querySelectorAll(".bd-tool").forEach((button) =>
      button.classList.toggle("active", button.dataset.tool === tool.type));
    const numbered = tool.type === "shield_gen" || tool.type === "core";
    const stacked = tool.type === "firing_computer" || tool.type === "fuel_tank";
    el("bd-tool-number-wrap").classList.toggle("hidden", !numbered);
    el("bd-tool-stack-wrap").classList.toggle("hidden", !stacked);
    el("bd-tool-number-label").textContent =
      tool.type === "core" ? "Core number" : "Shield region number";
  }

  function renderShieldPanel() {
    const select = el("bd-region-select");
    select.innerHTML = "";
    for (const region of design.shield_regions) {
      const option = document.createElement("option");
      option.value = region.number;
      option.textContent = `Region ${region.number} — ${region.hexes.length} hexes, ${region.lanes.length}/7 lanes`;
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
      info.innerHTML = '<span class="admin-note">No shield region selected. Add one to begin.</span>';
      return;
    }
    const generatorText = region.generator
      ? `shield gen at (${region.generator[0]},${region.generator[1]})`
      : "<b>none — click a Shield Gen tile to power this region</b>";
    const used = region.lanes.map((lane) => lane.roll).sort((a, b) => a - b);
    const missing = META.lane_rolls.filter((roll) => !used.includes(roll));
    info.innerHTML = `
      <div><span class="bd-swatch" style="background:${regionColor(region.number)}"></span>
        Powered by: ${generatorText}</div>
      <div class="bd-charges-row">
        <label>Start charges <input id="bd-region-charges" type="number" min="0" max="9" value="${region.charges ?? 3}"></label>
        <label>Max charges <input id="bd-region-maxcharges" type="number" min="0" max="9" value="${region.max_charges ?? 3}"></label>
      </div>
      <div>Lanes assigned: ${used.join(", ") || "none"}${missing.length ? ` · unassigned (rerolled in play): ${missing.join(", ")}` : " · all seven"}</div>
      <div class="admin-note">${shieldSub === "hexes"
        ? "Click hull hexes to add/remove them from this region; click a Shield Gen tile to set the power source."
        : "Click a region hex to assign the next lane (2-8). Click again to rotate its entry face; past the last face, the lane is cleared. Fewer than seven lanes is fine — unassigned numbers reroll. Tick the box to stack a second lane on a laned hex."}</div>`;
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
      ? "" : '<div class="admin-note">No steps yet — the track is empty.</div>';
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
        <label>stack <select data-f="stack">${META.action_stacks.map((stack) =>
          `<option ${step.stack === stack ? "selected" : ""}>${stack}</option>`).join("")}</select></label>
        <label>action <select data-f="action">
          <option ${step.action === "move" ? "selected" : ""}>move</option>
          <option ${step.action === "shoot" ? "selected" : ""}>shoot</option></select></label>`;
    } else if (step.kind === "breacher_link") {
      fields = `
        <label>core <select data-f="core"><option value="">—</option>${coreNumbers.map((number) =>
          `<option ${step.core === number ? "selected" : ""}>${number}</option>`).join("")}</select></label>
        <label>round ≥ <input data-f="round" type="number" min="1" max="99" value="${step.round ?? ""}" placeholder="—"></label>`;
    } else if (step.kind === "ability_trigger") {
      fields = `<label>name <input data-f="name" maxlength="80" value="${esc(step.name || "")}"></label>`;
    } else if (step.kind === "spawn_fleet") {
      const locations = META.spawn_locations || ["boss_front", "bauble", "fang"];
      const locationLabels = { boss_front: "front of boss", bauble: "current bauble", fang: "The Fang" };
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
    for (const region of design.shield_regions) {
      if (region.max_charges === undefined) region.max_charges = region.charges ?? 3;
      if (region.charges === undefined) region.charges = region.max_charges;
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
  function buildMarkup() {
    const transferTools = isAdmin ? `
        <span class="deck-set-sep">|</span>
        <button class="btn ghost small" id="bd-download">⬇ Download</button>
        <input id="bd-import-file" type="file" accept=".json,application/json">
        <button class="btn ghost small" id="bd-upload">⬆ Upload</button>` : "";
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
            <button class="btn ghost bd-mode" data-mode="shields">🛡 Shields &amp; Lanes</button>
            <button class="btn ghost bd-mode" data-mode="progression">📈 Progression</button>
            <button class="btn ghost bd-mode" data-mode="stacks">🗂 Action Stacks</button>
            <button class="btn ghost bd-mode" data-mode="behavior">⚙ Behavior</button>
            <button class="btn ghost bd-mode" data-mode="print">Print Sheets</button>
          </div>
          <button class="btn gold" id="bd-save">💾 Save design</button>
        </div>
        <div class="bd-grid">
          <div class="bd-board-wrap">
            <div id="bd-board" class="bd-board"></div>
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
                Right-click or use the eraser to remove. Shield Gens number a shield region;
                Firing Computers grant an attack and Fuel Tanks a move in their action stack;
                Cores anchor Breacher-stack abilities.</p>
            </div>
            <div id="bd-panel-shields" class="hidden">
              <h3 class="panel-sub">Shield regions</h3>
              <div class="bd-regionbar">
                <select id="bd-region-select"></select>
                <button class="btn ghost small" id="bd-region-add">＋ Region</button>
                <button class="btn ghost small" id="bd-region-del">✕</button>
              </div>
              <div class="bd-shieldsubs">
                <button class="btn ghost small bd-shieldsub active" data-sub="hexes">Protected Hexes</button>
                <button class="btn ghost small bd-shieldsub" data-sub="lanes">Damage Lanes</button>
              </div>
              <div id="bd-lane-tools" class="bd-lane-tools hidden">
                <label><input type="checkbox" id="bd-lane-stack"> Allow a second lane on a laned hex</label>
                <button class="btn ghost small" id="bd-lane-renumber">⇢ Renumber lanes left-to-right</button>
              </div>
              <div id="bd-region-info" class="bd-region-info"></div>
            </div>
            <div id="bd-panel-stacks" class="hidden">
              <h3 class="panel-sub">Action stacks</h3>
              <p class="admin-note">Each column is a boss action stack. Firing Computers,
                Fuel Tanks, and progression action links appear in the stack they feed —
                drag a card to another column to reassign it. Breacher links live in the
                StarBreach stack. The progression strip up top shows the track in order;
                drag a step onto another to reorder the track.</p>
              <p class="admin-note">Fleet actions (Behavior tab) are shown per column for
                reference.</p>
            </div>
            <div id="bd-panel-behavior" class="hidden">
              <h3 class="panel-sub">Boss behavior</h3>
              <label class="bd-field">Boss AI
                <select id="bd-boss-ai"><option value="hunter_killer">Hunter-Killer — close on the Prey, shoot the Prey</option></select>
              </label>
              <h3 class="panel-sub">Fleet craft</h3>
              <div class="bd-fleet-row">
                <label>Count <input id="bd-fleet-count" type="number" min="0" max="6"></label>
                <label>HP <input id="bd-fleet-hp" type="number" min="1" max="9"></label>
              </div>
              <div class="bd-fleet-row">
                <label>Type <select id="bd-fleet-kind"><option value="hunter_killer">Mini Hunter-Killer</option></select></label>
                <label>AI <select id="bd-fleet-ai"><option value="hunter_killer">Hunter-Killer</option></select></label>
              </div>
              <h3 class="panel-sub">Fleet actions per boss stage</h3>
              <p class="admin-note">Tick which actions the fleet (as a unit) takes at each boss action stage.</p>
              <table class="bd-fleet-actions" id="bd-fleet-actions">
                <tr><th>Stage</th><th>Move</th><th>Shoot</th></tr>
              </table>
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
                <label><input type="checkbox" data-print-opt="lanes" checked> Damage lane arrows</label>
                <label><input type="checkbox" data-print-opt="stacks" checked> Action stacks</label>
                <label><input type="checkbox" data-print-opt="stackLinks" checked> Action stack links to ship</label>
                <label><input type="checkbox" data-print-opt="components" checked> Component legend</label>
                <label><input type="checkbox" data-print-opt="progression" checked> Progression track</label>
                <label><input type="checkbox" data-print-opt="fleet" checked> Fleet and table aids</label>
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
      design.shield_regions.push({ number, hexes: [], generator: null, lanes: [], charges: 3, max_charges: 3 });
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
  let playerDesigner = null;
  function openPlayerDesigner() {
    let overlay = document.getElementById("player-bossdesigner-overlay");
    if (!overlay) {
      overlay = document.createElement("div");
      overlay.id = "player-bossdesigner-overlay";
      overlay.className = "bd-player-overlay";
      overlay.innerHTML = `
        <div class="bd-player-shell">
          <button class="btn ghost small bd-player-close" id="bd-player-close">✕ Back to Port</button>
          <div id="player-bossdesign"></div>
        </div>`;
      document.body.appendChild(overlay);
      overlay.querySelector("#bd-player-close").addEventListener("click", () => {
        overlay.classList.add("hidden");
      });
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
  }

  window.BossDesigner = { openPlayerDesigner };
})();
