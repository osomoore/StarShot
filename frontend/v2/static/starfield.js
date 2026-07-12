/* Parallax starfield + drifting nebula background. */
(function () {
  const canvas = document.getElementById("starfield");
  const ctx = canvas.getContext("2d");
  let stars = [];
  let width = 0, height = 0;

  function resize() {
    width = canvas.width = window.innerWidth;
    height = canvas.height = window.innerHeight;
    stars = [];
    const count = Math.floor((width * height) / 3800);
    for (let i = 0; i < count; i++) {
      const depth = Math.random();
      stars.push({
        x: Math.random() * width,
        y: Math.random() * height,
        r: 0.3 + depth * 1.5,
        speed: 0.02 + depth * 0.12,
        tw: Math.random() * Math.PI * 2,
        hue: Math.random() < 0.08 ? 38 : Math.random() < 0.5 ? 210 : 0,
      });
    }
  }

  function frame(t) {
    ctx.clearRect(0, 0, width, height);
    for (const star of stars) {
      star.x -= star.speed;
      if (star.x < -2) star.x = width + 2;
      const twinkle = 0.55 + 0.45 * Math.sin(t / 700 + star.tw);
      ctx.globalAlpha = twinkle * 0.9;
      ctx.fillStyle = star.hue ? `hsl(${star.hue} 70% 78%)` : "#dfe6ff";
      ctx.beginPath();
      ctx.arc(star.x, star.y, star.r, 0, Math.PI * 2);
      ctx.fill();
    }
    ctx.globalAlpha = 1;
    requestAnimationFrame(frame);
  }

  window.addEventListener("resize", resize);
  resize();
  requestAnimationFrame(frame);
})();
