/* Canvas battle effects over the board: lasers, explosions, shields, trails. */
(function () {
  const canvas = document.getElementById("fx");
  const wrap = document.getElementById("board-wrap");
  const ctx = canvas.getContext("2d");
  let particles = [];
  let beams = [];
  let flashes = [];
  let floats = [];

  function resize() {
    const rect = wrap.getBoundingClientRect();
    canvas.width = rect.width;
    canvas.height = rect.height;
  }
  window.addEventListener("resize", resize);
  new ResizeObserver(resize).observe(wrap);

  function frame() {
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    const now = performance.now();

    beams = beams.filter((beam) => now < beam.until);
    for (const beam of beams) {
      const life = 1 - (beam.until - now) / beam.duration;
      const head = Math.min(1, life * 2.2);
      const tail = Math.max(0, life * 2.2 - 0.35);
      const x1 = beam.x1 + (beam.x2 - beam.x1) * tail;
      const y1 = beam.y1 + (beam.y2 - beam.y1) * tail;
      const x2 = beam.x1 + (beam.x2 - beam.x1) * head;
      const y2 = beam.y1 + (beam.y2 - beam.y1) * head;
      ctx.save();
      ctx.globalCompositeOperation = "lighter";
      ctx.strokeStyle = beam.color;
      ctx.shadowColor = beam.color;
      ctx.shadowBlur = 14;
      ctx.lineWidth = 3.2;
      ctx.beginPath(); ctx.moveTo(x1, y1); ctx.lineTo(x2, y2); ctx.stroke();
      ctx.lineWidth = 1.2;
      ctx.strokeStyle = "#fff";
      ctx.beginPath(); ctx.moveTo(x1, y1); ctx.lineTo(x2, y2); ctx.stroke();
      ctx.restore();
    }

    particles = particles.filter((p) => now < p.until);
    for (const p of particles) {
      const life = (p.until - now) / p.duration;
      p.x += p.vx; p.y += p.vy;
      p.vx *= 0.97; p.vy *= 0.97;
      p.vy += p.gravity || 0;
      ctx.save();
      ctx.globalCompositeOperation = "lighter";
      ctx.globalAlpha = Math.max(0, life);
      ctx.fillStyle = p.color;
      ctx.beginPath();
      ctx.arc(p.x, p.y, p.r * life, 0, Math.PI * 2);
      ctx.fill();
      ctx.restore();
    }

    flashes = flashes.filter((f) => now < f.until);
    for (const f of flashes) {
      const life = (f.until - now) / f.duration;
      ctx.save();
      ctx.globalCompositeOperation = "lighter";
      const grad = ctx.createRadialGradient(f.x, f.y, 0, f.x, f.y, f.r * (1.4 - life * 0.4));
      grad.addColorStop(0, f.color.replace("ALPHA", (life * 0.85).toFixed(2)));
      grad.addColorStop(1, f.color.replace("ALPHA", "0"));
      ctx.fillStyle = grad;
      ctx.beginPath();
      ctx.arc(f.x, f.y, f.r * 1.6, 0, Math.PI * 2);
      ctx.fill();
      ctx.restore();
    }

    floats = floats.filter((f) => now < f.until);
    for (const f of floats) {
      const life = (f.until - now) / f.duration;
      ctx.save();
      ctx.globalAlpha = Math.min(1, life * 2);
      ctx.font = `700 ${f.size}px "Space Grotesk", sans-serif`;
      ctx.textAlign = "center";
      ctx.shadowColor = "#000";
      ctx.shadowBlur = 5;
      ctx.fillStyle = f.color;
      ctx.fillText(f.text, f.x, f.y - (1 - life) * 34);
      ctx.restore();
    }
    requestAnimationFrame(frame);
  }

  function burst(x, y, color, count, speed, size, duration, gravity) {
    const now = performance.now();
    for (let i = 0; i < count; i++) {
      const angle = Math.random() * Math.PI * 2;
      const velocity = (0.3 + Math.random()) * speed;
      particles.push({
        x, y,
        vx: Math.cos(angle) * velocity,
        vy: Math.sin(angle) * velocity,
        r: size * (0.5 + Math.random()),
        color, duration,
        until: now + duration * (0.6 + Math.random() * 0.6),
        gravity,
      });
    }
  }

  const FX = {
    laser(from, to, color = "#ff5340") {
      const now = performance.now();
      beams.push({ x1: from.x, y1: from.y, x2: to.x, y2: to.y, color, duration: 420, until: now + 420 });
      burst(from.x, from.y, color, 6, 1.6, 2, 360);
    },
    impact(at, big) {
      burst(at.x, at.y, "#ffcf6a", big ? 42 : 18, big ? 3.4 : 2.2, 2.6, big ? 900 : 550);
      burst(at.x, at.y, "#ff6a3c", big ? 30 : 12, big ? 2.6 : 1.8, 3, big ? 800 : 500);
      flashes.push({ x: at.x, y: at.y, r: big ? 46 : 24, color: "rgba(255,190,90,ALPHA)", duration: big ? 500 : 300, until: performance.now() + (big ? 500 : 300) });
    },
    miss(at) {
      burst(at.x, at.y, "#8fa3c8", 8, 1.5, 1.6, 420);
      FX.floatText(at, "MISS", "#9fb2d8", 13);
    },
    shield(at) {
      flashes.push({ x: at.x, y: at.y, r: 34, color: "rgba(80,190,255,ALPHA)", duration: 600, until: performance.now() + 600 });
      burst(at.x, at.y, "#5ec8ff", 22, 2.2, 2, 650);
    },
    explosion(at) {
      burst(at.x, at.y, "#ffd97a", 70, 4.2, 3.2, 1300);
      burst(at.x, at.y, "#ff5330", 50, 3.2, 4, 1200);
      burst(at.x, at.y, "#88919f", 34, 2.2, 2.4, 1700, 0.02);
      flashes.push({ x: at.x, y: at.y, r: 70, color: "rgba(255,160,60,ALPHA)", duration: 800, until: performance.now() + 800 });
      wrap.classList.remove("shake");
      void wrap.offsetWidth;
      wrap.classList.add("shake");
    },
    warp(at) {
      flashes.push({ x: at.x, y: at.y, r: 40, color: "rgba(160,110,255,ALPHA)", duration: 700, until: performance.now() + 700 });
      burst(at.x, at.y, "#b58cff", 30, 3, 2.2, 800);
    },
    trail(at, color) {
      burst(at.x, at.y, color || "#7ecbff", 3, 0.7, 1.7, 480);
    },
    loot(at) {
      burst(at.x, at.y, "#ffd76a", 26, 2.4, 2.2, 900, -0.015);
      FX.floatText(at, "✦ LOOT ✦", "#ffd76a", 15);
    },
    floatText(at, text, color, size = 14) {
      floats.push({ x: at.x, y: at.y - 14, text, color, size, duration: 1400, until: performance.now() + 1400 });
    },
  };

  window.FX = FX;
  resize();
  requestAnimationFrame(frame);
})();
