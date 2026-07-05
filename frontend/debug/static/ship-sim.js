const SQRT3 = Math.sqrt(3);
const HEX_SIZE = 26;

const elements = {
  runsInput: document.querySelector("#runsInput"),
  damageInput: document.querySelector("#damageInput"),
  shieldsInput: document.querySelector("#shieldsInput"),
  defenseInput: document.querySelector("#defenseInput"),
  aimInput: document.querySelector("#aimInput"),
  diceCountInput: document.querySelector("#diceCountInput"),
  dieSidesInput: document.querySelector("#dieSidesInput"),
  doubleMaxAutoHitInput: document.querySelector("#doubleMaxAutoHitInput"),
  seedInput: document.querySelector("#seedInput"),
  runButton: document.querySelector("#runButton"),
  averageKill: document.querySelector("#averageKill"),
  fastestKill: document.querySelector("#fastestKill"),
  slowestKill: document.querySelector("#slowestKill"),
  totalHits: document.querySelector("#totalHits"),
  hitRate: document.querySelector("#hitRate"),
  shotsFired: document.querySelector("#shotsFired"),
  misses: document.querySelector("#misses"),
  shieldBlocks: document.querySelector("#shieldBlocks"),
  autoHits: document.querySelector("#autoHits"),
  shipHeatmap: document.querySelector("#shipHeatmap"),
  eliminationList: document.querySelector("#eliminationList"),
  componentList: document.querySelector("#componentList"),
};

elements.runButton.addEventListener("click", () => runSimulation().catch(showError));

async function runSimulation() {
  elements.runButton.disabled = true;
  elements.runButton.textContent = "Running...";
  try {
    const params = new URLSearchParams({
      runs: readNumber(elements.runsInput, 1000),
      damage_per_volley: readNumber(elements.damageInput, 1),
      initial_shields: readNumber(elements.shieldsInput, 0),
      defense_threshold: readNumber(elements.defenseInput, 7),
      aim_bonus: readNumber(elements.aimInput, 0),
      attack_dice_count: readNumber(elements.diceCountInput, 2),
      attack_die_sides: readNumber(elements.dieSidesInput, 12),
      double_max_auto_hit: elements.doubleMaxAutoHitInput.checked,
      max_steps: 500,
    });
    const seed = elements.seedInput.value.trim();
    if (seed) params.set("seed", seed);

    const response = await fetch(`/api/simulations/ship-kill?${params.toString()}`);
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.detail || `Request failed: ${response.status}`);
    renderResults(payload);
  } finally {
    elements.runButton.disabled = false;
    elements.runButton.textContent = "Run Simulation";
  }
}

function readNumber(input, fallback) {
  const value = Number(input.value);
  return Number.isFinite(value) ? value : fallback;
}

function renderResults(payload) {
  const summary = payload.summary;
  elements.averageKill.textContent = `${summary.average_steps_to_kill} shots`;
  elements.fastestKill.textContent = `${summary.min_steps_to_kill}`;
  elements.slowestKill.textContent = `${summary.max_steps_to_kill}`;
  elements.totalHits.textContent = `${summary.total_component_hits}`;
  elements.hitRate.textContent = percent(summary.hit_rate);
  elements.shotsFired.textContent = `${summary.total_shots}`;
  elements.misses.textContent = `${summary.total_misses}`;
  elements.shieldBlocks.textContent = `${summary.total_shield_blocks}`;
  elements.autoHits.textContent = `${summary.total_auto_hits}`;
  renderHeatmap(payload.components);
  renderEliminations(summary.elimination_reasons, payload.config.runs);
  renderComponents(payload.components);
}

function renderHeatmap(components) {
  const svg = elements.shipHeatmap;
  svg.replaceChildren();
  svg.setAttribute("viewBox", "-92 -112 184 224");

  const maxRate = Math.max(...components.map((component) => component.destroyed_rate), 0.01);
  components.forEach((component) => {
    const [x, y] = axialToPixel(component.q, component.r);
    const group = svgEl("g");
    group.setAttribute("class", "heat-cell");

    const polygon = svgEl("polygon");
    polygon.setAttribute("points", hexPoints(x, y).map((point) => point.join(",")).join(" "));
    polygon.setAttribute("fill", heatColor(component.destroyed_rate / maxRate));

    const name = svgEl("text");
    name.setAttribute("class", "component-code");
    name.setAttribute("x", x);
    name.setAttribute("y", y - 4);
    name.textContent = shortName(component.name);

    const time = svgEl("text");
    time.setAttribute("class", "component-time");
    time.setAttribute("x", x);
    time.setAttribute("y", y + 10);
    time.textContent = component.average_first_hit_step === null ? "-" : component.average_first_hit_step.toFixed(1);

    const title = svgEl("title");
    title.textContent = `${component.name}: ${percent(component.destroyed_rate)} destroyed, avg first hit ${formatMaybe(component.average_first_hit_step)} shots`;

    group.append(polygon, name, time, title);
    svg.append(group);
  });
}

function renderEliminations(reasons, runs) {
  const labels = {
    bridge: "Bridge destroyed",
    life_support: "Both life supports destroyed",
    weapons_and_engines: "All weapons and engines destroyed",
    max_steps: "Reached step cap",
  };
  elements.eliminationList.replaceChildren(
    ...Object.entries(labels).map(([reason, label]) => {
      const count = reasons[reason] || 0;
      const item = document.createElement("div");
      item.className = "elimination-row";
      item.innerHTML = `
        <span>${label}</span>
        <strong>${count}</strong>
        <em>${percent(count / runs)}</em>
      `;
      return item;
    }),
  );
}

function renderComponents(components) {
  const sorted = [...components].sort((left, right) => {
    const leftTime = left.average_destroyed_step ?? Number.POSITIVE_INFINITY;
    const rightTime = right.average_destroyed_step ?? Number.POSITIVE_INFINITY;
    return leftTime - rightTime || left.name.localeCompare(right.name);
  });
  elements.componentList.replaceChildren(
    ...sorted.map((component) => {
      const row = document.createElement("article");
      row.className = "component-row";
      row.innerHTML = `
        <div>
          <strong>${component.name}</strong>
          <span>${component.type.replaceAll("_", " ")}</span>
        </div>
        <dl>
          <div><dt>Avg Hit</dt><dd>${formatMaybe(component.average_first_hit_step)}</dd></div>
          <div><dt>Avg Kill</dt><dd>${formatMaybe(component.average_destroyed_step)}</dd></div>
          <div><dt>Rate</dt><dd>${percent(component.destroyed_rate)}</dd></div>
        </dl>
      `;
      return row;
    }),
  );
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

function heatColor(intensity) {
  const clamped = Math.max(0, Math.min(1, intensity));
  const hue = 204 - clamped * 192;
  const lightness = 86 - clamped * 34;
  return `hsl(${hue} 82% ${lightness}%)`;
}

function shortName(name) {
  return name
    .replace("Starboard", "Stbd")
    .replace("Forward", "Fwd")
    .split(" ")
    .map((word) => word.charAt(0))
    .join("");
}

function formatMaybe(value) {
  return value === null || value === undefined ? "-" : value.toFixed(2);
}

function percent(value) {
  return `${(value * 100).toFixed(1)}%`;
}

function showError(error) {
  alert(error.message);
}

runSimulation().catch(showError);
