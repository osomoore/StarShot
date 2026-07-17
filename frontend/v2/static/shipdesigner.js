/* Player Ship Designer.
 *
 * Self-contained: builds its own DOM inside a host element and talks only to
 * its design API. Two instances exist:
 *   - player (full-screen overlay on the main app, /api/v2/my/ship-designs,
 *     capped library — players fly their creations in place of the base ship)
 *   - admin  (admin page tab, /api/v2/admin/ship-designs, global library),
 *     which also gets a player-design browse/clone/delete bar
 *
 * Ships are built on a radius-2 hex grid (19 spaces) against a 19-point
 * budget: 1/shield charge (0-3), 1/base card draw (3-6), 1 per non-core tile
 * on the three axes through the Core (its armor), 1 per Signal Jammer
 * (+2 defense, max 2), 1 per Targeting Sensors (+2 Aim, max 2). A
 * battle-ready ship places exactly 15 tiles including 1 Core and 2 Life
 * Supports, all connected. The 12 damage lanes are derived automatically
 * from the Core position and previewed live around the board.
 */
(function () {
  "use strict";

  function createShipDesigner(config) {
    const API = config.apiBase;
    const isAdmin = !!config.isAdmin;
    const root = config.root;
    const SQ = Math.sqrt(3);
    const SIZE = 34; // hex circumradius in svg units
    const DIRS = [[1, 0], [1, -1], [0, -1], [-1, 0], [-1, 1], [0, 1]];

    let META = {
      grid_radius: 2,
      point_budget: 19,
      max_tiles: 15,
      min_shields: 0,
      max_shields: 3,
      min_draw: 3,
      max_draw: 6,
      max_signal_jammers: 2,
      max_targeting_sensors: 2,
      player_design_limit: 10,
    };

    const TILE_TOOLS = [
      { type: "weapon", label: "Ion Cannon", icon: "☄" },
      { type: "engine", label: "Engine", icon: "🔥" },
      { type: "crew", label: "Crew", icon: "☠" },
      { type: "bay", label: "Docking Bay", icon: "⚓" },
      { type: "shield_generator", label: "Shield Gen", icon: "🛡" },
      { type: "life_support", label: "Life Support", icon: "❀" },
      { type: "core", label: "Core", icon: "⚙" },
      { type: "signal_jammer", label: "Sig. Jammer", icon: "📡" },
      { type: "targeting_sensors", label: "Targeting", icon: "🎯" },
      { type: "erase", label: "Eraser", icon: "✕" },
    ];
    const TILE_FILL = {
      weapon: "#d98c8c", shield_generator: "#7aa3d9", crew: "#a98fd1",
      core: "#c96a4a", engine: "#7fbf7f", life_support: "#d9c46a",
      bay: "#c9a37a", signal_jammer: "#6bffd8", targeting_sensors: "#ff7ad0",
    };
    const TILE_NOTES = {
      core: "Required — exactly 1. Ship dies when destroyed.",
      life_support: "Required — exactly 2. Ship dies when both are gone.",
      signal_jammer: "+2 defense while intact. 1 point. Max 2.",
      targeting_sensors: "+2 Aim while intact. 1 point. Max 2.",
    };

    // ── state ────────────────────────────────────────────────────────────
    let booted = false;
    let designs = [];
    let playerDesigns = []; // admin only: everyone's designs
    let design = null;
    let dirty = false;
    let tool = "weapon";
    let showLanes = true;

    // ── tiny helpers ─────────────────────────────────────────────────────
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
          detail = "Not Found — the running server predates the Ship Designer; restart the server.";
        }
        throw new Error(detail);
      }
      return payload;
    }

    const el = (id) => root().querySelector("#" + id);

    function setStatus(message, ok) {
      const node = el("sd-status");
      if (!node) return;
      node.textContent = message || "";
      node.className = "admin-status " + (ok ? "ok" : "err");
    }

    function markDirty() {
      dirty = true;
      el("sd-save")?.classList.add("attention");
    }

    // ── grid / rules math (mirrors backend player_ships.py) ──────────────
    function gridCells() {
      const cells = [];
      const R = META.grid_radius;
      for (let q = -R; q <= R; q++) {
        for (let r = -R; r <= R; r++) {
          if (Math.abs(q + r) <= R) cells.push([q, r]);
        }
      }
      return cells;
    }

    const tileAt = (q, r) => design.tiles.find((t) => t.q === q && t.r === r) || null;
    const countType = (type) => design.tiles.filter((t) => t.type === type).length;
    const coreTile = () => (countType("core") === 1 ? design.tiles.find((t) => t.type === "core") : null);

    function coreArmorCount() {
      const core = coreTile();
      if (!core) return 0;
      return design.tiles.filter((t) =>
        !(t.q === core.q && t.r === core.r)
        && (t.q === core.q || t.r === core.r || t.q + t.r === core.q + core.r)
      ).length;
    }

    function onCoreAxis(q, r) {
      const core = coreTile();
      if (!core) return false;
      if (q === core.q && r === core.r) return false;
      return q === core.q || r === core.r || q + r === core.q + core.r;
    }

    function pointsBreakdown() {
      const breakdown = {
        shields: design.shields, draw: design.draw, core_armor: coreArmorCount(),
        signal_jammers: countType("signal_jammer"), targeting_sensors: countType("targeting_sensors"),
      };
      breakdown.total = breakdown.shields + breakdown.draw + breakdown.core_armor
        + breakdown.signal_jammers + breakdown.targeting_sensors;
      return breakdown;
    }

    function isConnected() {
      const cells = new Set(design.tiles.map((t) => key(t.q, t.r)));
      if (!cells.size) return true;
      const start = design.tiles[0];
      const seen = new Set([key(start.q, start.r)]);
      const stack = [[start.q, start.r]];
      while (stack.length) {
        const [q, r] = stack.pop();
        for (const [dq, dr] of DIRS) {
          const k = key(q + dq, r + dr);
          if (cells.has(k) && !seen.has(k)) { seen.add(k); stack.push([q + dq, r + dr]); }
        }
      }
      return seen.size === cells.size;
    }

    function checklist() {
      const breakdown = pointsBreakdown();
      return [
        { ok: countType("core") === 1, text: "Exactly 1 Core" },
        { ok: countType("life_support") === 2, text: "Exactly 2 Life Supports" },
        { ok: design.tiles.length === META.max_tiles, text: `Exactly ${META.max_tiles} tiles (${design.tiles.length}/${META.max_tiles})` },
        { ok: design.tiles.length === 0 || isConnected(), text: "Hull fully connected" },
        { ok: countType("signal_jammer") <= META.max_signal_jammers, text: `Signal Jammers ≤ ${META.max_signal_jammers}` },
        { ok: countType("targeting_sensors") <= META.max_targeting_sensors, text: `Targeting Sensors ≤ ${META.max_targeting_sensors}` },
        { ok: breakdown.total <= META.point_budget, text: `Within ${META.point_budget} points (${breakdown.total})` },
      ];
    }

    /* The 12 auto lanes: full grid lines with travel directions, mirroring
       generate_damage_lanes() server-side. Returns {roll: {cells, dir}}. */
    function laneLines() {
      const core = coreTile();
      if (!core) return null;
      const cq = core.q, cr = core.r;
      const cells = gridCells();
      const line = (filter, axisKey, reverse) => {
        const found = cells.filter(filter);
        found.sort((a, b) => (axisKey(a) - axisKey(b)) * (reverse ? -1 : 1));
        return found;
      };
      const byQ = (c) => c[0], byR = (c) => c[1];
      return {
        1: line((c) => c[0] === cq, byR, true),
        7: line((c) => c[0] === cq, byR, false),
        4: line((c) => c[1] === cr, byQ, false),
        12: line((c) => c[1] === cr, byQ, true),
        2: line((c) => c[0] + c[1] === cq + cr, byQ, false),
        10: line((c) => c[0] + c[1] === cq + cr, byQ, true),
        5: line((c) => c[1] === cr - 1, byQ, false),
        11: line((c) => c[1] === cr - 1, byQ, true),
        3: line((c) => c[0] + c[1] === cq + cr - 1, byQ, false),
        9: line((c) => c[0] + c[1] === cq + cr - 1, byQ, true),
        6: line((c) => c[0] === cq - 1, byR, false),
        8: line((c) => c[0] === cq + 1, byR, false),
      };
    }

    // ── library view ─────────────────────────────────────────────────────
    async function refreshList() {
      const data = await call("");
      designs = data.designs || [];
      if (data.meta) META = { ...META, ...data.meta };
      if (isAdmin) {
        try {
          const mine = await fetch("/api/v2/admin/player-ship-designs", { credentials: "same-origin" });
          playerDesigns = mine.ok ? (await mine.json()).designs || [] : [];
        } catch (err) { playerDesigns = []; }
      }
    }

    function renderLibrary() {
      const limitNote = isAdmin ? "" :
        `<span class="sd-limit">${designs.length}/${META.player_design_limit} designs</span>`;
      const rows = designs.map((entry) => `
        <div class="sd-lib-row">
          <div class="sd-lib-name">
            <b>${esc(entry.name)}</b>
            <span class="sd-lib-meta">${entry.points == null ? "?" : entry.points} pts · ${entry.tile_count} tiles
              ${entry.valid ? '<span class="sd-ok">battle-ready</span>' : '<span class="sd-bad">incomplete</span>'}
              ${entry.conflict_of ? `<span class="sd-bad">(older copy of ${esc(entry.conflict_of)})</span>` : ""}
            </span>
          </div>
          <div class="sd-lib-actions">
            <button class="btn ghost small" data-open="${esc(entry.id)}">✏ Edit</button>
            <button class="btn ghost small" data-export="${esc(entry.id)}">⬇ Download</button>
            <button class="btn ghost small sd-danger" data-delete="${esc(entry.id)}">🗑</button>
          </div>
        </div>`).join("") || '<div class="sd-empty">No ship designs yet — name one and press ＋ New design.</div>';

      const playerRows = !isAdmin ? "" : `
        <h3 class="panel-sub">Player-made ships (all captains)</h3>
        <div class="sd-lib">
          ${playerDesigns.map((entry) => `
            <div class="sd-lib-row">
              <div class="sd-lib-name"><b>${esc(entry.name)}</b>
                <span class="sd-lib-meta">by ${esc(entry.owner_name)} · ${entry.points == null ? "?" : entry.points} pts
                  ${entry.valid ? '<span class="sd-ok">battle-ready</span>' : '<span class="sd-bad">incomplete</span>'}
                </span>
              </div>
              <div class="sd-lib-actions">
                <button class="btn ghost small" data-clone-owner="${entry.owner_id}" data-clone-id="${esc(entry.id)}">⤴ Clone to global</button>
                <button class="btn ghost small sd-danger" data-pdelete-owner="${entry.owner_id}" data-pdelete-id="${esc(entry.id)}">🗑</button>
              </div>
            </div>`).join("") || '<div class="sd-empty">No player designs yet.</div>'}
        </div>`;

      root().innerHTML = `
        <div class="sd-wrap">
          <div class="sd-head">
            <h2 class="panel-title">🚀 ${isAdmin ? "Global Ship Designs" : "My Ships"} ${limitNote}</h2>
            <div class="sd-head-actions">
              <input id="sd-new-name" type="text" maxlength="40" placeholder="New ship name">
              <button id="sd-new" class="btn gold small">＋ New design</button>
              <button id="sd-import" class="btn ghost small">⬆ Upload JSON</button>
              <input id="sd-import-file" type="file" accept="application/json" class="hidden">
            </div>
          </div>
          <div class="sd-blurb">Spend <b>${META.point_budget} points</b>: 1 per shield charge, 1 per card drawn,
            1 per tile armoring the Core's damage lanes, 1 per Jammer/Sensor. Place exactly
            <b>${META.max_tiles} tiles</b> — 1 Core, 2 Life Supports, the rest is up to you.
            Battle-ready ships appear in the lobby's <b>Your Ship</b> picker.</div>
          <div class="sd-lib">${rows}</div>
          ${playerRows}
          <div id="sd-status" class="admin-status"></div>
        </div>`;

      el("sd-new").addEventListener("click", () => {
        const name = el("sd-new-name").value.trim();
        if (!name) { setStatus("Name your ship first.", false); return; }
        const id = name.toLowerCase().replace(/[^a-z0-9]+/g, "_").replace(/^_+|_+$/g, "").slice(0, 60) || "ship";
        design = { id, name, description: "", shields: 2, draw: 5, tiles: [] };
        dirty = true;
        renderEditor();
      });
      el("sd-import").addEventListener("click", () => el("sd-import-file").click());
      el("sd-import-file").addEventListener("change", async (event) => {
        const file = event.target.files[0];
        if (!file) return;
        try {
          await call("/import", { method: "POST", body: await file.text() });
          await refreshList();
          renderLibrary();
          setStatus("Design uploaded.", true);
        } catch (err) { setStatus(err.message, false); }
      });
      root().querySelectorAll("[data-open]").forEach((button) => button.addEventListener("click", async () => {
        try {
          const data = await call("/" + encodeURIComponent(button.dataset.open));
          design = data.design;
          dirty = false;
          renderEditor(data.problems);
        } catch (err) { setStatus(err.message, false); }
      }));
      root().querySelectorAll("[data-export]").forEach((button) => button.addEventListener("click", () => {
        window.open(API + "/" + encodeURIComponent(button.dataset.export) + "/export", "_blank");
      }));
      root().querySelectorAll("[data-delete]").forEach((button) => button.addEventListener("click", async () => {
        if (!window.confirm("Delete this ship design? This cannot be undone.")) return;
        try {
          await call("/" + encodeURIComponent(button.dataset.delete), { method: "DELETE" });
          await refreshList();
          renderLibrary();
          setStatus("Design deleted.", true);
        } catch (err) { setStatus(err.message, false); }
      }));
      root().querySelectorAll("[data-clone-owner]").forEach((button) => button.addEventListener("click", async () => {
        try {
          const response = await fetch(
            `/api/v2/admin/player-ship-designs/${button.dataset.cloneOwner}/${encodeURIComponent(button.dataset.cloneId)}/clone`,
            { method: "POST", credentials: "same-origin" });
          if (!response.ok) throw new Error((await response.json()).detail || "Clone failed");
          await refreshList();
          renderLibrary();
          setStatus("Cloned into the global library — every captain can now fly it.", true);
        } catch (err) { setStatus(err.message, false); }
      }));
      root().querySelectorAll("[data-pdelete-owner]").forEach((button) => button.addEventListener("click", async () => {
        if (!window.confirm("Delete this player's ship design?")) return;
        try {
          const response = await fetch(
            `/api/v2/admin/player-ship-designs/${button.dataset.pdeleteOwner}/${encodeURIComponent(button.dataset.pdeleteId)}`,
            { method: "DELETE", credentials: "same-origin" });
          if (!response.ok) throw new Error((await response.json()).detail || "Delete failed");
          await refreshList();
          renderLibrary();
          setStatus("Player design removed.", true);
        } catch (err) { setStatus(err.message, false); }
      }));
    }

    // ── editor view ──────────────────────────────────────────────────────
    function renderEditor(problems) {
      root().innerHTML = `
        <div class="sd-wrap">
          <div class="sd-head">
            <button id="sd-back" class="btn ghost small">← Library</button>
            <input id="sd-name" type="text" maxlength="80" value="${esc(design.name)}">
            <div class="sd-head-actions">
              <button id="sd-save" class="btn gold small">💾 Save</button>
            </div>
          </div>
          <div class="sd-editor">
            <div class="sd-side">
              <div class="sd-stats">
                <div class="sd-stat"><span>🛡 Shields</span>
                  <span class="sd-ticker"><button id="sd-sh-down" class="btn ghost small">−</button>
                  <b id="sd-sh-val">${design.shields}</b>
                  <button id="sd-sh-up" class="btn ghost small">＋</button></span></div>
                <div class="sd-stat"><span>🃏 Card draw</span>
                  <span class="sd-ticker"><button id="sd-dr-down" class="btn ghost small">−</button>
                  <b id="sd-dr-val">${design.draw}</b>
                  <button id="sd-dr-up" class="btn ghost small">＋</button></span></div>
              </div>
              <div id="sd-points" class="sd-points"></div>
              <div id="sd-checklist" class="sd-checklist"></div>
              <div class="sd-tools" id="sd-tools"></div>
              <div id="sd-tool-note" class="sd-tool-note"></div>
              <label class="sd-lane-toggle"><input id="sd-lanes" type="checkbox" ${showLanes ? "checked" : ""}> Show damage lanes</label>
              <textarea id="sd-desc" rows="2" maxlength="500" placeholder="Description (optional)">${esc(design.description || "")}</textarea>
              <div id="sd-status" class="admin-status"></div>
              <div id="sd-problems" class="sd-problems"></div>
            </div>
            <div class="sd-board-wrap"><svg id="sd-board" xmlns="http://www.w3.org/2000/svg"></svg></div>
          </div>
        </div>`;

      el("sd-back").addEventListener("click", async () => {
        if (dirty && !window.confirm("Discard unsaved changes?")) return;
        design = null;
        await refreshList().catch(() => {});
        renderLibrary();
      });
      el("sd-name").addEventListener("input", () => { design.name = el("sd-name").value; markDirty(); });
      el("sd-desc").addEventListener("input", () => { design.description = el("sd-desc").value; markDirty(); });
      el("sd-lanes").addEventListener("change", () => { showLanes = el("sd-lanes").checked; drawBoard(); });
      const tick = (field, delta, min, max, node) => {
        design[field] = Math.min(max, Math.max(min, design[field] + delta));
        el(node).textContent = design[field];
        markDirty();
        renderMeters();
      };
      el("sd-sh-down").addEventListener("click", () => tick("shields", -1, META.min_shields, META.max_shields, "sd-sh-val"));
      el("sd-sh-up").addEventListener("click", () => tick("shields", 1, META.min_shields, META.max_shields, "sd-sh-val"));
      el("sd-dr-down").addEventListener("click", () => tick("draw", -1, META.min_draw, META.max_draw, "sd-dr-val"));
      el("sd-dr-up").addEventListener("click", () => tick("draw", 1, META.min_draw, META.max_draw, "sd-dr-val"));
      el("sd-save").addEventListener("click", saveDesign);

      renderTools();
      renderMeters();
      renderProblems(problems || []);
      drawBoard();
    }

    function renderTools() {
      const host = el("sd-tools");
      host.innerHTML = TILE_TOOLS.map((entry) => `
        <button class="sd-tool ${tool === entry.type ? "active" : ""}" data-tool="${entry.type}"
          style="${TILE_FILL[entry.type] ? `--tool-color:${TILE_FILL[entry.type]}` : ""}">
          <span class="sd-tool-icon">${entry.icon}</span>${entry.label}
        </button>`).join("");
      host.querySelectorAll(".sd-tool").forEach((button) => button.addEventListener("click", () => {
        tool = button.dataset.tool;
        renderTools();
      }));
      const note = TILE_NOTES[tool] || "Free to place — but tiles on the Core's axes cost 1 point each as Core armor.";
      el("sd-tool-note").textContent = note;
    }

    function renderMeters() {
      const breakdown = pointsBreakdown();
      const over = breakdown.total > META.point_budget;
      el("sd-points").innerHTML = `
        <div class="sd-points-total ${over ? "over" : ""}">${breakdown.total} / ${META.point_budget} points</div>
        <div class="sd-points-rows">
          <span>Shields ${breakdown.shields}</span><span>Draw ${breakdown.draw}</span>
          <span>Core armor ${breakdown.core_armor}</span>
          <span>Jammers ${breakdown.signal_jammers}</span><span>Sensors ${breakdown.targeting_sensors}</span>
        </div>`;
      el("sd-checklist").innerHTML = checklist().map((item) =>
        `<div class="sd-check ${item.ok ? "ok" : ""}">${item.ok ? "✔" : "○"} ${item.text}</div>`).join("");
    }

    function renderProblems(problems) {
      el("sd-problems").innerHTML = problems.length
        ? `<b>Not battle-ready yet:</b>${problems.map((p) => `<div>• ${esc(p)}</div>`).join("")}`
        : "";
    }

    // ── board ────────────────────────────────────────────────────────────
    function hexPoints(cx, cy, size) {
      const pts = [];
      for (let i = 0; i < 6; i++) {
        const angle = (Math.PI / 180) * (60 * i);
        pts.push(`${(cx + size * Math.cos(angle)).toFixed(2)},${(cy + size * Math.sin(angle)).toFixed(2)}`);
      }
      return pts.join(" ");
    }

    function drawBoard() {
      const svg = el("sd-board");
      const cells = gridCells();
      const pad = SIZE * 3.4;
      let minX = 0, maxX = 0, minY = 0, maxY = 0;
      for (const [q, r] of cells) {
        const [x, y] = xy(q, r);
        minX = Math.min(minX, x); maxX = Math.max(maxX, x);
        minY = Math.min(minY, y); maxY = Math.max(maxY, y);
      }
      svg.setAttribute("viewBox", `${minX - pad} ${minY - pad} ${maxX - minX + pad * 2} ${maxY - minY + pad * 2}`);

      const toolMeta = Object.fromEntries(TILE_TOOLS.map((t) => [t.type, t]));
      let body = "";
      for (const [q, r] of cells) {
        const [x, y] = xy(q, r);
        const tile = tileAt(q, r);
        const fill = tile ? TILE_FILL[tile.type] : "rgba(150,160,190,0.10)";
        const axis = tile && onCoreAxis(q, r);
        body += `<polygon class="sd-cell" data-q="${q}" data-r="${r}"
            points="${hexPoints(x, y, SIZE - 1.6)}" fill="${fill}"
            stroke="${axis ? "#ffd75e" : "#39435f"}" stroke-width="${axis ? 2.4 : 1.4}">
            <title>(${q},${r})${tile ? " — " + (toolMeta[tile.type]?.label || tile.type) + (axis ? " (core armor, 1 pt)" : "") : ""}</title>
          </polygon>`;
        if (tile) {
          body += `<text x="${x}" y="${y + 7}" text-anchor="middle" font-size="20" pointer-events="none">${toolMeta[tile.type]?.icon || ""}</text>`;
        }
      }

      if (showLanes) {
        const lanes = laneLines();
        if (lanes) {
          const occupied = new Set(design.tiles.map((t) => key(t.q, t.r)));
          for (const roll of Object.keys(lanes)) {
            const cellsOnLine = lanes[roll];
            if (!cellsOnLine.length) continue;
            const first = cellsOnLine[0];
            const second = cellsOnLine[1] || cellsOnLine[0];
            const [fx, fy] = xy(first[0], first[1]);
            const [sx, sy] = xy(second[0], second[1]);
            let dx = sx - fx, dy = sy - fy;
            if (!dx && !dy) { dx = 0; dy = 1; }
            const len = Math.hypot(dx, dy) || 1;
            const nx = dx / len, ny = dy / len;
            const isCoreLane = cellsOnLine.some(([q, r]) => {
              const core = coreTile();
              return core && q === core.q && r === core.r;
            });
            const hitNames = cellsOnLine.filter(([q, r]) => occupied.has(key(q, r))).length;
            const labelX = fx - nx * SIZE * 2.0, labelY = fy - ny * SIZE * 2.0;
            const tipX = fx - nx * SIZE * 1.0, tipY = fy - ny * SIZE * 1.0;
            body += `<g opacity="0.95"><title>Lane ${roll}: ${hitNames} tile(s)${isCoreLane ? " — contains the Core" : ""}</title>
              <text x="${labelX}" y="${labelY + 6}" text-anchor="middle" font-size="17"
                fill="${isCoreLane ? "#ffd75e" : "#e8e0cc"}" font-family="Pirata One">${roll}</text>
              <line x1="${labelX + nx * 10}" y1="${labelY + ny * 10}" x2="${tipX}" y2="${tipY}"
                stroke="${isCoreLane ? "#ffd75e" : "#e8e0cc"}" stroke-width="1.4" marker-end="url(#sdLaneArrow)"/></g>`;
          }
        }
      }

      svg.innerHTML = `<defs><marker id="sdLaneArrow" markerWidth="7" markerHeight="7" refX="5" refY="2.5" orient="auto">
        <polygon points="0 0, 6 2.5, 0 5" fill="#e8e0cc"/></marker></defs>${body}`;

      svg.querySelectorAll(".sd-cell").forEach((cell) => cell.addEventListener("click", () => {
        paintCell(parseInt(cell.dataset.q, 10), parseInt(cell.dataset.r, 10));
      }));
    }

    function paintCell(q, r) {
      const existing = tileAt(q, r);
      if (tool === "erase") {
        if (existing) {
          design.tiles = design.tiles.filter((t) => t !== existing);
          markDirty();
        }
      } else if (existing && existing.type === tool) {
        design.tiles = design.tiles.filter((t) => t !== existing); // toggle off
        markDirty();
      } else {
        if (tool === "core" && countType("core") >= 1 && (!existing || existing.type !== "core")) {
          // moving the core: remove the old one
          design.tiles = design.tiles.filter((t) => t.type !== "core");
        }
        if (!existing && design.tiles.length >= META.max_tiles) {
          setStatus(`A ship places at most ${META.max_tiles} tiles — erase one first.`, false);
          return;
        }
        if (existing) design.tiles = design.tiles.filter((t) => t !== existing);
        design.tiles.push({ q, r, type: tool });
        markDirty();
      }
      renderMeters();
      drawBoard();
    }

    async function saveDesign() {
      design.name = el("sd-name").value.trim() || design.name;
      try {
        const data = await call("", { method: "PUT", body: JSON.stringify(design) });
        design = data.design;
        dirty = false;
        el("sd-save").classList.remove("attention");
        renderProblems(data.problems || []);
        setStatus(data.problems && data.problems.length
          ? "Saved (not battle-ready yet — see the notes below)."
          : "Saved — battle-ready! Pick it as Your Ship in the lobby.", true);
      } catch (err) { setStatus(err.message, false); }
    }

    // ── boot ─────────────────────────────────────────────────────────────
    async function boot() {
      if (design) return; // keep an open editor
      try {
        await refreshList();
        renderLibrary();
        booted = true;
      } catch (err) {
        root().innerHTML = `<div class="sd-wrap"><div id="sd-status" class="admin-status err">${esc(err.message)}</div></div>`;
      }
    }

    return { boot };
  }

  // ── main app: full-screen "My Ships" overlay, opened from the lobby ─────
  let playerDesigner = null;
  function openPlayerDesigner() {
    let overlay = document.getElementById("player-shipdesigner-overlay");
    if (!overlay) {
      overlay = document.createElement("div");
      overlay.id = "player-shipdesigner-overlay";
      overlay.className = "bd-player-overlay";
      overlay.innerHTML = `
        <div class="bd-player-shell">
          <button class="btn ghost small bd-player-close" id="sd-player-close">✕ Back to Port</button>
          <div id="player-shipdesign"></div>
        </div>`;
      document.body.appendChild(overlay);
      overlay.querySelector("#sd-player-close").addEventListener("click", () => {
        overlay.classList.add("hidden");
        document.dispatchEvent(new CustomEvent("shipdesigner-closed"));
      });
    }
    overlay.classList.remove("hidden");
    if (!playerDesigner) {
      playerDesigner = createShipDesigner({
        apiBase: "/api/v2/my/ship-designs",
        root: () => document.getElementById("player-shipdesign"),
        isAdmin: false,
      });
    }
    playerDesigner.boot();
    maybeShowHowto();
  }

  const LS_HOWTO = "ss_shipdesigner_howto_seen";
  function maybeShowHowto() {
    try { if (localStorage.getItem(LS_HOWTO)) return; localStorage.setItem(LS_HOWTO, "1"); } catch (err) { return; }
    const howto = document.createElement("div");
    howto.className = "overlay bd-howto-overlay";
    howto.innerHTML = `
      <div class="picker">
        <h3>🚀 Ship Designer — how it works</h3>
        <div class="tutorial-steps">
          <div><b>1.</b> You have <b>19 points</b>: shield charges (1 each), base card draw (1 per card), Core armor (1 per tile on the Core's three axes), Signal Jammers and Targeting Sensors (1 each).</div>
          <div><b>2.</b> Place exactly <b>15 tiles</b> on the 19-space grid — 1 Core and 2 Life Supports are required, everything must stay connected. Four spaces stay empty.</div>
          <div><b>3.</b> The 12 damage lanes are drawn automatically from the Core's position — gold lanes hit the Core. Fewer tiles in those lanes = cheaper but riskier.</div>
          <div><b>4.</b> Save a battle-ready design, then choose it as <b>Your Ship</b> when creating or joining a raid. Download/upload JSON to share designs.</div>
        </div>
        <button class="btn gold picker-cancel" id="sd-howto-ok">Got it</button>
      </div>`;
    document.body.appendChild(howto);
    howto.querySelector("#sd-howto-ok").addEventListener("click", () => howto.remove());
  }

  // Admin page: lazy-boot inside the #tab-shipdesign tab.
  const adminTabs = document.querySelectorAll('.admin-tab[data-tab="shipdesign"]');
  if (adminTabs.length) {
    const adminDesigner = createShipDesigner({
      apiBase: "/api/v2/admin/ship-designs",
      root: () => document.getElementById("tab-shipdesign"),
      isAdmin: true,
    });
    adminTabs.forEach((tab) => tab.addEventListener("click", adminDesigner.boot));
  }

  window.ShipDesigner = { openPlayerDesigner, createShipDesigner };
})();
