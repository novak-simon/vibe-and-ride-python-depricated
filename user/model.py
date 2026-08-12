from dataclasses import dataclass
from typing import List

@dataclass(frozen=True)
class User:
    id: int = 0
    name: str = "User"
    genre_preferences: List[str] = ["pop", "rock"]