/* StarDock — Player Ship Designer.
 *
 * Self-contained: builds its own DOM inside a host element and talks only to
 * its design API. Two instances exist:
 *   - player (full-screen overlay on the main app, /api/v2/my/ship-designs,
 *     capped library — players fly their creations in place of the base ship)
 *   - admin  (admin page tab, /api/v2/admin/ship-designs, global library),
 *     which also gets a player-design browse/clone/delete bar
 *
 * Ships are built on a radius-5 hex grid. A battle-ready ship places 1 Core,
 * 2 Life Supports, 1 Bone Room, 1 Docking Bay, and exactly 10 Engine /
 * Double Engine / Cannon / Double Cannon components bought with 15 Core
 * Component points (Double = 2 points) — those 10 components ARE the ship's
 * 10-card starting deck (Move 1 / Move 2 / Aim +1 / Aim +2). The six primary
 * damage lanes follow the Core automatically (at most 10 components may
 * armor them); the six secondary lanes (rolls 3/5/6/8/9/11) are placed by
 * the player and must each sever at least 2 components from the Core when
 * shot fully through. Every ship also picks exactly one special upgrade.
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
    const DIR_ARROWS = ["↘", "↗", "↑", "↖", "↙", "↓"];
    const SECONDARY_ROLLS = [3, 5, 6, 8, 9, 11];
    // primary lanes: roll -> travel direction from the Core's lines
    const PRIMARY_DIRS = { 1: 2, 7: 5, 4: 0, 12: 3, 2: 1, 10: 4 };

    let META = {
      grid_radius: 5,
      base_tile_total: 15,
      deck_size: 10,
      base_shields: 2,
      base_draw: 5,
      upgrades: ["shield", "draw", "defense", "aim", "points"],
      upgrade_extra_points: 2,
      max_tiles: 15,
      primary_lane_limit: 10,
      secondary_lane_min_severed: 2,
      core_points: 15,
      upgrade_defense_bonus: 1,
      upgrade_aim_bonus: 1,
      player_design_limit: 10,
    };

    const TILE_COSTS = { engine: 1, double_engine: 2, cannon: 1, double_cannon: 2 };
    const DECK_CARD_NAMES = {
      engine: "Move 1", double_engine: "Move 2", cannon: "Aim +1", double_cannon: "Aim +2",
    };

    const TILE_TOOLS = [
      { type: "core", label: "Core", icon: "⚙" },
      { type: "life_support", label: "Life Support", icon: "❀" },
      { type: "bone_room", label: "Bone Room", icon: "☠" },
      { type: "docking_bay", label: "Docking Bay", icon: "⚓" },
      { type: "engine", label: "Engine", icon: "🔥" },
      { type: "double_engine", label: "Dbl Engine", icon: "🚀" },
      { type: "cannon", label: "Cannon", icon: "☄" },
      { type: "double_cannon", label: "Dbl Cannon", icon: "💥" },
      { type: "structure", label: "Structure", icon: "🧱", onlyExpanded: true },
      { type: "erase", label: "Eraser", icon: "✕" },
    ];
    const TILE_FILL = {
      core: "#c96a4a", life_support: "#d9c46a", bone_room: "#a98fd1", docking_bay: "#c9a37a",
      engine: "#7fbf7f", double_engine: "#3f9e5f", cannon: "#d98c8c", double_cannon: "#c05050",
      structure: "#8a93a5",
      // legacy tiles from pre-overhaul designs (not placeable, still shown)
      weapon: "#d98c8c", crew: "#a98fd1", bay: "#c9a37a", shield_generator: "#7aa3d9",
      signal_jammer: "#6bffd8", targeting_sensors: "#ff7ad0",
    };
    const TILE_NOTES = {
      core: "Required — exactly 1. The primary damage lanes follow it. Ship dies when destroyed.",
      life_support: "Required — exactly 2. Ship dies when both are gone.",
      bone_room: "Required — exactly 1.",
      docking_bay: "Required — exactly 1.",
      engine: "1 Core point — adds a Move 1 card to your deck.",
      double_engine: "2 Core points — adds a Move 2 card to your deck.",
      cannon: "1 Core point — adds an Aim +1 card to your deck.",
      double_cannon: "2 Core points — adds an Aim +2 card to your deck.",
      structure: "Filler armor for ships above 15 tiles (admin setting).",
      erase: "Remove a tile.",
    };
    const UPGRADE_LABELS = () => ({
      shield: `+1 shield charge (${META.base_shields + 1} total)`,
      draw: `+1 card drawn each round (${META.base_draw + 1} total)`,
      defense: `+${META.upgrade_defense_bonus} Defense on all actions`,
      aim: `+${META.upgrade_aim_bonus} Aim on all actions`,
      points: `+${META.upgrade_extra_points} Core Component points`,
    });

    // ── state ────────────────────────────────────────────────────────────
    let booted = false;
    let designs = [];
    let playerDesigns = []; // admin only: everyone's designs
    let design = null;
    let dirty = false;
    let tool = "core";
    let laneRoll = null;      // secondary lane being placed (chip selected)
    let lanePick = null;      // {q, r} awaiting a direction choice
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
          detail = "Not Found — the running server predates StarDock; restart the server.";
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
    const R = () => META.grid_radius;
    const inGrid = (q, r) => Math.abs(q) <= R() && Math.abs(r) <= R() && Math.abs(q + r) <= R();

    function gridCells() {
      const cells = [];
      for (let q = -R(); q <= R(); q++) {
        for (let r = -R(); r <= R(); r++) {
          if (Math.abs(q + r) <= R()) cells.push([q, r]);
        }
      }
      return cells;
    }

    const tileAt = (q, r) => design.tiles.find((t) => t.q === q && t.r === r) || null;
    const countType = (type) => design.tiles.filter((t) => t.type === type).length;
    const coreTile = () => (countType("core") === 1 ? design.tiles.find((t) => t.type === "core") : null);

    function onPrimaryLane(q, r) {
      const core = coreTile();
      if (!core) return false;
      if (q === core.q && r === core.r) return false;
      return q === core.q || r === core.r || q + r === core.q + core.r;
    }

    const primaryLaneTiles = () => design.tiles.filter((t) => onPrimaryLane(t.q, t.r)).length;
    const corePointsSpent = () => design.tiles.reduce((sum, t) => sum + (TILE_COSTS[t.type] || 0), 0);
    const corePointsBudget = () =>
      META.core_points + (design.upgrade === "points" ? META.upgrade_extra_points : 0);
    const deckComponentCount = () => design.tiles.filter((t) => TILE_COSTS[t.type]).length;

    function deckCounts() {
      const counts = { engine: 0, double_engine: 0, cannon: 0, double_cannon: 0 };
      for (const t of design.tiles) if (counts[t.type] != null) counts[t.type] += 1;
      return counts;
    }

    /* Full grid line through (q, r) travelling DIRS[dir]; entry cell first. */
    function laneCells(q, r, dir) {
      const [dq, dr] = DIRS[((dir % 6) + 6) % 6];
      while (inGrid(q - dq, r - dr)) { q -= dq; r -= dr; }
      const cells = [];
      while (inGrid(q, r)) { cells.push([q, r]); q += dq; r += dr; }
      return cells;
    }

    /* Surviving non-core tiles cut off from the Core when every tile on
       `cells` is destroyed (mirrors lane_severed_count server-side). */
    function severedCount(cells) {
      const core = coreTile();
      if (!core) return 0;
      const laneSet = new Set(cells.map(([q, r]) => key(q, r)));
      if (laneSet.has(key(core.q, core.r))) return 0;
      const remaining = new Set(
        design.tiles.map((t) => key(t.q, t.r)).filter((k) => !laneSet.has(k))
      );
      const start = key(core.q, core.r);
      if (!remaining.has(start)) return 0;
      const seen = new Set([start]);
      const stack = [[core.q, core.r]];
      while (stack.length) {
        const [q, r] = stack.pop();
        for (const [dq, dr] of DIRS) {
          const k = key(q + dq, r + dr);
          if (remaining.has(k) && !seen.has(k)) { seen.add(k); stack.push([q + dq, r + dr]); }
        }
      }
      return remaining.size - seen.size;
    }

    const laneThroughCore = (cells) => {
      const core = coreTile();
      return !!core && cells.some(([q, r]) => q === core.q && r === core.r);
    };

    function placedLanes() {
      const lanes = {};
      for (const roll of SECONDARY_ROLLS) {
        const lane = (design.lanes || {})[String(roll)];
        if (lane) lanes[roll] = lane;
      }
      return lanes;
    }

    function laneProblems() {
      const bad = [];
      const seen = {};
      const lanes = placedLanes();
      for (const roll of Object.keys(lanes)) {
        const lane = lanes[roll];
        const cells = laneCells(lane.q, lane.r, lane.dir);
        const lineKey = key(cells[0][0], cells[0][1]) + "|" + (lane.dir % 6);
        if (seen[lineKey]) bad.push({ roll, reason: `same line as lane ${seen[lineKey]}` });
        seen[lineKey] = roll;
        if (laneThroughCore(cells)) bad.push({ roll, reason: "passes through the Core" });
        else if (coreTile() && severedCount(cells) < META.secondary_lane_min_severed) {
          bad.push({ roll, reason: `severs ${severedCount(cells)} (needs ${META.secondary_lane_min_severed})` });
        }
      }
      return bad;
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
      const structureNeeded = META.max_tiles - META.base_tile_total;
      const laneCount = Object.keys(placedLanes()).length;
      const badLanes = laneProblems();
      const items = [
        { ok: design.tiles.length === 0 || isConnected(), text: "All tiles contiguous" },
        { ok: countType("core") === 1, text: "Exactly 1 Core" },
        { ok: countType("life_support") === 2, text: "Exactly 2 Life Supports" },
        { ok: countType("bone_room") === 1, text: "1 Bone Room" },
        { ok: countType("docking_bay") === 1, text: "1 Docking Bay" },
        {
          ok: deckComponentCount() === META.deck_size,
          text: `${META.deck_size} Engine/Cannon components (${deckComponentCount()}/${META.deck_size})`,
        },
        {
          ok: corePointsSpent() <= corePointsBudget(),
          text: `Within ${corePointsBudget()} Core points (${corePointsSpent()})`,
        },
        {
          ok: design.tiles.length === META.max_tiles,
          text: `Exactly ${META.max_tiles} tiles (${design.tiles.length}/${META.max_tiles})`,
        },
      ];
      if (structureNeeded > 0) {
        items.push({
          ok: countType("structure") === structureNeeded,
          text: `${structureNeeded} Structure tiles (${countType("structure")})`,
        });
      }
      items.push(
        {
          ok: !coreTile() || primaryLaneTiles() <= META.primary_lane_limit,
          text: `≤ ${META.primary_lane_limit} components on primary lanes (${primaryLaneTiles()})`,
        },
        { ok: laneCount === 6, text: `All 6 secondary lanes placed (${laneCount}/6)` },
        {
          ok: badLanes.length === 0,
          text: badLanes.length
            ? "Lanes need fixing: " + badLanes.map((b) => `${b.roll} (${b.reason})`).join("; ")
            : `Each lane severs ≥ ${META.secondary_lane_min_severed} from the Core`,
        },
        { ok: !!design.upgrade, text: "Special upgrade chosen" },
      );
      return items;
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
            <span class="sd-lib-meta">${entry.points == null ? "?" : entry.points} Core pts · ${entry.tile_count} tiles
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
                <span class="sd-lib-meta">by ${esc(entry.owner_name)} · ${entry.points == null ? "?" : entry.points} Core pts
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
            <h2 class="panel-title">🚀 ${isAdmin ? "Global Ship Designs" : 'StarDock <span class="badge-alpha">ALPHA</span>'} ${limitNote}</h2>
            <div class="sd-head-actions">
              <input id="sd-new-name" type="text" maxlength="40" placeholder="New ship name">
              <button id="sd-new" class="btn gold small">＋ New design</button>
              <button id="sd-import" class="btn ghost small">⬆ Upload JSON</button>
              <input id="sd-import-file" type="file" accept="application/json" class="hidden">
            </div>
          </div>
          ${isAdmin ? "" : '<p class="tutorial-alpha-note">StarDock is still in Alpha — rules and balance may shift as it\'s tested. Bug reports and feedback are very welcome.</p>'}
          <div class="sd-blurb">Place <b>${META.max_tiles} contiguous tiles</b> — 1 Core, 2 Life Supports, 1 Bone Room,
            1 Docking Bay, and exactly <b>${META.deck_size} Engine/Cannon components</b> bought with
            <b>${META.core_points} Core Component points</b>: those components are your 10-card deck.
            Then place the <b>6 secondary damage lanes</b> and pick <b>1 special upgrade</b>.
            Battle-ready ships appear in the lobby's <b>Your Ship</b> picker.</div>
          <div class="sd-lib">${rows}</div>
          ${playerRows}
          <div id="sd-status" class="admin-status"></div>
        </div>`;

      el("sd-new").addEventListener("click", () => {
        const name = el("sd-new-name").value.trim();
        if (!name) { setStatus("Name your ship first.", false); return; }
        const id = name.toLowerCase().replace(/[^a-z0-9]+/g, "_").replace(/^_+|_+$/g, "").slice(0, 60) || "ship";
        design = { id, name, description: "", tiles: [], lanes: {}, upgrade: null };
        dirty = true;
        tool = "core";
        laneRoll = null;
        lanePick = null;
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
          design.lanes = design.lanes || {};
          dirty = false;
          laneRoll = null;
          lanePick = null;
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
              <div id="sd-points" class="sd-points"></div>
              <div id="sd-deck" class="sd-deck"></div>
              <div class="sd-tools" id="sd-tools"></div>
              <div id="sd-tool-note" class="sd-tool-note"></div>
              <div id="sd-lanes-panel" class="sd-lanes-panel"></div>
              <div id="sd-upgrade" class="sd-upgrade"></div>
              <div id="sd-checklist" class="sd-checklist"></div>
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
      el("sd-save").addEventListener("click", saveDesign);

      renderTools();
      renderLanePanel();
      renderUpgradePanel();
      renderMeters();
      renderProblems(problems || []);
      drawBoard();
    }

    function renderTools() {
      const host = el("sd-tools");
      const tools = TILE_TOOLS.filter((entry) => !entry.onlyExpanded || META.max_tiles > META.base_tile_total);
      host.innerHTML = tools.map((entry) => `
        <button class="sd-tool ${tool === entry.type && laneRoll == null ? "active" : ""}" data-tool="${entry.type}"
          style="${TILE_FILL[entry.type] ? `--tool-color:${TILE_FILL[entry.type]}` : ""}">
          <span class="sd-tool-icon">${entry.icon}</span>${entry.label}
        </button>`).join("");
      host.querySelectorAll(".sd-tool").forEach((button) => button.addEventListener("click", () => {
        tool = button.dataset.tool;
        laneRoll = null;
        lanePick = null;
        renderTools();
        renderLanePanel();
        drawBoard();
      }));
      el("sd-tool-note").textContent = laneRoll != null
        ? `Placing lane ${laneRoll}: click a hex, then pick the shot direction.`
        : (TILE_NOTES[tool] || "");
    }

    function renderLanePanel() {
      const host = el("sd-lanes-panel");
      if (!host) return;
      const lanes = placedLanes();
      const bad = Object.fromEntries(laneProblems().map((b) => [String(b.roll), b.reason]));
      host.innerHTML = `
        <div class="sd-lanes-title">Secondary damage lanes</div>
        <div class="sd-lane-chips">
          ${SECONDARY_ROLLS.map((roll) => {
            const placed = !!lanes[roll];
            const badReason = bad[String(roll)];
            const cls = laneRoll === roll ? "picking" : placed ? (badReason ? "bad" : "ok") : "";
            return `<span class="sd-lane-chip ${cls}" data-lane="${roll}"
              title="${placed ? (badReason ? esc(badReason) : "placed") : "not placed"}">${roll}${placed ? (badReason ? " ⚠" : " ✓") : ""}
              ${placed ? `<button class="sd-lane-clear" data-lane-clear="${roll}" title="Remove lane ${roll}">✕</button>` : ""}
            </span>`;
          }).join("")}
        </div>
        <div class="sd-lane-hint">${laneRoll != null
          ? `Click a hex the lane should pass through, then pick its direction.`
          : "Click a number, then place that lane on the board. Each lane must sever ≥ "
            + META.secondary_lane_min_severed + " components from the Core when shot fully through."}</div>`;
      host.querySelectorAll("[data-lane]").forEach((chip) => chip.addEventListener("click", (event) => {
        if (event.target.closest("[data-lane-clear]")) return;
        const roll = parseInt(chip.dataset.lane, 10);
        laneRoll = laneRoll === roll ? null : roll;
        lanePick = null;
        renderTools();
        renderLanePanel();
        drawBoard();
      }));
      host.querySelectorAll("[data-lane-clear]").forEach((button) => button.addEventListener("click", (event) => {
        event.stopPropagation();
        delete design.lanes[String(button.dataset.laneClear)];
        markDirty();
        renderLanePanel();
        renderMeters();
        drawBoard();
      }));
    }

    function renderUpgradePanel() {
      const host = el("sd-upgrade");
      if (!host) return;
      const labels = UPGRADE_LABELS();
      host.innerHTML = `
        <div class="sd-lanes-title">Special upgrade — choose 1</div>
        ${META.upgrades.map((upgrade) => `
          <label class="sd-upgrade-row">
            <input type="radio" name="sd-upgrade-pick" value="${upgrade}" ${design.upgrade === upgrade ? "checked" : ""}>
            ${esc(labels[upgrade] || upgrade)}
          </label>`).join("")}`;
      host.querySelectorAll("input[name=sd-upgrade-pick]").forEach((radio) => radio.addEventListener("change", () => {
        design.upgrade = radio.value;
        markDirty();
        renderMeters();
      }));
    }

    function renderMeters() {
      const spent = corePointsSpent();
      const budget = corePointsBudget();
      const counts = deckCounts();
      const over = spent > budget;
      el("sd-points").innerHTML = `
        <div class="sd-points-total ${over ? "over" : ""}">${spent} / ${budget} Core points</div>
        <div class="sd-points-rows">
          <span>Deck ${deckComponentCount()}/${META.deck_size} components</span>
          <span>Primary lanes ${primaryLaneTiles()}/${META.primary_lane_limit}</span>
          <span>Tiles ${design.tiles.length}/${META.max_tiles}</span>
        </div>`;
      const cards = [
        ["engine", counts.engine], ["double_engine", counts.double_engine],
        ["cannon", counts.cannon], ["double_cannon", counts.double_cannon],
      ].filter(([, n]) => n > 0);
      el("sd-deck").innerHTML = `
        <div class="sd-lanes-title">Starting deck preview (${deckComponentCount()}/${META.deck_size} cards)</div>
        ${cards.length
          ? cards.map(([type, n]) => `<div class="sd-deck-row">${n} × ${DECK_CARD_NAMES[type]}</div>`).join("")
          : '<div class="sd-deck-row sd-empty-deck">Place Engines and Cannons to build your deck.</div>'}`;
      el("sd-checklist").innerHTML = checklist().map((item) =>
        `<div class="sd-check ${item.ok ? "ok" : ""}">${item.ok ? "✔" : "○"} ${esc(item.text)}</div>`).join("");
      renderLanePanel();
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

    /* Marker (number + arrow) at a lane's entry edge. */
    function laneMarkerSvg(roll, cells, color, tooltip) {
      const first = cells[0];
      const second = cells[1] || cells[0];
      const [fx, fy] = xy(first[0], first[1]);
      const [sx, sy] = xy(second[0], second[1]);
      let dx = sx - fx, dy = sy - fy;
      if (!dx && !dy) { dx = 0; dy = 1; }
      const len = Math.hypot(dx, dy) || 1;
      const nx = dx / len, ny = dy / len;
      const labelX = fx - nx * SIZE * 2.0, labelY = fy - ny * SIZE * 2.0;
      const tipX = fx - nx * SIZE * 1.0, tipY = fy - ny * SIZE * 1.0;
      return `<g opacity="0.95"><title>${esc(tooltip)}</title>
        <text x="${labelX}" y="${labelY + 6}" text-anchor="middle" font-size="17"
          fill="${color}" font-family="Pirata One">${roll}</text>
        <line x1="${labelX + nx * 10}" y1="${labelY + ny * 10}" x2="${tipX}" y2="${tipY}"
          stroke="${color}" stroke-width="1.4" marker-end="url(#sdLaneArrow)"/></g>`;
    }

    function drawBoard() {
      const svg = el("sd-board");
      if (!svg) return;
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
      const laneHover = new Set();
      if (laneRoll != null && lanePick) {
        // highlight nothing extra; direction buttons carry the preview
      }
      let body = "";
      for (const [q, r] of cells) {
        const [x, y] = xy(q, r);
        const tile = tileAt(q, r);
        const fill = tile ? (TILE_FILL[tile.type] || "#888") : "rgba(150,160,190,0.10)";
        const axis = tile && onPrimaryLane(q, r);
        body += `<polygon class="sd-cell" data-q="${q}" data-r="${r}"
            points="${hexPoints(x, y, SIZE - 1.6)}" fill="${fill}"
            stroke="${axis ? "#ffd75e" : "#39435f"}" stroke-width="${axis ? 2.4 : 1.4}">
            <title>(${q},${r})${tile ? " — " + (toolMeta[tile.type]?.label || tile.type) + (axis ? " (on a primary lane)" : "") : ""}</title>
          </polygon>`;
        if (tile) {
          body += `<text x="${x}" y="${y + 7}" text-anchor="middle" font-size="20" pointer-events="none">${toolMeta[tile.type]?.icon || "▦"}</text>`;
        }
      }

      if (showLanes) {
        const core = coreTile();
        if (core) {
          for (const roll of Object.keys(PRIMARY_DIRS)) {
            const cellsOnLine = laneCells(core.q, core.r, PRIMARY_DIRS[roll]);
            const hits = cellsOnLine.filter(([q, r]) => tileAt(q, r)).length;
            body += laneMarkerSvg(roll, cellsOnLine, "#ffd75e",
              `Primary lane ${roll}: ${hits} tile(s) — contains the Core`);
          }
        }
        const lanes = placedLanes();
        const bad = Object.fromEntries(laneProblems().map((b) => [String(b.roll), b.reason]));
        for (const roll of Object.keys(lanes)) {
          const lane = lanes[roll];
          const cellsOnLine = laneCells(lane.q, lane.r, lane.dir);
          const hits = cellsOnLine.filter(([q, r]) => tileAt(q, r)).length;
          const badReason = bad[String(roll)];
          const severed = severedCount(cellsOnLine);
          body += laneMarkerSvg(roll, cellsOnLine, badReason ? "#ff8d7a" : "#8fd7ff",
            `Lane ${roll}: ${hits} tile(s), severs ${severed}${badReason ? " — " + badReason : ""}`);
        }
      }

      // direction picker for a pending lane placement
      if (laneRoll != null && lanePick) {
        const [px, py] = xy(lanePick.q, lanePick.r);
        body += `<circle cx="${px}" cy="${py}" r="${SIZE * 0.55}" fill="none" stroke="#8fd7ff" stroke-width="2.5"/>`;
        for (let dir = 0; dir < 6; dir++) {
          const [dq, dr] = DIRS[dir];
          const [nx2, ny2] = xy(lanePick.q + dq, lanePick.r + dr);
          const bx = px + (nx2 - px) * 0.62, by = py + (ny2 - py) * 0.62;
          body += `<g class="sd-dir-pick" data-dir="${dir}" style="cursor:pointer">
            <circle cx="${bx}" cy="${by}" r="15" fill="rgba(20,30,60,0.92)" stroke="#8fd7ff" stroke-width="1.6"/>
            <text x="${bx}" y="${by + 6}" text-anchor="middle" font-size="16" fill="#8fd7ff" pointer-events="none">${DIR_ARROWS[dir]}</text>
            <title>Lane ${laneRoll} travelling ${DIR_ARROWS[dir]}</title>
          </g>`;
        }
      }

      svg.innerHTML = `<defs><marker id="sdLaneArrow" markerWidth="7" markerHeight="7" refX="5" refY="2.5" orient="auto">
        <polygon points="0 0, 6 2.5, 0 5" fill="#e8e0cc"/></marker></defs>${body}`;

      svg.querySelectorAll(".sd-cell").forEach((cell) => cell.addEventListener("click", () => {
        const q = parseInt(cell.dataset.q, 10), r = parseInt(cell.dataset.r, 10);
        if (laneRoll != null) {
          lanePick = { q, r };
          drawBoard();
        } else {
          paintCell(q, r);
        }
      }));
      svg.querySelectorAll(".sd-dir-pick").forEach((button) => button.addEventListener("click", () => {
        const dir = parseInt(button.dataset.dir, 10);
        const cellsOnLine = laneCells(lanePick.q, lanePick.r, dir);
        if (laneThroughCore(cellsOnLine)) {
          setStatus("That line passes through the Core — it is already a primary lane.", false);
          return;
        }
        design.lanes[String(laneRoll)] = { q: cellsOnLine[0][0], r: cellsOnLine[0][1], dir };
        markDirty();
        lanePick = null;
        // auto-advance to the next unplaced lane
        const lanes = placedLanes();
        laneRoll = SECONDARY_ROLLS.find((roll) => !lanes[roll]) ?? null;
        renderTools();
        renderMeters();
        drawBoard();
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
        design.lanes = design.lanes || {};
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
          <div class="bd-player-toprow">
            <button class="btn ghost small bd-player-close" id="sd-player-close">✕ Back to Port</button>
            <button class="btn ghost small" id="sd-player-help">❓ Help</button>
          </div>
          <div id="player-shipdesign"></div>
        </div>`;
      document.body.appendChild(overlay);
      overlay.querySelector("#sd-player-close").addEventListener("click", () => {
        overlay.classList.add("hidden");
        document.dispatchEvent(new CustomEvent("shipdesigner-closed"));
      });
      overlay.querySelector("#sd-player-help").addEventListener("click", () => showHowto());
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

  const LS_HOWTO = "ss_shipdesigner_howto_seen2";
  function showHowto() {
    const howto = document.createElement("div");
    howto.className = "overlay bd-howto-overlay";
    howto.innerHTML = `
      <div class="picker">
        <h3>🚀 StarDock <span class="badge-alpha">ALPHA</span> — how it works</h3>
        <p class="tutorial-alpha-note">StarDock is still in Alpha — rules and balance may shift as it's tested. Bug reports and feedback are very welcome.</p>
        <div class="tutorial-steps">
          <div><b>1.</b> Place <b>15 contiguous tiles</b>: 1 Core, 2 Life Supports, 1 Bone Room, 1 Docking Bay,
            and exactly <b>10 Engine/Cannon components</b>.</div>
          <div><b>2.</b> Those 10 components are your <b>starting deck</b>, bought with <b>15 Core Component points</b>:
            Engine = Move 1 (1 pt), Double Engine = Move 2 (2 pts), Cannon = Aim +1 (1 pt), Double Cannon = Aim +2 (2 pts).</div>
          <div><b>3.</b> The 6 gold <b>primary damage lanes</b> follow the Core — at most 10 components may sit on them.
            Place the 6 blue <b>secondary lanes</b> yourself; each must sever at least 2 components from the Core if shot fully through.</div>
          <div><b>4.</b> Pick <b>1 special upgrade</b>: +1 shield, +1 card draw, flat Defense, flat Aim, or +2 Core points.</div>
          <div><b>5.</b> Save a battle-ready design, then choose it as <b>Your Ship</b> when creating or joining a raid.</div>
        </div>
        <button class="btn gold picker-cancel" id="sd-howto-ok">Got it</button>
      </div>`;
    document.body.appendChild(howto);
    howto.querySelector("#sd-howto-ok").addEventListener("click", () => howto.remove());
  }
  function maybeShowHowto() {
    try { if (localStorage.getItem(LS_HOWTO)) return; localStorage.setItem(LS_HOWTO, "1"); } catch (err) { return; }
    showHowto();
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

  window.ShipDesigner = { openPlayerDesigner, createShipDesigner, showHowto };
})();
