from __future__ import annotations

from typing import Any, Dict, List, Optional

from analysis.model import AudioAnalysis
from music.model import Song
from dotenv import load_dotenv
from database.methods import _effective_client, _extract_data

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


def get_songs_needing_analysis(
    client: Any | None = None,
    limit: Optional[int] = None,
) -> List[Song]:
    client = _effective_client(client)
    query = (
        client.table("songs")
        .select("*")
        .not_("audio_url", "is", None)
        .neq("audio_url", "")
        .is_("bpm", "is", None)
    )
    if limit is not None:
        query = query.limit(limit)
    rows = _extract_data(query.execute())
    return [_song_from_record(row) for row in rows]


def _normalize_bpm_for_db(bpm: float | int | None) -> int | None:
    if bpm is None:
        return None
    return int(round(float(bpm)))


def _normalize_confidence_for_db(confidence: float | int | None) -> int | None:
    if confidence is None:
        return None
    return int(round(1000 * float(confidence)))


def update_song_analysis(
    song_id: Optional[int] = None,
    jamendo_id: Optional[str] = None,
    bpm: float = 0.0,
    bpm_confidence: float = 0.0,
    beats: Optional[List[float]] = None,
    bpm_estimates: Optional[List[float]] = None,
    beat_intervals: Optional[List[float]] = None,
    client: Any | None = None,
) -> Song:
    if song_id is None and not jamendo_id:
        raise ValueError("song_id or jamendo_id is required to update analysis")

    client = _effective_client(client)
    payload = {
        "bpm": _normalize_bpm_for_db(bpm),
        "bpm_confidence": bpm_confidence,
        "beats": beats,
        "bpm_estimates": bpm_estimates,
        "beat_intervals": beat_intervals,
    }

    query = client.table("songs").update(payload)
    if song_id is not None:
        query = query.eq("id", song_id)
    else:
        query = query.eq("jamendo_id", jamendo_id)

    rows = _extract_data(query.select("*").execute())
    if not rows:
        raise RuntimeError("Failed to update song analysis")
    return _song_from_record(rows[0])


def _get_table(client):
    table_method = getattr(client, "table", None) or getattr(client, "from_", None)
    if table_method is None:
        raise AttributeError("Supabase client must expose table() or from_()")
    return table_method("songs")


def _execute_query(query):
    response = query.execute()
    if isinstance(response, dict):
        error = response.get("error")
        data = response.get("data", [])
    else:
        error = getattr(response, "error", None)
        data = getattr(response, "data", [])
    if error:
        raise RuntimeError(f"Supabase error: {error}")
    return data or []


def fetch_unanalyzed_songs(client, limit: int = 50) -> List[Song]:
    table = _get_table(client)
    try:
        query = (
            table.select("*")
            .or_("bpm.is.null,beats.is.null,beat_intervals.is.null")
            .limit(limit)
        )
        rows = _execute_query(query)
    except Exception:
        fallback_limit = max(limit * 4, 100)
        rows = _execute_query(table.select("*").limit(fallback_limit))
        rows = [
            row
            for row in rows
            if row.get("bpm") is None
            or row.get("beats") is None
            or row.get("beat_intervals") is None
        ][:limit]

    return [Song.from_dict(row) for row in rows]


def update_song_analysis(client, song_id: int, analysis: AudioAnalysis) -> None:
    table = _get_table(client)
    record: Dict[str, Any] = {
        "bpm": _normalize_bpm_for_db(analysis.bpm),
        "beats": analysis.beats,
        "beat_intervals": analysis.beat_intervals,
        "bpm_confidence": _normalize_confidence_for_db(
            analysis.bpm_confidence
        ),
    }
    query = table.update(record).eq("id", song_id)
    _execute_query(query)