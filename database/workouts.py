from __future__ import annotations

from typing import Any, List, Optional, TYPE_CHECKING, Union
from database.methods import _extract_data, _effective_client

import supabase

if TYPE_CHECKING:
    from workout.parser import ZwoNode


def _is_bike_sport(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    try:
        return int(value) == 1
    except (TypeError, ValueError):
        pass
    return str(value).strip().lower() in {"bike", "bicycle", "cycling", "true", "yes", "1"}

def name_exists(name: str, client: Any | None = None) -> bool:
    client = _effective_client(client)
    response = (
        client.table("workouts")
        .select("id")
        .eq("name", name)
        .limit(1)
        .execute()
    )
    return bool(_extract_data(response))

def upload_parsed_file(parsedFile: Union["ZwoNode", List["ZwoNode"]], client: Any | None = None) -> List[dict[str, Any]]:
    client = _effective_client(client)

    items: List[dict[str, Any]]
    if isinstance(parsedFile, list):
        items = [item for item in parsedFile if isinstance(item, dict)]
    elif isinstance(parsedFile, dict):
        items = [parsedFile]
    else:
        raise ValueError("Parsed workout must be a dict or list of dicts")
    
    inserted_records = []
    for item in items:
        record = {
            "name": item.get("children")[1].get("text"),
            "author": item.get("children")[0].get("text"),
            "sport_type_is_bike": _is_bike_sport(item.get("children")[3].get("text")),
            "parsed_workout": item,
        }

        if name_exists(record.get("name"), client=client):
            return

        response = (
            client.table("workouts")
            .insert(record)
            .select("*")
            .execute()
        )
        rows = _extract_data(response)
        if not rows:
            raise RuntimeError("Failed to upload workout")
        inserted_records.append(rows[0])

    return inserted_records

# Added: helper functions to read workouts from the database.
def list_workouts(client: Any | None = None) -> List[dict[str, Any]]:
    """
    Return list of workout rows from the 'workouts' table.
    """
    client = _effective_client(client)
    response = client.table("workouts").select("*").order("id", desc=False).execute()
    rows = _extract_data(response)
    return rows or []

def get_workout_by_id(record_id: Any, client: Any | None = None) -> Optional[dict[str, Any]]:
    """
    Return single workout row by id or None if not found.
    """
    client = _effective_client(client)
    response = client.table("workouts").select("*").eq("id", record_id).limit(1).execute()
    rows = _extract_data(response)
    if not rows:
        return None
    return rows[0]