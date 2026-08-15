from typing import Any


def _get(obj: Any, key: str, default=None):
    if obj is None:
        return default
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)

def _clamp01(x: float) -> float:
    """Returns value clamped between 0 and 1."""
    if x < 0.0:
        return 0.0
    elif x > 1.0:
        return 1.0
    return x

def _clamp02(x: float) -> float:
    """Returns value clamped between -1 and 1."""
    if x < -1.0:
        return -1.0
    elif x > 1.0:
        return 1.0
    return x