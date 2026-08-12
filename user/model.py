from dataclasses import dataclass, field
from typing import List, Dict, Any

from helper_methods.model_methods import _optional_str, _optional_int_or_none, _optional_int, _optional_float_list, _str_to_list

@dataclass(frozen=True)
class User:
    id: int = 0
    name: str = "User"
    genre_preferences: List[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "User":
        return cls(
            id=_optional_int_or_none(data.get("id")),
            name=_optional_str(data.get("name")),
            genre_preferences=_str_to_list(_optional_str(data.get("genre_preferences"))),
        )

    def to_record(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "genre_preferences": self.genre_preferences,
        }