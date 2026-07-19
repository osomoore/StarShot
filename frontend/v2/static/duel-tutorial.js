/* In-game duel tutorial: piratical, round-paced popups shown only for games
   started from the lobby's "Player Duel" / "Digital Duel" buttons. */
(function () {
  const STAGES = {
    1: {
      icon: "🏴‍☠", title: "Welcome to yer first Duel, Captain!",
      body: `Click a card stack to load it — you've got three: <b>Action I, II, and III</b>. Drop
        <b>movement and attack cards</b> into each one to set yer orders. When all three are
        loaded to yer liking, hit <b>Seal Orders</b> and pray to the void.
        <br><br>The fight runs <b>six rounds</b>, or until some poor soul's ship is sent to the deep.`,
      minRound: 1, skipLabel: "Let me sink or swim - skip tutorial",
    },
    2: {
      icon: "🔥", title: "A word on Overdrive",
      body: `Round 1's done — see how she played out? Each stack can be <b>Sealed</b> (runs once) or
        flipped to <b>Overdrive</b>, which doubles every card in it. The catch: overdriving a stack
        costs you a card draw next round. Save it for a sure shot, not a gamble.`,
      minRound: 2, skipLabel: "Skip further tips",
    },
    3: {
      icon: "✦", title: "Scoring the Vaults",
      body: `Numbered vaults pay out in their matching round — end the round inside the glowing
        cluster and claim <b>2 VP plus a Desperation card</b>. The central <b>Fang</b> pays out
        every round, and it's worth big VP come round 6. Keep one eye on the board, Captain.`,
      minRound: 3, skipLabel: "Skip further tips",
    },
    4: {
      icon: "⚓", title: "Mind yer Fleet",
      body: `The <b>Fleet</b> panel on the left tracks every ship in the fight. Click any ship there
        to study its board and damage lanes before you commit to a broadside.`,
      minRound: 4, skipLabel: "Skip further tips",
    },
    5: {
      icon: "☄", title: "Desperation Sets In",
      body: `Loot and battle damage feed you <b>Desperation cards</b> — two-faced monsters. The
        purple <b>DESPERATE face</b> is a single-use haymaker: guaranteed hits, wild maneuvers.
        Time one right and you can turn a losing fight around.`,
      minRound: 5, skipLabel: "Skip further tips",
    },
    6: {
      icon: "🌊", title: "Ye crossed the seas, Captain!",
      body: `Yer first duel is done and dusted. Ye've earned the <b>Crossed the Seas</b> badge —
        wear it proud on yer legend. Fair winds and full broadsides on the next one!`,
      minRound: null, skipLabel: "",
    },
  };
  const STAGE_ORDER = [1, 2, 3, 4, 5, 6];

  let popupOpen = false;

  function safeGet(key) {
    try { return localStorage.getItem(key); } catch (err) { return null; }
  }
  function safeSet(key, value) {
    try { localStorage.setItem(key, value); } catch (err) { /* ignore */ }
  }
  function safeSessionGet(key) {
    try { return sessionStorage.getItem(key); } catch (err) { return null; }
  }
  function safeSessionSet(key, value) {
    try { sessionStorage.setItem(key, value); } catch (err) { /* ignore */ }
  }
  function safeSessionRemove(key) {
    try { sessionStorage.removeItem(key); } catch (err) { /* ignore */ }
  }

  function isDone() {
    return !!safeGet("ss_duel_tut_done");
  }

  function markDone() {
    safeSet("ss_duel_tut_done", "1");
  }

  function reset() {
    try { localStorage.removeItem("ss_duel_tut_done"); } catch (err) { /* ignore */ }
  }

  function markPending() {
    safeSessionSet("ss_duel_pending", "1");
  }

  function consumeForGame(gameId) {
    if (safeSessionGet("ss_duel_pending")) {
      safeSessionRemove("ss_duel_pending");
      safeSet("ss_duel_game_" + gameId, "1");
    }
  }

  function isDuelGame(gameId) {
    return !!safeGet("ss_duel_game_" + gameId);
  }

  function shownStages(gameId) {
    try {
      const raw = localStorage.getItem("ss_duel_tut_stages_" + gameId);
      return raw ? JSON.parse(raw) : [];
    } catch (err) { return []; }
  }

  function markStageShown(gameId, stage) {
    const stages = shownStages(gameId);
    if (!stages.includes(stage)) {
      stages.push(stage);
      safeSet("ss_duel_tut_stages_" + gameId, JSON.stringify(stages));
    }
  }

  function overlay() {
    let node = document.getElementById("duel-tutorial-overlay");
    if (!node) {
      node = document.createElement("div");
      node.id = "duel-tutorial-overlay";
      node.className = "overlay hidden";
      document.body.appendChild(node);
    }
    return node;
  }

  function closeOverlay() {
    overlay().classList.add("hidden");
    popupOpen = false;
  }

  function showStage(gameId, stage, onClosed) {
    const slide = STAGES[stage];
    if (!slide) { onClosed(); return; }
    popupOpen = true;
    markStageShown(gameId, stage);
    if (stage === 6 && window.API && typeof window.API.awardBadge === "function") {
      window.API.awardBadge("crossed_the_seas").catch(() => {});
    }
    const node = overlay();
    node.classList.remove("hidden");
    node.innerHTML = `
      <div class="picker" style="max-width:520px;text-align:left">
        <div style="text-align:center;font-size:44px">${slide.icon}</div>
        <h3 style="text-align:center">${slide.title}</h3>
        <div style="color:var(--ink);line-height:1.65;font-size:14.5px">${slide.body}</div>
        <div style="display:flex;justify-content:space-between;margin-top:16px;gap:10px">
          ${slide.skipLabel ? `<button class="btn ghost" id="dt-skip">${slide.skipLabel}</button>` : "<span></span>"}
          <button class="btn gold" id="dt-next">${stage === 6 ? "⚔ Set Sail!" : "Next →"}</button>
        </div>
      </div>`;
    document.getElementById("dt-skip")?.addEventListener("click", () => {
      markDone();
      closeOverlay();
      onClosed();
    });
    document.getElementById("dt-next").addEventListener("click", () => {
      closeOverlay();
      onClosed();
    });
  }

  function maybeShowForRound(gameId, view) {
    if (popupOpen || !gameId || !view) return;
    if (!isDuelGame(gameId) || isDone()) return;
    const shown = shownStages(gameId);
    const round = view.round_number || 1;
    for (const stage of STAGE_ORDER) {
      if (stage === 6) continue;
      if (shown.includes(stage)) continue;
      if (round >= STAGES[stage].minRound) {
        showStage(gameId, stage, () => {});
        return;
      }
    }
  }

  function maybeShowAtEndgame(gameId, view, onDone) {
    if (!gameId || !isDuelGame(gameId) || isDone()) { onDone(); return; }
    const shown = shownStages(gameId);
    const missing = STAGE_ORDER.filter((stage) => !shown.includes(stage));
    if (!missing.length) { onDone(); return; }
    let index = 0;
    const advance = () => {
      if (isDone() || index >= missing.length) { onDone(); return; }
      const stage = missing[index];
      index += 1;
      showStage(gameId, stage, advance);
    };
    advance();
  }

  window.DuelTutorial = { markPending, consumeForGame, isDuelGame, maybeShowForRound, maybeShowAtEndgame, reset };
})();
