from typing import Any, Optional, List
import ast

def _optional_str(value: Any) -> Optional[str]:
    if value is None:
        return None
    return str(value)


def _optional_int(value: Any, default: int = 0) -> int:
    if value is None:
        return default
    return int(value)


def _optional_int_or_none(value: Any) -> Optional[int]:
    if value is None:
        return None
    return int(value)


def _optional_float_list(value: Any) -> Optional[List[float]]:
    if value is None:
        return None
    if isinstance(value, list):
        return [float(item) for item in value]
    return [float(item) for item in list(value)]

def _str_to_list(value: str) -> List:
    if value is None:
        return []
    return ast.literal_eval(value)