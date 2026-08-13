from __future__ import annotations

from typing import Any, Dict, List, Optional

from analysis.model import AudioAnalysis
from user.model import UserSongStats
from database.methods import _effective_client, _extract_data, _get_table, _execute_query, _song_from_record

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
    return _song_from_record(records[0]) if records else None

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
    return _song_from_record(records[0]) if records else None

def get_stats_by_user_id(user_id: int, limit: int = 50, client: Any | None = None) -> Optional[UserSongStats]:
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
    return _song_from_record(records[0]) if records else None