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
      base_palette_limits: {
        core: 1, life_support: 2, bone_room: 1, docking_bay: 1,
        double_cannon: 2, cannon: 3, double_engine: 3, engine: 2,
      },
      upgrades: ["shield", "draw", "defense", "aim", "points"],
      upgrade_extra_points: 2,
      max_tiles: 15,
      primary_lane_limit: 10,
      secondary_lane_min_severed: 2,
      core_points: 15,
      upgrade_defense_bonus: 1,
      upgrade_aim_bonus: 1,
      player_design_limit: 10,
      bonus_components: [],
      available_reward_components: [],
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
      { type: "double_cannon", label: "Dbl Cannon", icon: "💥" },
      { type: "cannon", label: "Cannon", icon: "☄" },
      { type: "double_engine", label: "Dbl Engine", icon: "🚀" },
      { type: "engine", label: "Engine", icon: "🔥" },
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
    let playerDesigns = []; // admin only: current page of everyone's designs
    let playerSearch = "";
    let playerPage = 1;
    let playerTotal = 0;
    let playerTotalPages = 1;
    let selectedPlayerDesigns = new Set(); // "ownerId:designId" keys, admin only
    let playerSearchDebounce = null;
    let design = null;
    let dirty = false;
    let tool = "core";
    let laneRoll = null;      // secondary lane being placed (chip selected, advanced mode)
    let lanePick = null;      // {q, r} awaiting a direction choice
    let showLanes = true;
    let laneCycle = 0;        // which auto-generated lane arrangement is shown
    let advancedLanes = (() => {
      try { return localStorage.getItem("ss_stardock_adv_lanes") === "1"; } catch (err) { return false; }
    })();
    let printTone = "color";  // color | bw
    let printZoom = 1;        // ship-drawing scale multiplier (0.5 - 2.0)
    let printOptions = {
      lanes: true,
      laneList: true,
      coords: false,
      components: true,
      deck: true,
      checklist: true,
    };
    let boardPlacementWired = false;

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
    const paletteLimit = (type) => type === "structure"
      ? Math.max(0, META.max_tiles - META.base_tile_total)
      : (META.base_palette_limits || {})[type];
    const paletteRemaining = (type) => {
      const limit = paletteLimit(type);
      return Number.isFinite(limit) ? Math.max(0, limit - countType(type)) : null;
    };
    const coreTile = () => (countType("core") === 1 ? design.tiles.find((t) => t.type === "core") : null);

    function onPrimaryLane(q, r) {
      const core = coreTile();
      if (!core) return false;
      if (q === core.q && r === core.r) return false;
      return q === core.q || r === core.r || q + r === core.q + core.r;
    }

    const primaryLaneTiles = () => design.tiles.filter((t) => onPrimaryLane(t.q, t.r)).length;
    const bonusById = (id) => (META.bonus_components || []).find((entry) => entry.id === id) || null;
    const tileCost = (tile) => tile.type === "bonus_component"
      ? (bonusById(tile.reward_id)?.cost || 0) : (TILE_COSTS[tile.type] || 0);
    const corePointsSpent = () => design.tiles.reduce((sum, t) => sum + tileCost(t), 0);
    const corePointsBudget = () =>
      META.core_points + (design.upgrade === "points" ? META.upgrade_extra_points : 0);
    const deckComponentCount = () => design.tiles.filter((t) => TILE_COSTS[t.type] || t.type === "bonus_component").length;

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

    // ── auto lane placement ──────────────────────────────────────────────
    /* Mirror across the vertical axis through the Core (ships face "up"):
       relative (dq, dr) -> (-dq, dq + dr). Direction indexes map likewise. */
    const MIRROR_DIR = [4, 3, 2, 1, 0, 5];

    function mirrorCoord(q, r) {
      const core = coreTile();
      const dq = q - core.q, dr = r - core.r;
      return [core.q - dq, core.r + dq + dr];
    }

    function isShipSymmetric() {
      if (!coreTile()) return false;
      const coords = new Set(design.tiles.map((t) => key(t.q, t.r)));
      return design.tiles.every((t) => {
        const [mq, mr] = mirrorCoord(t.q, t.r);
        return coords.has(key(mq, mr));
      });
    }

    const laneKey = (cells, dir) => key(cells[0][0], cells[0][1]) + "|" + (((dir % 6) + 6) % 6);
    const primaryLaneId = (dir) => "p:" + (((dir % 6) + 6) % 6);
    const secondaryLaneId = (cells, dir) => "s:" + laneKey(cells, dir);

    function laneDisplayRoll(kind, defaultRoll, cells, dir) {
      const laneId = kind === "primary" ? primaryLaneId(dir) : secondaryLaneId(cells, dir);
      const n = parseInt((design.lane_numbers || {})[laneId], 10);
      return n >= 1 && n <= 12 ? n : parseInt(defaultRoll, 10);
    }

    /* Every legal secondary-lane placement on the current hull: full lines
       not through the Core that sever at least the required components. */
    function validLaneCandidates() {
      const seen = new Set();
      const candidates = [];
      for (const [q, r] of gridCells()) {
        for (let dir = 0; dir < 6; dir++) {
          const cells = laneCells(q, r, dir);
          const candidateKey = laneKey(cells, dir);
          if (seen.has(candidateKey)) continue;
          seen.add(candidateKey);
          if (laneThroughCore(cells)) continue;
          if (severedCount(cells) < META.secondary_lane_min_severed) continue;
          candidates.push({ q: cells[0][0], r: cells[0][1], dir, key: candidateKey, cells });
        }
      }
      return candidates;
    }

    function mirrorCandidateKey(candidate) {
      const [mq, mr] = mirrorCoord(candidate.q, candidate.r);
      const mdir = MIRROR_DIR[candidate.dir];
      return laneKey(laneCells(mq, mr, mdir), mdir);
    }

    /* Deterministic PRNG so arrangement #N is stable for a given hull. */
    function mulberry32(seed) {
      return function () {
        seed |= 0; seed = (seed + 0x6D2B79F5) | 0;
        let t = Math.imul(seed ^ (seed >>> 15), 1 | seed);
        t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
        return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
      };
    }

    function shuffled(list, rand) {
      const copy = list.slice();
      for (let i = copy.length - 1; i > 0; i--) {
        const j = Math.floor(rand() * (i + 1));
        [copy[i], copy[j]] = [copy[j], copy[i]];
      }
      return copy;
    }

    function laneEntriesForNumbering() {
      const core = coreTile();
      if (!core) return [];
      const entries = [];
      for (const defaultRoll of Object.keys(PRIMARY_DIRS)) {
        const dir = PRIMARY_DIRS[defaultRoll];
        const cells = laneCells(core.q, core.r, dir);
        entries.push({ id: primaryLaneId(dir), defaultRoll: parseInt(defaultRoll, 10), dir, cells, kind: "primary" });
      }
      for (const [defaultRoll, lane] of Object.entries(placedLanes())) {
        const dir = parseInt(lane.dir, 10);
        const cells = laneCells(lane.q, lane.r, dir);
        entries.push({ id: secondaryLaneId(cells, dir), defaultRoll: parseInt(defaultRoll, 10), dir, cells, kind: "secondary" });
      }
      return entries;
    }

    function laneEntryAngle(entry) {
      const firstHitIndex = entry.cells.findIndex(([q, r]) => !!tileAt(q, r));
      if (firstHitIndex < 0) return null;
      const first = entry.cells[firstHitIndex];
      const previous = entry.cells[firstHitIndex - 1] || first;
      const next = entry.cells[firstHitIndex + 1] || first;
      const [fx, fy] = xy(first[0], first[1]);
      const [px, py] = xy(previous[0], previous[1]);
      const [nx, ny] = xy(next[0], next[1]);
      let dx = nx - px, dy = ny - py;
      if (!dx && !dy) { dx = 0; dy = 1; }
      const len = Math.hypot(dx, dy) || 1;
      const bx = fx - (dx / len) * SIZE * 1.55;
      const by = fy - (dy / len) * SIZE * 1.55;
      const core = coreTile();
      const [cx, cy] = core ? xy(core.q, core.r) : [0, 0];
      const angle = Math.atan2(by - cy, bx - cx);
      return (angle + Math.PI / 2 + Math.PI * 2) % (Math.PI * 2);
    }

    function renumberLanesLinearly(options = {}) {
      const entries = laneEntriesForNumbering()
        .map((entry) => ({ ...entry, angle: laneEntryAngle(entry) }))
        .filter((entry) => entry.angle != null)
        .sort((a, b) => a.angle - b.angle || a.defaultRoll - b.defaultRoll);
      if (entries.length !== 12) {
        if (!options.silent) setStatus("Place all 6 secondary lanes before renumbering all 12 lane arrows.", false);
        return false;
      }
      design.lane_numbers = {};
      entries.forEach((entry, index) => {
        design.lane_numbers[entry.id] = index + 1;
      });
      laneRoll = null;
      lanePick = null;
      if (options.mark !== false) markDirty();
      if (options.render !== false) {
        renderTools();
        renderMeters();
        drawBoard();
      }
      if (!options.silent) setStatus("Lane arrows renumbered 1-12 clockwise from the nose.", true);
      return true;
    }

    /* Auto-place all six secondary lanes. Symmetric hulls get mirrored lane
       pairs on (3,9) / (5,11) / (6,8); each click cycles to a different
       valid arrangement. */
    function autoPlaceLanes() {
      if (!coreTile()) {
        setStatus("Place the Core first — lanes are judged by what they sever from it.", false);
        return;
      }
      const candidates = validLaneCandidates();
      const byKey = Object.fromEntries(candidates.map((c) => [c.key, c]));
      const rand = mulberry32(0x5D0C + laneCycle * 7919);
      const symmetric = isShipSymmetric();
      let chosen = null; // [{roll, cand}]

      if (symmetric) {
        const pairs = [];
        const used = new Set();
        for (const candidate of candidates) {
          if (used.has(candidate.key)) continue;
          const mirrorKey = mirrorCandidateKey(candidate);
          const partner = byKey[mirrorKey];
          if (!partner || mirrorKey === candidate.key || used.has(mirrorKey)) continue;
          used.add(candidate.key);
          used.add(mirrorKey);
          pairs.push([candidate, partner]);
        }
        if (pairs.length >= 3) {
          const picked = shuffled(pairs, rand).slice(0, 3);
          const rollPairs = [[3, 9], [5, 11], [6, 8]];
          chosen = [];
          picked.forEach((pair, index) => {
            const [a, b] = pair[0].key < pair[1].key ? pair : [pair[1], pair[0]];
            chosen.push({ roll: rollPairs[index][0], cand: a });
            chosen.push({ roll: rollPairs[index][1], cand: b });
          });
        }
      }
      if (!chosen) {
        if (candidates.length < 6) {
          setStatus(
            `Only ${candidates.length} legal lane placements exist — add tiles so more lines can sever `
            + `${META.secondary_lane_min_severed}+ components from the Core.`, false);
          return;
        }
        const picked = shuffled(candidates, rand).slice(0, 6);
        chosen = SECONDARY_ROLLS.map((roll, index) => ({ roll, cand: picked[index] }));
      }

      design.lanes = {};
      for (const { roll, cand } of chosen) {
        design.lanes[String(roll)] = { q: cand.q, r: cand.r, dir: cand.dir };
      }
      const renumbered = renumberLanesLinearly({ silent: true, render: false, mark: false });
      laneCycle += 1;
      laneRoll = null;
      lanePick = null;
      markDirty();
      renderTools();
      renderMeters();
      drawBoard();
      setStatus(
        `Lane arrangement #${laneCycle}${symmetric ? " (symmetric ship — mirrored lanes)" : ""}`
        + " — click again for another.", true);
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
          text: `${META.deck_size} deck components (${deckComponentCount()}/${META.deck_size})`,
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
      if (isAdmin) await refreshPlayerDesigns();
    }

    async function refreshPlayerDesigns() {
      try {
        const params = new URLSearchParams({ page: String(playerPage) });
        if (playerSearch) params.set("search", playerSearch);
        const mine = await fetch(`/api/v2/admin/player-ship-designs?${params}`, { credentials: "same-origin" });
        const payload = mine.ok ? await mine.json() : {};
        playerDesigns = payload.designs || [];
        playerTotal = payload.total || 0;
        playerTotalPages = payload.total_pages || 1;
        playerPage = payload.page || 1;
      } catch (err) {
        playerDesigns = [];
        playerTotal = 0;
        playerTotalPages = 1;
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

      const playerKey = (entry) => `${entry.owner_id}:${entry.id}`;
      const allOnPageSelected = playerDesigns.length > 0 && playerDesigns.every((entry) => selectedPlayerDesigns.has(playerKey(entry)));
      const playerRows = !isAdmin ? "" : `
        <h3 class="panel-sub">Player-made ships (all captains)</h3>
        <div class="sd-lib-toolbar">
          <input id="sd-player-search" type="text" placeholder="Search ship or owner name…" value="${esc(playerSearch)}">
          <span class="sd-lib-meta">${playerTotal} design${playerTotal === 1 ? "" : "s"}</span>
          <button id="sd-player-delete-selected" class="btn ghost small sd-danger" ${selectedPlayerDesigns.size ? "" : "disabled"}>
            🗑 Delete selected (${selectedPlayerDesigns.size})
          </button>
        </div>
        <div class="sd-lib">
          ${playerDesigns.length ? `
            <div class="sd-lib-row sd-lib-row-head">
              <label class="sd-lib-select"><input type="checkbox" id="sd-player-select-all" ${allOnPageSelected ? "checked" : ""}> Select all on page</label>
            </div>` : ""}
          ${playerDesigns.map((entry) => `
            <div class="sd-lib-row">
              <label class="sd-lib-select"><input type="checkbox" class="sd-player-select" data-key="${esc(playerKey(entry))}" ${selectedPlayerDesigns.has(playerKey(entry)) ? "checked" : ""}></label>
              <div class="sd-lib-name"><b>${esc(entry.name)}</b>
                <span class="sd-lib-meta">by ${esc(entry.owner_name)} · ${entry.points == null ? "?" : entry.points} Core pts
                  ${entry.valid ? '<span class="sd-ok">battle-ready</span>' : '<span class="sd-bad">incomplete</span>'}
                </span>
              </div>
              <div class="sd-lib-actions">
                <button class="btn ghost small" data-clone-owner="${entry.owner_id}" data-clone-id="${esc(entry.id)}">⤴ Clone to global</button>
                <button class="btn ghost small sd-danger" data-pdelete-owner="${entry.owner_id}" data-pdelete-id="${esc(entry.id)}">🗑</button>
              </div>
            </div>`).join("") || '<div class="sd-empty">No player designs found.</div>'}
        </div>
        <div class="sd-lib-pager">
          <button id="sd-player-prev" class="btn ghost small" ${playerPage <= 1 ? "disabled" : ""}>← Prev</button>
          <span class="sd-lib-meta">Page ${playerTotalPages ? playerPage : 0} of ${playerTotalPages}</span>
          <button id="sd-player-next" class="btn ghost small" ${playerPage >= playerTotalPages ? "disabled" : ""}>Next →</button>
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
          ${!isAdmin && META.is_campaign_admin ? `
            <div class="sd-bonus-palette">
              <h3 class="panel-sub">Admin campaign tools</h3>
              <select id="sd-admin-award-select">${(META.available_reward_components || []).map((entry) =>
                `<option value="${esc(entry.id)}">${esc(entry.name)}</option>`).join("")}</select>
              <button class="btn gold small" id="sd-admin-award">Award a new component</button>
            </div>` : ""}
          ${playerRows}
          <div id="sd-status" class="admin-status"></div>
        </div>`;

      el("sd-new").addEventListener("click", () => {
        const name = el("sd-new-name").value.trim();
        if (!name) { setStatus("Name your ship first.", false); return; }
        const id = name.toLowerCase().replace(/[^a-z0-9]+/g, "_").replace(/^_+|_+$/g, "").slice(0, 60) || "ship";
        design = { id, name, description: "", tiles: [], lanes: {}, lane_numbers: {}, upgrade: null };
        dirty = true;
        tool = "core";
        laneRoll = null;
        lanePick = null;
        renderEditor();
      });
      el("sd-import").addEventListener("click", () => el("sd-import-file").click());
      el("sd-admin-award")?.addEventListener("click", async () => {
        try {
          const response = await fetch("/api/v2/campaign/admin-award", {
            method: "POST", credentials: "same-origin", headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ component_id: el("sd-admin-award-select").value }),
          });
          const payload = await response.json();
          if (!response.ok) throw new Error(payload.detail || "Award failed");
          META.bonus_components = payload.components || [];
          renderLibrary();
          setStatus(payload.added ? "Component added to your bonus palette." : "You already own that component.", true);
        } catch (err) { setStatus(err.message, false); }
      });
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
          const response = await call("/" + encodeURIComponent(button.dataset.delete), { method: "DELETE" });
          if (response.restored_default) {
            window.alert(`At least you'll always have the ${response.default_ship.name}`);
          }
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
          selectedPlayerDesigns.delete(`${button.dataset.pdeleteOwner}:${button.dataset.pdeleteId}`);
          await refreshPlayerDesigns();
          renderLibrary();
          setStatus("Player design removed.", true);
        } catch (err) { setStatus(err.message, false); }
      }));
      if (isAdmin) {
        el("sd-player-search")?.addEventListener("input", (event) => {
          const value = event.target.value;
          clearTimeout(playerSearchDebounce);
          playerSearchDebounce = setTimeout(async () => {
            playerSearch = value;
            playerPage = 1;
            await refreshPlayerDesigns();
            renderLibrary();
          }, 300);
        });
        el("sd-player-prev")?.addEventListener("click", async () => {
          if (playerPage <= 1) return;
          playerPage -= 1;
          await refreshPlayerDesigns();
          renderLibrary();
        });
        el("sd-player-next")?.addEventListener("click", async () => {
          if (playerPage >= playerTotalPages) return;
          playerPage += 1;
          await refreshPlayerDesigns();
          renderLibrary();
        });
        el("sd-player-select-all")?.addEventListener("change", (event) => {
          for (const entry of playerDesigns) {
            const key = `${entry.owner_id}:${entry.id}`;
            if (event.target.checked) selectedPlayerDesigns.add(key);
            else selectedPlayerDesigns.delete(key);
          }
          renderLibrary();
        });
        root().querySelectorAll(".sd-player-select").forEach((checkbox) => checkbox.addEventListener("change", (event) => {
          if (event.target.checked) selectedPlayerDesigns.add(checkbox.dataset.key);
          else selectedPlayerDesigns.delete(checkbox.dataset.key);
          renderLibrary();
        }));
        el("sd-player-delete-selected")?.addEventListener("click", async () => {
          if (!selectedPlayerDesigns.size) return;
          if (!window.confirm(`Delete ${selectedPlayerDesigns.size} selected ship design(s)? This cannot be undone.`)) return;
          const items = Array.from(selectedPlayerDesigns, (key) => {
            const [ownerId, designId] = key.split(":");
            return { owner_id: Number(ownerId), design_id: designId };
          });
          try {
            const response = await fetch("/api/v2/admin/player-ship-designs/bulk-delete", {
              method: "POST", credentials: "same-origin", headers: { "Content-Type": "application/json" },
              body: JSON.stringify({ items }),
            });
            const payload = await response.json();
            if (!response.ok) throw new Error(payload.detail || "Bulk delete failed");
            selectedPlayerDesigns.clear();
            await refreshPlayerDesigns();
            renderLibrary();
            setStatus(`Deleted ${payload.deleted} design(s).`, true);
          } catch (err) { setStatus(err.message, false); }
        });
      }
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
              <div class="sd-view-tabs">
                <button id="sd-tab-edit" class="btn gold small" type="button">Edit Ship</button>
                <button id="sd-tab-print" class="btn ghost small" type="button">Print Sheets</button>
              </div>
              <div id="sd-points" class="sd-points"></div>
              <div id="sd-deck" class="sd-deck"></div>
              <div id="sd-edit-controls">
                <div class="sd-tools" id="sd-tools"></div>
                <div class="sd-bonus-palette" id="sd-bonus-tools"></div>
                <div id="sd-tool-note" class="sd-tool-note"></div>
                <div id="sd-lanes-panel" class="sd-lanes-panel"></div>
                <div id="sd-upgrade" class="sd-upgrade"></div>
              </div>
              <div id="sd-print-controls" class="sd-print-controls hidden">
                <div class="sd-lanes-title">Printable export</div>
                <label>Tone
                  <select id="sd-print-tone">
                    <option value="color" ${printTone === "color" ? "selected" : ""}>Color</option>
                    <option value="bw" ${printTone === "bw" ? "selected" : ""}>Black and white</option>
                  </select>
                </label>
                <label><input type="checkbox" data-sd-print-opt="lanes" ${printOptions.lanes ? "checked" : ""}> Damage lane arrows</label>
                <label><input type="checkbox" data-sd-print-opt="laneList" ${printOptions.laneList ? "checked" : ""}> Damage lane list</label>
                <label><input type="checkbox" data-sd-print-opt="coords" ${printOptions.coords ? "checked" : ""}> Hex coordinates</label>
                <label><input type="checkbox" data-sd-print-opt="components" ${printOptions.components ? "checked" : ""}> Component legend</label>
                <label><input type="checkbox" data-sd-print-opt="deck" ${printOptions.deck ? "checked" : ""}> Starting deck</label>
                <label><input type="checkbox" data-sd-print-opt="checklist" ${printOptions.checklist ? "checked" : ""}> Table checklist</label>
                <label>Ship scale
                  <input id="sd-print-zoom" type="range" min="50" max="200" step="5" value="${Math.round(printZoom * 100)}">
                  <span id="sd-print-zoom-value">${Math.round(printZoom * 100)}%</span>
                </label>
                <div class="sd-print-actions">
                  <button class="btn gold small" id="sd-print-download" type="button">Download SVG</button>
                  <button class="btn ghost small" id="sd-print-now" type="button">Print</button>
                </div>
              </div>
              <div id="sd-checklist" class="sd-checklist"></div>
              <label class="sd-lane-toggle"><input id="sd-lanes" type="checkbox" ${showLanes ? "checked" : ""}> Show damage lanes</label>
              <textarea id="sd-desc" rows="2" maxlength="500" placeholder="Description (optional)">${esc(design.description || "")}</textarea>
              <div id="sd-status" class="admin-status"></div>
              <div id="sd-problems" class="sd-problems"></div>
            </div>
            <div class="sd-board-wrap" id="sd-board-wrap"><svg id="sd-board" xmlns="http://www.w3.org/2000/svg"></svg></div>
            <div class="sd-print hidden" id="sd-print"></div>
          </div>
        </div>`;

      syncBoardPlacement();
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
      el("sd-tab-edit").addEventListener("click", () => setEditorMode("edit"));
      el("sd-tab-print").addEventListener("click", () => setEditorMode("print"));
      el("sd-print-tone").addEventListener("change", (event) => {
        printTone = event.target.value === "bw" ? "bw" : "color";
        renderPrintView();
      });
      root().querySelectorAll("[data-sd-print-opt]").forEach((box) => {
        box.addEventListener("change", () => {
          printOptions[box.dataset.sdPrintOpt] = !!box.checked;
          renderPrintView();
        });
      });
      el("sd-print-zoom").addEventListener("input", (event) => {
        printZoom = Math.max(0.5, Math.min(2, (parseInt(event.target.value, 10) || 100) / 100));
        el("sd-print-zoom-value").textContent = Math.round(printZoom * 100) + "%";
        renderPrintView();
      });
      el("sd-print-download").addEventListener("click", downloadPrintSheet);
      el("sd-print-now").addEventListener("click", printSheet);

      renderTools();
      renderLanePanel();
      renderUpgradePanel();
      renderMeters();
      renderProblems(problems || []);
      drawBoard();
    }

    function syncBoardPlacement() {
      const board = el("sd-board-wrap");
      const editor = root().querySelector(".sd-editor");
      const print = el("sd-print");
      const note = el("sd-tool-note");
      if (!board || !editor || !print || !note) return;
      const mobile = window.matchMedia && window.matchMedia("(max-width: 860px)").matches;
      if (mobile) {
        note.after(board);
      } else {
        editor.insertBefore(board, print);
      }
      if (!boardPlacementWired) {
        boardPlacementWired = true;
        window.addEventListener("resize", syncBoardPlacement);
      }
    }

    function setEditorMode(mode) {
      syncBoardPlacement();
      const printing = mode === "print";
      el("sd-tab-edit").className = "btn " + (printing ? "ghost" : "gold") + " small";
      el("sd-tab-print").className = "btn " + (printing ? "gold" : "ghost") + " small";
      el("sd-edit-controls").classList.toggle("hidden", printing);
      el("sd-print-controls").classList.toggle("hidden", !printing);
      el("sd-board-wrap").classList.toggle("hidden", printing);
      el("sd-print").classList.toggle("hidden", !printing);
      if (printing) renderPrintView();
      else drawBoard();
    }

    function renderTools() {
      const host = el("sd-tools");
      const tools = TILE_TOOLS.filter((entry) => !entry.onlyExpanded || META.max_tiles > META.base_tile_total);
      host.innerHTML = `<div class="sd-palette-title">Base components</div>` + tools.map((entry) => {
        const remaining = paletteRemaining(entry.type);
        return `
        <button class="sd-tool ${tool === entry.type && laneRoll == null ? "active" : ""} ${remaining === 0 ? "exhausted" : ""}" data-tool="${entry.type}"
          style="${TILE_FILL[entry.type] ? `--tool-color:${TILE_FILL[entry.type]}` : ""}">
          <span class="sd-tool-icon">${entry.icon}</span><span class="sd-tool-label">${entry.label}</span>
          ${remaining == null ? "" : `<span class="sd-tool-remaining" title="Unplaced components remaining">${remaining}</span>`}
        </button>`;
      }).join("");
      host.querySelectorAll(".sd-tool").forEach((button) => button.addEventListener("click", () => {
        if (paletteRemaining(button.dataset.tool) === 0 && button.dataset.tool !== "core") {
          setStatus("That base component is fully placed. Remove one from the ship to return it to the palette.", false);
          return;
        }
        tool = button.dataset.tool;
        laneRoll = null;
        lanePick = null;
        renderTools();
        renderLanePanel();
        drawBoard();
      }));
      const bonusHost = el("sd-bonus-tools");
      if (bonusHost) {
        const bonuses = META.bonus_components || [];
        bonusHost.innerHTML = `<div class="sd-lanes-title">Campaign reward components</div>` +
          (bonuses.length ? bonuses.map((entry) => `
            <button class="sd-tool ${tool === "bonus:" + entry.id && laneRoll == null ? "active" : ""}"
              data-bonus-tool="${esc(entry.id)}" style="--tool-color:${entry.component_type === "weapon" ? "#d66b8f" : "#62bba1"}">
              <span class="sd-tool-icon">${entry.component_type === "weapon" ? "☄" : "🔥"}</span>${esc(entry.name)} (${entry.cost})
            </button>`).join("") : '<div class="sd-tool-note">Win battles or destroy an opposing ship to unlock components here.</div>');
        bonusHost.querySelectorAll("[data-bonus-tool]").forEach((button) => button.addEventListener("click", () => {
          tool = "bonus:" + button.dataset.bonusTool;
          laneRoll = null;
          lanePick = null;
          renderTools();
          renderLanePanel();
          drawBoard();
        }));
      }
      el("sd-tool-note").textContent = laneRoll != null
        ? `Placing lane ${laneRoll}: click a hex, then pick the shot direction.`
        : tool.startsWith("bonus:")
          ? ((bonusById(tool.slice(6))?.description || "Campaign reward component") +
            ` Costs ${bonusById(tool.slice(6))?.cost || "?"} Core point(s) and adds its matching card.`)
          : (TILE_NOTES[tool] || "");
    }

    function renderLanePanel() {
      const host = el("sd-lanes-panel");
      if (!host) return;
      const lanes = placedLanes();
      const bad = Object.fromEntries(laneProblems().map((b) => [String(b.roll), b.reason]));
      const anyPlaced = Object.keys(lanes).length > 0;
      const hint = laneRoll != null
        ? "Click a hex the lane should pass through, then pick its direction."
        : advancedLanes
          ? "Click a number, then place that lane on the board. Each lane must sever ≥ "
            + META.secondary_lane_min_severed + " components from the Core when shot fully through."
          : "Auto-place finds legal lane sets for your hull"
            + " — every lane severs ≥ " + META.secondary_lane_min_severed
            + " components from the Core when shot fully through. Symmetric hulls get mirrored lanes.";
      host.innerHTML = `
        <div class="sd-lanes-title">Secondary damage lanes</div>
        <div class="sd-lane-chips">
          ${SECONDARY_ROLLS.map((roll) => {
            const placed = !!lanes[roll];
            const lane = lanes[roll];
            const cells = lane ? laneCells(lane.q, lane.r, lane.dir) : null;
            const displayRoll = lane ? laneDisplayRoll("secondary", roll, cells, lane.dir) : roll;
            const badReason = bad[String(roll)];
            const cls = (laneRoll === roll ? "picking" : placed ? (badReason ? "bad" : "ok") : "")
              + (advancedLanes ? " clickable" : "");
            return `<span class="sd-lane-chip ${cls}" data-lane="${roll}"
              title="${placed ? (badReason ? esc(badReason) : "placed") : "not placed"}">${roll}${placed ? (badReason ? " ⚠" : " ✓") : ""}
              ${placed && advancedLanes ? `<button class="sd-lane-clear" data-lane-clear="${roll}" title="Remove lane ${roll}">✕</button>` : ""}
            </span>`;
          }).join("")}
        </div>
        <div class="sd-lane-actions">
          <button id="sd-lane-auto" class="btn ghost small">🎲 ${anyPlaced ? "Next lane arrangement" : "Auto-place lanes"}</button>
          <button id="sd-lane-renumber" class="btn ghost small">Renumber lanes linearly</button>
        </div>
        <label class="sd-lane-toggle"><input id="sd-lane-adv" type="checkbox" ${advancedLanes ? "checked" : ""}>
          Advanced: place lanes manually</label>
        <div class="sd-lane-hint">${hint}</div>`;
      el("sd-lane-auto").addEventListener("click", autoPlaceLanes);
      el("sd-lane-renumber").addEventListener("click", () => renumberLanesLinearly());
      el("sd-lane-adv").addEventListener("change", () => {
        advancedLanes = el("sd-lane-adv").checked;
        try { localStorage.setItem("ss_stardock_adv_lanes", advancedLanes ? "1" : "0"); } catch (err) { /* ok */ }
        laneRoll = null;
        lanePick = null;
        renderTools();
        renderLanePanel();
        drawBoard();
      });
      if (advancedLanes) {
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
      for (const tile of design.tiles.filter((entry) => entry.type === "bonus_component")) {
        const bonus = bonusById(tile.reward_id);
        if (bonus) cards.push(["bonus:" + bonus.id, 1]);
      }
      el("sd-deck").innerHTML = `
        <div class="sd-lanes-title">Starting deck preview (${deckComponentCount()}/${META.deck_size} cards)</div>
        ${cards.length
          ? cards.map(([type, n]) => `<div class="sd-deck-row">${n} × ${type.startsWith("bonus:") ? esc(bonusById(type.slice(6))?.card_name || bonusById(type.slice(6))?.name || type) : DECK_CARD_NAMES[type]}</div>`).join("")
          : '<div class="sd-deck-row sd-empty-deck">Place Engines and Cannons to build your deck.</div>'}`;
      el("sd-checklist").innerHTML = checklist().map((item) =>
        `<div class="sd-check ${item.ok ? "ok" : ""}">${item.ok ? "✔" : "○"} ${esc(item.text)}</div>`).join("");
      renderLanePanel();
      if (el("sd-print") && !el("sd-print").classList.contains("hidden")) renderPrintView();
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
        const fill = tile ? (tile.type === "bonus_component"
          ? (bonusById(tile.reward_id)?.component_type === "weapon" ? "#d66b8f" : "#62bba1")
          : (TILE_FILL[tile.type] || "#888")) : "rgba(150,160,190,0.10)";
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
            const dir = PRIMARY_DIRS[roll];
            const cellsOnLine = laneCells(core.q, core.r, dir);
            const hits = cellsOnLine.filter(([q, r]) => tileAt(q, r)).length;
            const displayRoll = laneDisplayRoll("primary", roll, cellsOnLine, dir);
            body += laneMarkerSvg(displayRoll, cellsOnLine, "#ffd75e",
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
          const displayRoll = laneDisplayRoll("secondary", roll, cellsOnLine, lane.dir);
          body += laneMarkerSvg(displayRoll, cellsOnLine, badReason ? "#ff8d7a" : "#8fd7ff",
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
      const bonusId = tool.startsWith("bonus:") ? tool.slice(6) : null;
      const selectedType = bonusId ? "bonus_component" : tool;
      if (tool === "erase") {
        if (existing) {
          design.tiles = design.tiles.filter((t) => t !== existing);
          markDirty();
        }
      } else if (existing && existing.type === selectedType && (!bonusId || existing.reward_id === bonusId)) {
        design.tiles = design.tiles.filter((t) => t !== existing); // toggle off
        markDirty();
      } else {
        const remaining = bonusId ? null : paletteRemaining(selectedType);
        if (remaining === 0 && selectedType !== "core") {
          setStatus(`No unplaced ${TILE_TOOLS.find((entry) => entry.type === selectedType)?.label || selectedType} components remain in the base palette.`, false);
          return;
        }
        if (tool === "core" && countType("core") >= 1 && (!existing || existing.type !== "core")) {
          // moving the core: remove the old one
          design.tiles = design.tiles.filter((t) => t.type !== "core");
        }
        if (!existing && design.tiles.length >= META.max_tiles) {
          setStatus(`A ship places at most ${META.max_tiles} tiles — erase one first.`, false);
          return;
        }
        if (existing) design.tiles = design.tiles.filter((t) => t !== existing);
        design.tiles.push(bonusId
          ? { q, r, type: selectedType, reward_id: bonusId }
          : { q, r, type: selectedType });
        markDirty();
      }
      renderTools();
      renderMeters();
      drawBoard();
    }

    function sortedTiles() {
      return [...(design.tiles || [])].sort((a, b) => (a.r - b.r) || (a.q - b.q));
    }

    function componentBadges() {
      const prefixes = {
        core: "CR", life_support: "LS", bone_room: "BR", docking_bay: "DB",
        engine: "E", double_engine: "DE", cannon: "CN", double_cannon: "DC",
        structure: "ST",
        weapon: "W", crew: "CQ", bay: "DB", shield_generator: "SG",
        signal_jammer: "J", targeting_sensors: "TS",
      };
      const totals = {};
      for (const tile of design.tiles || []) totals[tile.type] = (totals[tile.type] || 0) + 1;
      const seen = {};
      const badges = {};
      for (const tile of sortedTiles()) {
        seen[tile.type] = (seen[tile.type] || 0) + 1;
        const prefix = prefixes[tile.type] || tile.type.slice(0, 2).toUpperCase();
        badges[key(tile.q, tile.r)] = totals[tile.type] > 1 ? prefix + seen[tile.type] : prefix;
      }
      return badges;
    }

    function tileLabel(tile) {
      if (tile.type === "bonus_component") return bonusById(tile.reward_id)?.name || tile.reward_id;
      const meta = TILE_TOOLS.find((entry) => entry.type === tile.type);
      return meta?.label || tile.type.replace(/_/g, " ").replace(/\b\w/g, (m) => m.toUpperCase());
    }

    function printPalette() {
      if (printTone === "bw") {
        return {
          page: "#ffffff", text: "#111111", dim: "#555555", line: "#111111",
          hull: "#f5f5f5", core: "#d0d0d0", life: "#e4e4e4", utility: "#ffffff",
          move: "#dddddd", attack: "#eeeeee", structure: "#f8f8f8",
          primary: "#111111", secondary: "#555555", card: "#ffffff",
        };
      }
      return {
        page: "#fffaf0", text: "#151923", dim: "#5f6675", line: "#283246",
        hull: "#f2ead8", core: "#f0b090", life: "#f4df89", utility: "#dcc0a0",
        move: "#bce7b8", attack: "#ffc9c9", structure: "#ccd3df",
        primary: "#b98a12", secondary: "#2c8fc4", card: "#fffdf7",
      };
    }

    function printTileFill(tile, colors) {
      if (tile.type === "core") return colors.core;
      if (tile.type === "life_support" || tile.type === "bone_room") return colors.life;
      if (tile.type === "docking_bay" || tile.type === "bay") return colors.utility;
      if (tile.type === "engine" || tile.type === "double_engine") return colors.move;
      if (tile.type === "cannon" || tile.type === "double_cannon" || tile.type === "weapon") return colors.attack;
      return colors.structure;
    }

    function printSheetSVG() {
      if (!design) return "";
      const colors = printPalette();
      const badges = componentBadges();
      const pageW = 1400;
      let pageH = 1720;
      const shipBox = { x: 55, y: 175, w: pageW - 110, h: 690 };
      const baseSize = 34;
      const baseXy = (q, r) => [baseSize * 1.5 * q, baseSize * SQ * (r + q / 2)];
      const basePoints = design.tiles.length ? design.tiles.map((tile) => baseXy(tile.q, tile.r)) : [[0, 0]];
      const baseMinX = Math.min(...basePoints.map(([x]) => x)) - baseSize;
      const baseMaxX = Math.max(...basePoints.map(([x]) => x)) + baseSize;
      const baseMinY = Math.min(...basePoints.map(([, y]) => y)) - baseSize;
      const baseMaxY = Math.max(...basePoints.map(([, y]) => y)) + baseSize;
      const shipScale = Math.min(
        1,
        (shipBox.w - 70) / Math.max(1, baseMaxX - baseMinX),
        (shipBox.h - 70) / Math.max(1, baseMaxY - baseMinY),
      ) * printZoom;
      const shipSize = baseSize * shipScale;
      const rawXy = (q, r) => [shipSize * 1.5 * q, shipSize * SQ * (r + q / 2)];
      const rawPoints = design.tiles.length ? design.tiles.map((tile) => rawXy(tile.q, tile.r)) : [[0, 0]];
      const minRawX = Math.min(...rawPoints.map(([x]) => x)) - shipSize;
      const maxRawX = Math.max(...rawPoints.map(([x]) => x)) + shipSize;
      const minRawY = Math.min(...rawPoints.map(([, y]) => y)) - shipSize;
      const maxRawY = Math.max(...rawPoints.map(([, y]) => y)) + shipSize;
      const shipX = shipBox.x + shipBox.w / 2 - (minRawX + maxRawX) / 2;
      const shipY = shipBox.y + shipBox.h / 2 - (minRawY + maxRawY) / 2;
      const pxy = (q, r) => {
        const [x, y] = rawXy(q, r);
        return [shipX + x, shipY + y];
      };

      let ship = "";
      for (const tile of sortedTiles()) {
        const [x, y] = pxy(tile.q, tile.r);
        const badge = badges[key(tile.q, tile.r)] || "";
        ship += `<g>
          <polygon points="${hexPoints(x, y, shipSize - 1.2)}" fill="${printTileFill(tile, colors)}" stroke="${colors.line}" stroke-width="2"/>
          <text x="${x}" y="${y + 6}" text-anchor="middle" class="ps-badge">${esc(badge)}</text>
          ${printOptions.coords ? `<text x="${x}" y="${y + shipSize - 5}" text-anchor="middle" class="ps-coord">${tile.q},${tile.r}</text>` : ""}
          <title>${esc(tileLabel(tile))} (${tile.q},${tile.r})</title>
        </g>`;
      }

      const laneEntries = [];
      const core = coreTile();
      if (core) {
        for (const roll of Object.keys(PRIMARY_DIRS)) {
          const dir = PRIMARY_DIRS[roll];
          const cells = laneCells(core.q, core.r, dir);
          laneEntries.push({ roll: laneDisplayRoll("primary", roll, cells, dir), cells, kind: "primary" });
        }
      }
      for (const roll of SECONDARY_ROLLS) {
        const lane = (design.lanes || {})[String(roll)];
        if (lane) {
          const cells = laneCells(lane.q, lane.r, lane.dir);
          laneEntries.push({ roll: laneDisplayRoll("secondary", roll, cells, lane.dir), cells, kind: "secondary" });
        }
      }
      if (printOptions.lanes) {
        for (const entry of laneEntries) {
          const firstHitIndex = entry.cells.findIndex(([q, r]) => !!tileAt(q, r));
          if (firstHitIndex < 0) continue;
          const first = entry.cells[firstHitIndex];
          const previous = entry.cells[firstHitIndex - 1] || first;
          const next = entry.cells[firstHitIndex + 1] || first;
          const [fx, fy] = pxy(first[0], first[1]);
          const [px, py] = pxy(previous[0], previous[1]);
          const [nx, ny] = pxy(next[0], next[1]);
          let dx = nx - px, dy = ny - py;
          if (!dx && !dy) { dx = 0; dy = 1; }
          const len = Math.hypot(dx, dy) || 1;
          const ux = dx / len, uy = dy / len;
          const color = entry.kind === "primary" ? colors.primary : colors.secondary;
          const bubbleR = Math.max(8.5, Math.min(14, shipSize * 0.36));
          const faceDist = shipSize * 0.88;
          const bubbleDist = faceDist + bubbleR + shipSize * 0.34;
          const bx = fx - ux * bubbleDist, by = fy - uy * bubbleDist;
          const startX = bx + ux * (bubbleR + 1.5), startY = by + uy * (bubbleR + 1.5);
          const hx = fx - ux * faceDist, hy = fy - uy * faceDist;
          const headLen = Math.max(5.5, shipSize * 0.22);
          const headHalf = Math.max(3.5, shipSize * 0.12);
          const shaftW = Math.max(1.8, shipSize * 0.075);
          const baseX = hx - ux * headLen, baseY = hy - uy * headLen;
          const perpX = -uy, perpY = ux;
          const arrowPoints = `${hx.toFixed(1)},${hy.toFixed(1)} `
            + `${(baseX + perpX * headHalf).toFixed(1)},${(baseY + perpY * headHalf).toFixed(1)} `
            + `${(baseX - perpX * headHalf).toFixed(1)},${(baseY - perpY * headHalf).toFixed(1)}`;
          ship += `<g class="ps-lane">
            <line x1="${startX.toFixed(1)}" y1="${startY.toFixed(1)}" x2="${baseX.toFixed(1)}" y2="${baseY.toFixed(1)}" stroke="${color}" stroke-width="${shaftW.toFixed(1)}" stroke-linecap="round"/>
            <polygon points="${arrowPoints}" fill="${color}"/>
            <circle cx="${bx.toFixed(1)}" cy="${by.toFixed(1)}" r="${bubbleR.toFixed(1)}" fill="${colors.page}" stroke="${color}" stroke-width="2"/>
            <text x="${bx}" y="${by + 5}" text-anchor="middle" class="ps-lane-num" fill="${color}">${entry.roll}</text>
          </g>`;
        }
      }

      let side = "";
      let cursorY = shipBox.y + shipBox.h + 56;
      const colX = [70, 520, 930];
      const counts = deckCounts();
      const upgradeLabels = UPGRADE_LABELS();
      const summary = [
        `Shields: ${META.base_shields + (design.upgrade === "shield" ? 1 : 0)}`,
        `Draw: ${META.base_draw + (design.upgrade === "draw" ? 1 : 0)}`,
        `Core points: ${corePointsSpent()} / ${corePointsBudget()}`,
        `Tiles: ${design.tiles.length} / ${META.max_tiles}`,
      ];
      side += `<text x="70" y="${cursorY}" class="ps-section">Ship Summary</text>`;
      cursorY += 30;
      summary.forEach((line, index) => {
        side += `<text x="${colX[index % 3]}" y="${cursorY + Math.floor(index / 3) * 24}" class="ps-list">${esc(line)}</text>`;
      });
      cursorY += Math.ceil(summary.length / 3) * 24 + 18;
      side += `<text x="70" y="${cursorY}" class="ps-list">Special advantage: ${esc(upgradeLabels[design.upgrade] || "not chosen")}</text>`;
      cursorY += 38;

      if (printOptions.deck) {
        side += `<text x="70" y="${cursorY}" class="ps-section">Starting Deck</text>`;
        cursorY += 28;
        const cardTypes = [
          ["engine", counts.engine],
          ["double_engine", counts.double_engine],
          ["cannon", counts.cannon],
          ["double_cannon", counts.double_cannon],
        ];
        let cardIndex = 0;
        for (const [type, count] of cardTypes) {
          for (let i = 0; i < count; i++) {
            const x = 70 + (cardIndex % 5) * 246;
            const y = cursorY + Math.floor(cardIndex / 5) * 72;
            const isMove = type.includes("engine");
            side += `<g>
              <rect x="${x}" y="${y}" width="220" height="54" rx="7" fill="${colors.card}" stroke="${colors.line}" stroke-width="1.8"/>
              <rect x="${x}" y="${y}" width="10" height="54" rx="5" fill="${isMove ? colors.move : colors.attack}"/>
              <text x="${x + 24}" y="${y + 32}" class="ps-card">${esc(DECK_CARD_NAMES[type])}</text>
            </g>`;
            cardIndex += 1;
          }
        }
        if (!cardIndex) side += `<text x="70" y="${cursorY}" class="ps-small">No deck components placed.</text>`;
        cursorY += Math.max(1, Math.ceil(Math.max(cardIndex, 1) / 5)) * 72 + 16;
      }

      if (printOptions.components) {
        side += `<text x="70" y="${cursorY}" class="ps-section">Components</text>`;
        cursorY += 28;
        sortedTiles().forEach((tile, index) => {
          const column = index % 3;
          const row = Math.floor(index / 3);
          const x = colX[column];
          const y = cursorY + row * 23;
          side += `<text x="${x}" y="${y}" class="ps-list">${esc(badges[key(tile.q, tile.r)] || "")}</text>
            <text x="${x + 58}" y="${y}" class="ps-small">${esc(tileLabel(tile))} (${tile.q},${tile.r})</text>`;
        });
        cursorY += Math.ceil(Math.max(sortedTiles().length, 1) / 3) * 23 + 24;
      }

      if (printOptions.laneList) {
        side += `<text x="70" y="${cursorY}" class="ps-section">Damage Lanes</text>`;
        cursorY += 28;
        laneEntries.sort((a, b) => a.roll - b.roll).forEach((entry, index) => {
          const ids = entry.cells
            .map(([q, r]) => badges[key(q, r)])
            .filter(Boolean)
            .join(" -> ") || "miss";
          const x = index % 2 === 0 ? 70 : 700;
          const y = cursorY + Math.floor(index / 2) * 24;
          side += `<text x="${x}" y="${y}" class="ps-list">${entry.roll}</text>
            <text x="${x + 38}" y="${y}" class="ps-small">${esc(entry.kind)}: ${esc(ids)}</text>`;
        });
        cursorY += Math.ceil(Math.max(laneEntries.length, 1) / 2) * 24 + 24;
      }

      if (printOptions.checklist) {
        side += `<text x="70" y="${cursorY}" class="ps-section">Table Checklist</text>`;
        cursorY += 28;
        [
          `Use one d12 for player damage lanes; each roll follows that numbered lane.`,
          `Track shields (${META.base_shields + (design.upgrade === "shield" ? 1 : 0)} max), hand draw (${META.base_draw + (design.upgrade === "draw" ? 1 : 0)}), and destroyed components.`,
          `When a component is destroyed, remove any intact components no longer connected to the Core.`,
          `Special advantage: ${upgradeLabels[design.upgrade] || "not chosen"}.`,
        ].forEach((line) => {
          side += `<text x="70" y="${cursorY}" class="ps-list">- ${esc(line)}</text>`;
          cursorY += 24;
        });
      }
      if (design.description) {
        cursorY += 10;
        side += `<text x="70" y="${cursorY}" class="ps-small">${esc(design.description).slice(0, 190)}</text>`;
        cursorY += 22;
      }
      pageH = Math.max(1200, cursorY + 110);

      return `<svg xmlns="http://www.w3.org/2000/svg" width="${pageW}" height="${pageH}" viewBox="0 0 ${pageW} ${pageH}">
        <defs>
          <style>
            .ps-title{font:700 44px 'Space Grotesk',Arial,sans-serif;fill:${colors.text}}
            .ps-sub{font:600 18px 'Space Grotesk',Arial,sans-serif;fill:${colors.dim}}
            .ps-section{font:700 24px 'Space Grotesk',Arial,sans-serif;fill:${colors.text}}
            .ps-badge{font:700 17px 'Space Grotesk',Arial,sans-serif;fill:${colors.text}}
            .ps-coord{font:600 10px 'Space Grotesk',Arial,sans-serif;fill:${colors.dim}}
            .ps-lane-num{font:700 14px 'Space Grotesk',Arial,sans-serif}
            .ps-card{font:700 17px 'Space Grotesk',Arial,sans-serif;fill:${colors.text}}
            .ps-small{font:500 13px 'Space Grotesk',Arial,sans-serif;fill:${colors.dim}}
            .ps-list{font:600 16px 'Space Grotesk',Arial,sans-serif;fill:${colors.text}}
          </style>
        </defs>
        <rect width="${pageW}" height="${pageH}" fill="${colors.page}"/>
        <text x="70" y="78" class="ps-title">${esc(design.name || "Player Ship")}</text>
        <text x="72" y="112" class="ps-sub">StarShot printable StarDock ship sheet - ${printTone === "bw" ? "black and white" : "color"}</text>
        <text x="70" y="155" class="ps-section">Hull, Components, and Damage Lane Arrows</text>
        <rect x="${shipBox.x}" y="${shipBox.y}" width="${shipBox.w}" height="${shipBox.h}" rx="14" fill="${colors.hull}" stroke="${colors.line}" stroke-width="2"/>
        ${ship}
        ${side}
      </svg>`;
    }

    function renderPrintView() {
      const container = el("sd-print");
      if (!container) return;
      container.innerHTML = `<div class="sd-print-preview">${printSheetSVG()}</div>`;
    }

    function downloadPrintSheet() {
      const blob = new Blob([printSheetSVG()], { type: "image/svg+xml;charset=utf-8" });
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = `starshot-${(design.id || "ship").replace(/[^a-z0-9_-]+/gi, "-")}-ship-sheet.svg`;
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
      win.document.write(`<!doctype html><html><head><title>${esc(design.name)} ship sheet</title>
        <style>body{margin:0;background:white}svg{width:100%;height:auto;display:block}@media print{body{margin:0}}</style>
        </head><body>${printSheetSVG()}<script>window.onload=function(){window.focus();window.print();};<\/script></body></html>`);
      win.document.close();
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
          : "Saved — battle-ready! Choose it from Your Ship on the main deck.", true);
      } catch (err) { setStatus(err.message, false); }
    }

    // ── boot ─────────────────────────────────────────────────────────────
    async function boot(opts = {}) {
      if (design) {
        // An editor is already open. If asked to jump to a different design,
        // switch to it; otherwise keep what's showing.
        if (opts.editDesignId && opts.editDesignId !== design.id && !dirty) {
          await openDesign(opts.editDesignId);
        }
        return;
      }
      try {
        await refreshList();
        renderLibrary();
        if (!isAdmin && opts.editDesignId && designs.some((entry) => entry.id === opts.editDesignId)) {
          await openDesign(opts.editDesignId);
        } else if (!isAdmin && META.first_visit && designs.some((entry) => entry.id === META.initial_design_id)) {
          await openDesign(META.initial_design_id);
        }
        booted = true;
      } catch (err) {
        root().innerHTML = `<div class="sd-wrap"><div id="sd-status" class="admin-status err">${esc(err.message)}</div></div>`;
      }
    }

    // Load a specific design straight into the editor (from the landing card).
    async function openDesign(designId) {
      const data = await call("/" + encodeURIComponent(designId));
      design = data.design;
      design.lanes = design.lanes || {};
      dirty = false;
      renderEditor(data.problems);
    }

    return { boot };
  }

  // ── main app: full-screen "My Ships" overlay, opened from the lobby ─────
  let playerDesigner = null;
  function openPlayerDesigner(opts = {}) {
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
    playerDesigner.boot(opts);
    maybeShowHowto();
  }

  const LS_HOWTO = "ss_shipdesigner_howto_seen4";
  function showHowto() {
    const howto = document.createElement("div");
    howto.className = "overlay bd-howto-overlay";
    howto.innerHTML = `
      <div class="picker">
        <h3>🚀 StarDock <span class="badge-alpha">ALPHA</span> — how it works</h3>
        <p class="tutorial-alpha-note">StarDock is still in Alpha — rules and balance may shift as it's tested. Bug reports and feedback are very welcome.</p>
        <div class="tutorial-steps">
          <div><b>Starter ship.</b> Every captain starts with a personal copy of <b>Lightning Bug Alpha</b> — shown on the main deck as Your Ship. Save it as-is, reshape it, or use it as the starting point for another design.</div>
          <div><b>1.</b> Place <b>15 contiguous tiles</b>: 1 Core, 2 Life Supports, 1 Bone Room, 1 Docking Bay,
            and exactly <b>10 Engine/Cannon components</b>.</div>
          <div><b>2.</b> Those 10 components are your <b>starting deck</b>, bought with <b>15 Core Component points</b>:
            Engine = Move 1 (1 pt), Double Engine = Move 2 (2 pts), Cannon = Aim +1 (1 pt), Double Cannon = Aim +2 (2 pts).</div>
          <div><b>Base palette.</b> Common parts are finite: 2 Double Cannons, 3 Cannons, 3 Double Engines, and 2 Engines. The number on each palette button shows how many remain unplaced.</div>
          <div><b>3.</b> The 6 gold <b>primary damage lanes</b> follow the Core — at most 10 components may sit on them.
            The 6 blue <b>secondary lanes</b> must each sever at least 2 components from the Core if shot fully through:
            use <b>🎲 Auto-place lanes</b> to cycle legal arrangements (mirrored on symmetric ships), or tick
            <b>Advanced</b> to place them by hand.</div>
          <div><b>4.</b> Pick <b>1 special upgrade</b>: +1 shield, +1 card draw, flat Defense, flat Aim, or +2 Core points.</div>
          <div><b>5.</b> Save a battle-ready design, then pick it from <b>Your Ship</b> on the main deck — you'll fly it in every raid.</div>
          <div><b>Campaign components.</b> Winning on VP or destroying an opposing ship can unlock a component and matching card. Earned parts appear in their own palette and may be used in any ship you design.</div>
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
