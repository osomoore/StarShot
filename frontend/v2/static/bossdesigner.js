/* Boss Ship Designer admin tab.
 *
 * Self-contained: builds its own DOM inside #tab-bossdesign, talks only to
 * /api/v2/admin/boss-designs, and shares nothing with admin.js beyond the
 * generic tab-switching markup. Three edit modes over one SVG hex board:
 *   structure     — paint hull tiles (generic / shield gen / firing computer /
 *                   fuel tank / core)
 *   shields+lanes — per shield region: protected hexes, powering generator,
 *                   and the seven d8 damage lanes (rolls 2-8)
 *   progression   — progression triggers and the step track
 */
(function () {
  "use strict";

  const API = "/api/v2/admin/boss-designs";
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

  const root = () => document.getElementById("tab-bossdesign");
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

  function tileBadge(tile) {
    if (tile.type === "shield_gen") return "SG" + tile.number;
    if (tile.type === "core") return "◉" + tile.number;
    if (tile.type === "firing_computer") return "FC " + (STACK_SHORT[tile.stack] || tile.stack);
    if (tile.type === "fuel_tank") return "FT " + (STACK_SHORT[tile.stack] || tile.stack);
    return "";
  }

  function renderBoard() {
    const footprint = footprintSet();
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
          <title>(${q},${r})${tile ? " — " + tile.type.replace("_", " ") : ""}</title></polygon>
        ${extra}
        ${tile && tileBadge(tile) ? `<text x="${x}" y="${y + 3.6}" text-anchor="middle" class="bd-badge"
          fill="${isGen ? "#fff" : "#0a0f1e"}">${esc(tileBadge(tile))}</text>` : ""}
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

    // Damage lanes: number outside the entry face, arrow in, faint ray through the hull.
    let lanesSvg = "";
    for (const region of design.shield_regions) {
      const color = regionColor(region.number);
      const isActive = mode === "shields" && region.number === currentRegion;
      const opacity = mode === "shields" ? (isActive ? 1 : 0.25) : 0.7;
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
     face. Click again: same roll, next edge face. Past the last face: unassign. */
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
    const existing = region.lanes.find((lane) => lane.q === q && lane.r === r);
    if (existing) {
      const at = facings.indexOf(existing.facing);
      if (at >= 0 && at < facings.length - 1) {
        existing.facing = facings[at + 1];
      } else {
        region.lanes = region.lanes.filter((lane) => lane !== existing);
      }
      return;
    }
    const used = new Set(region.lanes.map((lane) => lane.roll));
    const next = META.lane_rolls.find((roll) => !used.has(roll));
    if (next === undefined) {
      setStatus("All seven lanes (2-8) are assigned — click an assigned hex to adjust or clear it.", false);
      return;
    }
    region.lanes.push({ roll: next, q, r, facing: facings[0] });
  }

  // ── panels ───────────────────────────────────────────────────────────────
  function renderModePanel() {
    el("bd-panel-structure").classList.toggle("hidden", mode !== "structure");
    el("bd-panel-shields").classList.toggle("hidden", mode !== "shields");
    el("bd-panel-progression").classList.toggle("hidden", mode !== "progression");
    el("bd-panel-behavior").classList.toggle("hidden", mode !== "behavior");
    root().querySelectorAll(".bd-mode").forEach((button) =>
      button.classList.toggle("active", button.dataset.mode === mode));
    if (mode === "shields") renderShieldPanel();
    if (mode === "progression") renderProgressionPanel();
    if (mode === "structure") renderStructurePanel();
    if (mode === "behavior") renderBehaviorPanel();
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
      <div>Lanes assigned: ${used.join(", ") || "none"}${missing.length ? ` · missing: ${missing.join(", ")}` : " · complete"}</div>
      <div class="admin-note">${shieldSub === "hexes"
        ? "Click hull hexes to add/remove them from this region; click a Shield Gen tile to set the power source."
        : "Click a region hex to assign the next lane (2-8). Click again to rotate its entry face; past the last face, the lane is cleared."}</div>`;
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
    }

    row.innerHTML = `
      <span class="bd-step-index">${index + 1}</span>
      <select data-f="kind">
        <option value="filler" ${step.kind === "filler" ? "selected" : ""}>Filler</option>
        <option value="action_link" ${step.kind === "action_link" ? "selected" : ""}>Action link</option>
        <option value="breacher_link" ${step.kind === "breacher_link" ? "selected" : ""}>Breacher link</option>
        <option value="ability_trigger" ${step.kind === "ability_trigger" ? "selected" : ""}>Ability trigger</option>
      </select>
      <span class="bd-step-fields">${fields}</span>
      <span class="bd-step-actions">
        <button class="btn ghost small" data-a="up" ${index === 0 ? "disabled" : ""}>↑</button>
        <button class="btn ghost small" data-a="down" ${index === design.progression.steps.length - 1 ? "disabled" : ""}>↓</button>
        <button class="btn ghost small" data-a="del">✕</button>
      </span>`;

    row.querySelector('[data-f="kind"]').addEventListener("change", (event) => {
      design.progression.steps[index] = defaultStep(event.target.value);
      markDirty();
      renderProgressionPanel();
    });
    row.querySelectorAll("[data-f]:not([data-f=kind])").forEach((node) => {
      node.addEventListener("change", () => {
        const field = node.dataset.f;
        if (field === "core" || field === "round") {
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

  function openDesign(document_) {
    design = document_;
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
    root().innerHTML = `
      <h2 class="panel-title">Boss Ship Designer</h2>
      <div class="bd-designbar">
        <select id="bd-design-select"></select>
        <button class="btn ghost small" id="bd-load">Open</button>
        <input id="bd-new-name" placeholder="New boss name…" maxlength="80">
        <button class="btn gold small" id="bd-new">＋ New design</button>
        <span class="deck-set-sep">|</span>
        <button class="btn ghost small" id="bd-download">⬇ Download</button>
        <input id="bd-import-file" type="file" accept=".json,application/json">
        <button class="btn ghost small" id="bd-upload">⬆ Upload</button>
        <span class="deck-set-sep">|</span>
        <button class="btn crimson small" id="bd-delete">🗑 Delete</button>
      </div>
      <div id="bd-editor" class="hidden">
        <div class="bd-topbar">
          <label>Name <input id="bd-name" maxlength="80"></label>
          <div class="bd-modes">
            <button class="btn ghost bd-mode active" data-mode="structure">⬡ Structure</button>
            <button class="btn ghost bd-mode" data-mode="shields">🛡 Shields &amp; Lanes</button>
            <button class="btn ghost bd-mode" data-mode="progression">📈 Progression</button>
            <button class="btn ghost bd-mode" data-mode="behavior">⚙ Behavior</button>
          </div>
          <button class="btn gold" id="bd-save">💾 Save design</button>
        </div>
        <div class="bd-grid">
          <div class="bd-board-wrap"><div id="bd-board" class="bd-board"></div></div>
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
              <div id="bd-region-info" class="bd-region-info"></div>
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
      });
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

    el("bd-step-add").addEventListener("click", () => {
      design.progression.steps.push(defaultStep("filler"));
      markDirty();
      renderProgressionPanel();
    });

    window.addEventListener("beforeunload", (event) => {
      if (dirty) event.preventDefault();
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
      setStatus("✘ " + error.message + " (sign in as the admin first)", false);
      booted = false; // retry on next tab visit
    }
  }

  // Lazy-boot when the tab is first opened (admin.js handles the show/hide).
  document.querySelectorAll('.admin-tab[data-tab="bossdesign"]').forEach((tab) => {
    tab.addEventListener("click", boot);
  });
})();
