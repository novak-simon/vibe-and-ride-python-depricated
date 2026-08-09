from typing import Any, List

import supabase

def _effective_client(client: Any | None) -> Any:
    return client if client is not None else supabase

def _extract_data(response: Any) -> List[dict[str, Any]]:
    if isinstance(response, dict):
        data = response.get("data")
    else:
        data = getattr(response, "data", None)

    if data is None:
        raise RuntimeError("Unexpected Supabase response: missing data")

    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        return [data]

    raise RuntimeError("Unexpected Supabase data shape")
