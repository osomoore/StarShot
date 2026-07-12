/* Ship hex-layout rendering: mini boards for the fleet rail and a full
   damage-lane view, modeled on the printed ship board (15 component hexes,
   d12 damage lanes entering from the rim, dashed shield rings). */
(function () {
  const SQRT3 = Math.sqrt(3);

  const TYPE_COLORS = {
    weapon: "#d98c8c",
    shield_generator: "#7aa3d9",
    crew: "#a98fd1",
    bridge: "#c96a4a",
    engine: "#7fbf7f",
    life_support: "#d9c46a",
    bay: "#c9a37a",
  };
  const TYPE_ICONS = {
    weapon: "☄", shield_generator: "🛡", crew: "☠", bridge: "⚙", engine: "🔥",
    life_support: "❀", bay: "⚓",
  };

  function hexXY(q, r, size) {
    return [size * 1.5 * q, size * SQRT3 * (r + q / 2)];
  }

  function hexPointsAt(cx, cy, size) {
    const pts = [];
    for (let i = 0; i < 6; i++) {
      const angle = (Math.PI / 180) * (60 * i);
      pts.push(`${(cx + size * Math.cos(angle)).toFixed(2)},${(cy + size * Math.sin(angle)).toFixed(2)}`);
    }
    return pts.join(" ");
  }

  function layoutBounds(components, size) {
    let minX = 0, maxX = 0, minY = 0, maxY = 0;
    for (const component of components) {
      const [x, y] = hexXY(component.q, component.r, size);
      minX = Math.min(minX, x); maxX = Math.max(maxX, x);
      minY = Math.min(minY, y); maxY = Math.max(maxY, y);
    }
    return { minX, maxX, minY, maxY };
  }

  /* Mini ship board as inline SVG markup (fleet rail). */
  function miniShipSVG(ship, pixelWidth) {
    const components = ship.component_layout || [];
    if (!components.length) return "";
    const size = 10;
    const destroyed = new Set(ship.destroyed_components || []);
    const bounds = layoutBounds(components, size);
    const pad = size * 2.6; // room for shield rings
    const viewX = bounds.minX - pad, viewY = bounds.minY - pad;
    const viewW = bounds.maxX - bounds.minX + pad * 2;
    const viewH = bounds.maxY - bounds.minY + pad * 2;
    const centerX = (bounds.minX + bounds.maxX) / 2;
    const centerY = (bounds.minY + bounds.maxY) / 2;
    const ringBase = Math.max(viewW, viewH) / 2 - size * 0.6;

    let cells = "";
    for (const component of components) {
      const [x, y] = hexXY(component.q, component.r, size);
      const dead = destroyed.has(component.id);
      const color = dead ? "#3a1418" : (TYPE_COLORS[component.type] || "#888");
      cells += `<polygon points="${hexPointsAt(x, y, size - 0.7)}" fill="${color}"
        stroke="${dead ? "#c33e3e" : "#0a0f1e"}" stroke-width="1"><title>${component.name}${dead ? " — DESTROYED" : ""}</title></polygon>`;
      if (dead) {
        cells += `<text x="${x}" y="${y + 3.5}" text-anchor="middle" font-size="9" fill="#ff8d7a">✕</text>`;
      }
    }
    let rings = "";
    for (let i = 0; i < 2; i++) {
      const spent = (ship.shields || 0) <= i;
      rings += `<circle cx="${centerX}" cy="${centerY}" r="${ringBase - i * 4.5}" fill="none"
        stroke="${spent ? "#3a4a66" : "#5ec8ff"}" stroke-width="1" stroke-dasharray="4 3"
        opacity="${spent ? 0.35 : 0.9}"><title>Shield ${i + 1}${spent ? " — spent" : ""}</title></circle>`;
    }
    return `<svg class="mini-ship" viewBox="${viewX} ${viewY} ${viewW} ${viewH}"
      width="${pixelWidth}" xmlns="http://www.w3.org/2000/svg">${rings}${cells}</svg>`;
  }

  /* Full ship board with the 12 damage lanes marked around the rim. */
  function fullShipSVG(ship) {
    const components = ship.component_layout || [];
    if (!components.length) return "";
    const size = 30;
    const destroyed = new Set(ship.destroyed_components || []);
    const lanes = ship.damage_lanes || {};
    const bounds = layoutBounds(components, size);
    const pad = size * 3.1;
    const viewX = bounds.minX - pad, viewY = bounds.minY - pad;
    const viewW = bounds.maxX - bounds.minX + pad * 2;
    const viewH = bounds.maxY - bounds.minY + pad * 2;
    const centerX = (bounds.minX + bounds.maxX) / 2;
    const centerY = (bounds.minY + bounds.maxY) / 2;
    const byId = {};
    for (const component of components) byId[component.id] = component;

    let cells = "";
    for (const component of components) {
      const [x, y] = hexXY(component.q, component.r, size);
      const dead = destroyed.has(component.id);
      const color = dead ? "#3a1418" : (TYPE_COLORS[component.type] || "#888");
      cells += `<polygon points="${hexPointsAt(x, y, size - 1.6)}" fill="${color}"
          stroke="${dead ? "#c33e3e" : "#0a0f1e"}" stroke-width="2">
          <title>${component.name}${dead ? " — DESTROYED" : ""}</title></polygon>
        <text x="${x}" y="${y - 6}" text-anchor="middle" font-size="13">${dead ? "✕" : (TYPE_ICONS[component.type] || "")}</text>
        <text x="${x}" y="${y + 9}" text-anchor="middle" font-size="6.5" fill="#10182b"
          font-family="Space Grotesk" font-weight="600">${component.name.replace(/(Port |Starboard |Forward |Aft )/, "").toUpperCase()}</text>`;
    }

    // Damage lane markers: each lane is a straight line of hexes; the shot
    // enters at the FIRST hex travelling toward the second. Place the number
    // just outside the entry hex, opposite the direction of travel, with the
    // arrow showing how the shot bores in (matches the printed ship board).
    let laneMarks = "";
    for (const roll of Object.keys(lanes)) {
      const path = lanes[roll];
      const first = byId[path[0]];
      const second = byId[path[1]];
      if (!first || !second) continue;
      const [fx, fy] = hexXY(first.q, first.r, size);
      const [sx, sy] = hexXY(second.q, second.r, size);
      const dx = sx - fx, dy = sy - fy;               // direction of travel
      const len = Math.hypot(dx, dy) || 1;
      const nx = dx / len, ny = dy / len;
      const labelX = fx - nx * size * 1.95;           // behind the entry hex
      const labelY = fy - ny * size * 1.95;
      const tipX = fx - nx * size * 0.95;             // arrow tip at the hex rim
      const tipY = fy - ny * size * 0.95;
      const names = path.map((id) => (byId[id] ? byId[id].name : id)).join(" → ");
      laneMarks += `<g opacity="0.95"><title>Lane ${roll}: ${names}</title>
        <text x="${labelX}" y="${labelY + 5}" text-anchor="middle" font-size="15" fill="#e8e0cc"
          font-family="Pirata One" >${roll}</text>
        <line x1="${labelX + nx * 9}" y1="${labelY + ny * 9}" x2="${tipX}" y2="${tipY}"
          stroke="#e8e0cc" stroke-width="1.4" marker-end="url(#laneArrow)"/></g>`;
    }

    let rings = "";
    const ringBase = Math.max(viewW, viewH) / 2 - size * 0.9;
    for (let i = 0; i < 2; i++) {
      const spent = (ship.shields || 0) <= i;
      rings += `<circle cx="${centerX}" cy="${centerY}" r="${ringBase - i * 12}" fill="none"
        stroke="${spent ? "#3a4a66" : "#5ec8ff"}" stroke-width="1.6" stroke-dasharray="8 6"
        opacity="${spent ? 0.3 : 0.85}"/>`;
    }

    return `<svg viewBox="${viewX} ${viewY} ${viewW} ${viewH}" style="width:100%;max-height:62vh"
      xmlns="http://www.w3.org/2000/svg">
      <defs><marker id="laneArrow" markerWidth="7" markerHeight="7" refX="5" refY="2.5" orient="auto">
        <polygon points="0 0, 6 2.5, 0 5" fill="#e8e0cc"/></marker></defs>
      ${rings}${cells}${laneMarks}</svg>`;
  }

  window.ShipView = { miniShipSVG, fullShipSVG };
})();
