from __future__ import annotations

from typing import Any, Dict, List, Optional

from analysis.model import AudioAnalysis
from user.model import UserSongStats
from user.service import getCurrentUser
from database.methods import _effective_client, _extract_data, _get_table, _execute_query, _song_from_record, _song_stat_from_record

def get_stat_by_id(id: int, client: Any | None = None) -> Optional[UserSongStats]:
    client = _effective_client(client)
    response = (
        client.table("user_song_stats")
        .select("*")
        .eq("id", id)
        .limit(1)
        .execute()
    )
    records = _extract_data(response)
    return _song_stat_from_record(records[0]) if records else None

def get_stat_by_user_and_song_id(user_id: int, song_id: int, client: Any | None = None) -> Optional[UserSongStats]:
    client = _effective_client(client)
    response = (
        client.table("user_song_stats")
        .select("*")
        .eq("song_id", song_id)
        .eq("user_id", user_id)
        .limit(1)
        .execute()
    )
    records = _extract_data(response)
    return _song_stat_from_record(records[0]) if records else None

def get_stats_by_user_id(user_id: int, limit: int = 50, client: Any | None = None) -> List[UserSongStats]:
    """
    Returns user_song_stats records from database that correspond to a certain user.
    Limit is 50 records by default, can be set to anything.
    If limit is set to None, all existing records will be returned.
    """
    client = _effective_client(client)
    if limit is None:
        response = (
            client.table("user_song_stats")
            .select("*")
            .eq("user_id", user_id)
            .execute()
            )
    else:
        response = (
            client.table("user_song_stats")
            .select("*")
            .eq("user_id", user_id)
            .limit(limit)
            .execute()
        )
    records = _extract_data(response)
    return [_song_stat_from_record(record) for record in records]

def increment_skip_count(song_id: int, user_id: int | None = None, client: Any | None = None) -> Optional[UserSongStats]:
    """
    Increments `skip_count` for the given song for the current user or provided user.
    If no stat row exists yet, creates one with skip_count = 1.
    """
    client = _effective_client(client)

    if user_id is None:
        user_id = getCurrentUser().id

    existing = get_stat_by_user_and_song_id(user_id, song_id, client=client)
    if existing is None:
        response = (
            client.table("user_song_stats")
            .insert({
                "user_id": user_id,
                "song_id": song_id,
                "skip_count": 1,
            })
            .execute()
        )
        records = _extract_data(response)
        return _song_stat_from_record(records[0]) if records else None

    new_skip_count = (getattr(existing, "skip_count", 0) or 0) + 1
    response = (
        client.table("user_song_stats")
        .update({"skip_count": new_skip_count})
        .eq("user_id", user_id)
        .eq("song_id", song_id)
        .execute()
    )
    records = _extract_data(response)
    return _song_stat_from_record(records[0]) if records else None