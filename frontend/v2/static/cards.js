/* Card face descriptions + physical card DOM rendering. */
(function () {
  const ORIENTATION_LABELS = {
    forward: "⬆ Ahead",
    turn_left: "↰ Port",
    turn_right: "↱ Starboard",
    slip_left: "⬅ Slip Port",
    slip_right: "➡ Slip Starboard",
    u_turn_move: "⤵ Come About + Move",
    u_turn_attack: "⤵ Come About + Fire",
  };

  function orientationLabel(orientation) {
    return ORIENTATION_LABELS[orientation] || orientation;
  }

  function describeBasic(card) {
    const effect = card.effect || {};
    if (card.is_hybrid) return `Move ${effect.value || card.value} — or — Cannons +1 dmg`;
    if ((effect.family || card.family) === "move") {
      const turns = (effect.orientation_options || []).length > 1 ? " (may turn first)" : "";
      return `Move ${effect.value || card.value}${turns}`;
    }
    const bits = [];
    if (card.requires_target) bits.push("Targeted volley");
    if (/damage \+?(\d)/i.test(card.name)) bits.push("+" + RegExp.$1 + " damage");
    if (/aim \+?(\d)/i.test(card.name)) bits.push("aim +" + RegExp.$1);
    return bits.join(", ") || "Fire cannons";
  }

  function describeDesperate(face) {
    if (!face) return "";
    const bits = [];
    if (face.warp_destination) bits.push(`Warp (${face.warp_destination})`);
    else if (face.u_turn_move || face.u_turn_attack) bits.push(`Come about: move ${face.value} or fire +${face.damage_bonus + 1}`);
    else if (face.side_slip_direction || (face.orientation_options || []).includes("slip_right")) bits.push(`Slip sideways ${face.value}`);
    else if (face.double_turn_after_move) bits.push(`Move ${face.value}, then swing twice`);
    else if (face.family === "move") bits.push(`Move ${face.value}`);
    if (face.family === "attack" || face.u_turn_attack) {
      if (face.ramming_damage) bits.push(`ram ${face.value || face.ramming_distance || 3}, ${face.ramming_damage} hull damage`);
      if (face.attacks_cone_120) bits.push("120 degree cone");
      if (face.always_hits || face.aim_bonus >= 99) bits.push("NEVER misses");
      else if (face.aim_bonus) bits.push(`aim +${face.aim_bonus}`);
      if (face.damage_bonus && !face.u_turn_move) bits.push(`+${face.damage_bonus} damage`);
      if (face.lead_the_target) bits.push("lead the target");
    }
    if (face.repair_components) bits.push(`restore ${face.repair_components} component`);
    if (face.reconfigure_components) bits.push(`move ${face.reconfigure_components} damage`);
    if (face.defense_bonus) bits.push(`defense +${face.defense_bonus}`);
    return bits.join(" · ") || "Desperate gambit";
  }

  function familyIcon(family, isHybrid) {
    if (isHybrid) return "➤⚔";
    if (family === "move") return "➤";
    if (family === "attack") return "☄";
    return "✦";
  }

  function familyClass(card) {
    if (card.is_hybrid) return "fam-hybrid";
    return (card.effect && card.effect.family) === "move" || card.family === "move" ? "fam-move" : "fam-attack";
  }

  /* Build a card element. options: {inSlot, faceUsed, useTag, onClick} */
  function cardEl(card, options = {}) {
    const node = document.createElement("div");
    const desperateUsed = options.faceUsed === "desperate";
    node.className = "card " + familyClass(card)
      + (card.desperate_face && !desperateUsed ? " has-desperate" : "")
      + (desperateUsed ? " desperate-face" : "")
      + (options.inSlot ? " in-slot" : "");
    const family = desperateUsed ? card.desperate_face.family : (card.effect && card.effect.family) || card.family;
    const icon = familyIcon(family, !desperateUsed && card.is_hybrid);
    const text = desperateUsed
      ? describeDesperate(card.desperate_face)
      : card.no_basic_face
        ? "☄ " + describeDesperate(card.desperate_face)
        : describeBasic(card);
    node.innerHTML = `
      <div class="card-trim"></div>
      <div class="card-top"><span>${family === "move" ? "MOVE" : family === "attack" ? "ATTACK" : "CMD"}</span><span>${desperateUsed ? "☄" : "⚓"}</span></div>
      <div class="card-icon">${icon}</div>
      <div class="card-name">${escapeHtml(card.name)}</div>
      <div class="card-text">${escapeHtml(text)}</div>
      ${options.useTag ? `<div class="use-tag">${escapeHtml(options.useTag)}</div>` : ""}`;
    if (options.onClick) node.addEventListener("click", options.onClick);
    return node;
  }

  function cardBackEl(small) {
    const node = document.createElement("div");
    node.className = "card card-back" + (small ? " in-slot" : "");
    node.innerHTML = `<div class="back-skull">☠</div>`;
    return node;
  }

  function escapeHtml(value) {
    return String(value ?? "").replace(/[&<>"']/g, (ch) => ({
      "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
    }[ch]));
  }

  window.Cards = { cardEl, cardBackEl, describeBasic, describeDesperate, orientationLabel, escapeHtml };
})();
