/* StarShot v2 API client — thin fetch wrapper over /api/v2. */
(function () {
  async function call(path, options = {}) {
    const response = await fetch("/api/v2" + path, {
      headers: { "Content-Type": "application/json" },
      credentials: "same-origin",
      ...options,
    });
    let payload = null;
    try { payload = await response.json(); } catch (err) { /* non-JSON error body */ }
    if (!response.ok) {
      const error = new Error((payload && payload.detail) || `Request failed (${response.status})`);
      error.status = response.status;
      throw error;
    }
    return payload;
  }

  const get = (path) => call(path);
  const post = (path, body) => call(path, { method: "POST", body: JSON.stringify(body || {}) });

  window.API = {
    register: (username, password) => post("/auth/register", { username, password }),
    login: (username, password) => post("/auth/login", { username, password }),
    logout: () => post("/auth/logout"),
    me: () => get("/me"),
    leaderboard: () => get("/leaderboard"),
    submitFeedback: (body) => post("/feedback", body),
    clientEvent: (body) => fetch("/api/debug/client-event", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      credentials: "same-origin",
      keepalive: true,
      body: JSON.stringify(body || {}),
    }).catch(() => {}),
    lobby: () => get("/lobby"),
    queue: (action) => post("/lobby/queue", { action }),
    createMatch: (body) => post("/matches", body),
    bossDesigns: () => get("/boss-designs"),
    joinMatch: (id, body) => post(`/matches/${id}/join`, body),
    leaveMatch: (id) => post(`/matches/${id}/leave`),
    startMatch: (id) => post(`/matches/${id}/start`),
    abandonMatch: (id) => post(`/matches/${id}/abandon`),
    challenge: (username, activeExpansions = []) => post("/lobby/challenge", { username, active_expansions: activeExpansions }),
    respondChallenge: (id, accept) => post(`/lobby/challenge/${id}/respond`, { accept }),
    cancelChallenge: (id) => post(`/lobby/challenge/${id}/cancel`),
    gameView: (gameId, since) => get(`/games/${gameId}/view` + (since >= 0 ? `?since=${since}` : "")),
    debugLog: (gameId) => get(`/games/${gameId}/debug-log`),
    chooseCaptain: (gameId, captainId) => post(`/games/${gameId}/captain`, { captain_id: captainId }),
    submitOrders: (gameId, orders) => post(`/games/${gameId}/orders`, { orders }),
  };
})();
