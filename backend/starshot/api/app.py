from __future__ import annotations

from fastapi import FastAPI
from pydantic import BaseModel, Field

from starshot.rules import GameConfig, create_initial_state

app = FastAPI(title="StarShot")


class CreateGameRequest(BaseModel):
    player_ids: list[str] = Field(min_length=2, max_length=4)
    seed: int | None = None


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/api/games")
def create_game(request: CreateGameRequest) -> dict:
    state = create_initial_state(GameConfig(player_ids=tuple(request.player_ids), seed=request.seed))
    return {
        "round": state.round_number,
        "phase": state.phase,
        "starting_player_id": state.starting_player_id,
        "players": list(state.players),
    }
