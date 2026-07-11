from __future__ import annotations

from contextlib import contextmanager
import json
import sqlite3
from collections.abc import Iterator
from pathlib import Path
from uuid import uuid4

from starshot.rules.models import GameState
from starshot.rules.serialization import state_from_dict, state_to_dict


class SQLiteGameStore:
    def __init__(self, db_path: Path | str) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def create_game(self, state: GameState) -> str:
        game_id = uuid4().hex
        payload = self._dumps(state)
        with self._connection() as connection:
            connection.execute(
                """
                INSERT INTO games (id, state_json, created_at, updated_at)
                VALUES (?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                """,
                (game_id, payload),
            )
            connection.executemany(
                """
                INSERT INTO game_events (game_id, event_index, event_type, event_json, created_at)
                VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
                """,
                [
                    (
                        game_id,
                        index,
                        event.get("type", "unknown"),
                        json.dumps(event, sort_keys=True),
                    )
                    for index, event in enumerate(state.event_log)
                ],
            )
        return game_id

    def load_game(self, game_id: str) -> GameState:
        with self._connection() as connection:
            row = connection.execute(
                "SELECT state_json FROM games WHERE id = ?",
                (game_id,),
            ).fetchone()
        if row is None:
            raise KeyError(f"Unknown game id: {game_id}")
        return state_from_dict(json.loads(row["state_json"]))

    def save_game(self, game_id: str, state: GameState) -> None:
        with self._connection() as connection:
            row = connection.execute(
                "SELECT state_json FROM games WHERE id = ?",
                (game_id,),
            ).fetchone()
            if row is None:
                raise KeyError(f"Unknown game id: {game_id}")

            old_state = state_from_dict(json.loads(row["state_json"]))
            old_event_count = len(old_state.event_log)
            new_events = state.event_log[old_event_count:]

            connection.execute(
                """
                UPDATE games
                SET state_json = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (self._dumps(state), game_id),
            )
            connection.executemany(
                """
                INSERT INTO game_events (game_id, event_index, event_type, event_json, created_at)
                VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
                """,
                [
                    (
                        game_id,
                        old_event_count + offset,
                        event.get("type", "unknown"),
                        json.dumps(event, sort_keys=True),
                    )
                    for offset, event in enumerate(new_events)
                ],
            )

    def list_games(self) -> list[dict]:
        with self._connection() as connection:
            rows = connection.execute(
                """
                SELECT id, created_at, updated_at, state_json
                FROM games
                ORDER BY updated_at DESC
                """
            ).fetchall()
        games = []
        for row in rows:
            state = state_from_dict(json.loads(row["state_json"]))
            games.append(
                {
                    "id": row["id"],
                    "created_at": row["created_at"],
                    "updated_at": row["updated_at"],
                    "round_number": state.round_number,
                    "phase": state.phase.value,
                    "deck_set_id": state.deck_set_id,
                    "players": list(state.players),
                }
            )
        return games

    def _initialize(self) -> None:
        with self._connection() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS games (
                    id TEXT PRIMARY KEY,
                    state_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS game_events (
                    game_id TEXT NOT NULL,
                    event_index INTEGER NOT NULL,
                    event_type TEXT NOT NULL,
                    event_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY (game_id, event_index),
                    FOREIGN KEY (game_id) REFERENCES games(id)
                )
                """
            )

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.db_path)
        connection.row_factory = sqlite3.Row
        return connection

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        connection = self._connect()
        try:
            yield connection
            connection.commit()
        finally:
            connection.close()

    def _dumps(self, state: GameState) -> str:
        return json.dumps(state_to_dict(state), sort_keys=True)
