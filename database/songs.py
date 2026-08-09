from __future__ import annotations

from typing import Any, List, Optional

from database.methods import _effective_client, _extract_data

from music.model import Song
import supabase

def _song_from_record(record: dict[str, Any]) -> Song:
    return Song.from_dict(record)


def get_song_by_jamendo_id(
    jamendo_id: str, client: Any | None = None
) -> Optional[Song]:
    client = _effective_client(client)
    response = (
        client.table("songs")
        .select("*")
        .eq("jamendo_id", jamendo_id)
        .limit(1)
        .execute()
    )
    records = _extract_data(response)
    return _song_from_record(records[0]) if records else None


def jamendo_id_exists(jamendo_id: str, client: Any | None = None) -> bool:
    client = _effective_client(client)
    response = (
        client.table("songs")
        .select("id")
        .eq("jamendo_id", jamendo_id)
        .limit(1)
        .execute()
    )
    return bool(_extract_data(response))


def add_song(song: Song, client: Any | None = None) -> Song:
    if not song.jamendo_id:
        raise ValueError("Song must have a jamendo_id")

    client = _effective_client(client)

    if jamendo_id_exists(song.jamendo_id, client=client):
        raise ValueError(f"Song with jamendo_id={song.jamendo_id} already exists")

    response = (
        client.table("songs")
        .insert(song.to_record())
        .select("*")
        .execute()
    )
    records = _extract_data(response)
    if not records:
        raise RuntimeError("Failed to insert song")

    return _song_from_record(records[0])


def get_songs(
    limit: int = 100, offset: int = 0, client: Any | None = None
) -> List[Song]:
    client = _effective_client(client)
    response = (
        client.table("songs")
        .select("*")
        .limit(limit)
        .offset(offset)
        .execute()
    )
    return [_song_from_record(record) for record in _extract_data(response)]


def get_playable_songs(client: Any) -> List[Song]:
    query = (
        client.table("songs")
        .select("*")
    )
    result = query.execute()
    if isinstance(result, dict):
        rows = result.get("data", [])
    else:
        rows = getattr(result, "data", []) or []

    return [Song.from_dict(row) for row in rows]