/* New-captain tutorial: optional slide walkthrough of the rules. */
(function () {
  const SLIDES = [
    {
      icon: "🏴‍☠", title: "Welcome aboard, Captain!",
      body: `StarShot is a battle of <b>void corsairs</b>. Plunder vaults, outfly rivals, and blast
        their ships to scrap. <b>Most Victory Points after 6 rounds wins</b> — or be the last ship
        flying and take it all early.`,
    },
    {
      icon: "🗺", title: "How a round works",
      body: `Every round, all captains <b>secretly plan three Actions</b> at the same time. When everyone
        has sealed their orders, the round plays out automatically: Action I, II, III — in each one,
        <b>all ships move simultaneously</b>, then volleys fire. Watch the replay to see how your plan
        collided with theirs.`,
    },
    {
      icon: "🂠", title: "Your hand and the three stacks",
      body: `You draw <b>5 cards</b> (6 once your shields are gone). Load <b>up to two cards</b>
        into each Action stack, so click, drag, or click a stack first and then
        pick its cards. Leftover cards go to your discard, and your discard shuffles back in when your
        deck runs dry — nothing is lost forever.`,
    },
    {
      icon: "🔥", title: "Sealed… or OVERDRIVE",
      body: `Each stack is covered <b>Sealed</b> (runs once) or flipped to <b>Overdrive</b> — cards in the
        order stack are doubled! The price: you lose a draw next round.
        Overdrive a sure shot or a long burn, not a gamble.`,
    },
    {
      icon: "➤", title: "Flying your ship",
      body: `Move cards turn <b>then</b> move — pick Ahead, Port, or Starboard when you place the card.
        The dashed <b>preview path</b> on the board shows exactly where you'll end each Action. Bonus:
        distance flown this Action is added to your defense, so a moving ship is a hard target.
        <br><br><i>In StarBreach, ships can fly past enemies, but if an Action would end exactly on an enemy ship,
        it stops one tile short instead.</i>`,
    },
    {
      icon: "☄", title: "Firing your cannons",
      body: `All attack cards in one stack combine into <b>one volley at one target</b>. To hit, roll
        <b>2d6 + Aim ≥ distance + the target's movement this Action + their defense</b>. The preview
        arrow shows your <b>predicted hit chance</b> before you commit. Two attack cards don't fire twice —
        they stack bonuses like <b>Damage +1</b> or <b>Aim +1</b> into one bigger broadside.`,
    },
    {
      icon: "🛡", title: "Shields and the d12 damage lanes",
      body: `You start with <b>2 shield charges</b>. One charge blocks ALL damage for that entire Action
        step — but each attacker still gains <b>1 VP</b>. Once shields are gone, every hit rolls a
        <b>d12 damage lane</b>: the shot bores into your ship and destroys the first intact part in that
        lane. Lose your <b>Command Bridge</b> or <b>both Life Supports</b> and you're space dust.
        <br><br><i>Click any ship in the Fleet Registry to study its board and lanes.</i>`,
    },
    {
      icon: "✦", title: "Vaults — the loot",
      body: `Numbered vaults pay out in their matching round: end the round <b>anywhere in the glowing
        7-hex cluster</b> and claim the 2 VP <b>plus a Desperation card</b>. The central <b>Fang</b> is
        active every round — it bites for 1 damage, pays 1 VP… but in round 6 it's worth <b>6 VP</b>.
        Round 6 near the Fang is a knife fight.`,
    },
    {
      icon: "☄", title: "Desperation cards",
      body: `Loot and battle damage feed you <b>Desperation cards</b> — two-faced monsters. Most Desperation
        card faces have a basic face - a solid hybrid (move or +damage). The purple <b>DESPERATE face</b> is a single-use
        haymaker: Move 8, guaranteed hits, wild maneuvers. Once spent, it returns to the shared deck.
        Timing one perfectly wins games.`,
    },
    {
      icon: "⚔", title: "Ready to fly, Captain?",
      body: `<b>Quick Duel</b> finds you a live opponent. <b>Choose your battles</b> lets you battle up to three
        Digital Scallywags — the Freebooter chases loot, the Bloodthirsty hunts one prey, the Cannoneer shoots whatever's close.
        Win battles to climb the leaderboard. Fair winds and full broadsides!`,
    },
  ];

  let index = 0;

  function overlay() {
    let node = document.getElementById("tutorial-overlay");
    if (!node) {
      node = document.createElement("div");
      node.id = "tutorial-overlay";
      node.className = "overlay hidden";
      document.body.appendChild(node);
    }
    return node;
  }

  function render() {
    const slide = SLIDES[index];
    const node = overlay();
    node.classList.remove("hidden");
    node.innerHTML = `
      <div class="picker" style="max-width:560px;text-align:left">
        <div style="text-align:center;font-size:44px">${slide.icon}</div>
        <h3 style="text-align:center">${slide.title}</h3>
        <div style="color:var(--ink);line-height:1.65;font-size:14.5px">${slide.body}</div>
        <div style="text-align:center;margin:16px 0 4px;color:var(--gold)">
          ${SLIDES.map((_, i) => i === index ? "●" : "○").join(" ")}
        </div>
        <div style="display:flex;justify-content:space-between;margin-top:10px">
          <button class="btn ghost" id="tut-skip">Skip the tour</button>
          <div>
            <button class="btn ghost" id="tut-back" ${index === 0 ? "disabled" : ""}>← Back</button>
            <button class="btn gold" id="tut-next">${index === SLIDES.length - 1 ? "⚔ Set Sail!" : "Next →"}</button>
          </div>
        </div>
      </div>`;
    document.getElementById("tut-skip").addEventListener("click", close);
    document.getElementById("tut-back").addEventListener("click", () => { if (index > 0) { index--; render(); } });
    document.getElementById("tut-next").addEventListener("click", () => {
      if (index >= SLIDES.length - 1) close();
      else { index++; render(); }
    });
  }

  function close() {
    overlay().classList.add("hidden");
    try { localStorage.setItem("ss_tutorial_done", "1"); } catch (err) {}
  }

  function start() { index = 0; render(); }

  /* First visit after signing in: offer the tour once, unobtrusively. */
  function offerIfNew() {
    let done = null;
    try { done = localStorage.getItem("ss_tutorial_done"); } catch (err) {}
    if (done) return;
    const node = overlay();
    node.classList.remove("hidden");
    node.innerHTML = `
      <div class="picker" style="max-width:440px">
        <div style="font-size:44px">🧭</div>
        <h3>First time aboard?</h3>
        <div style="color:var(--ink-dim);line-height:1.6">Take a two-minute tour of the rules —
          rounds, orders, overdrive, cannons, and loot. You can rerun it any time from
          <b>📖 How to Play</b> in the lobby.</div>
        <div style="display:flex;gap:10px;justify-content:center;margin-top:18px">
          <button class="btn gold big" id="tut-yes">📖 Take the tour</button>
          <button class="btn ghost" id="tut-no">I know the ropes</button>
        </div>
      </div>`;
    document.getElementById("tut-yes").addEventListener("click", start);
    document.getElementById("tut-no").addEventListener("click", close);
  }

  window.Tutorial = { start, offerIfNew };
})();
