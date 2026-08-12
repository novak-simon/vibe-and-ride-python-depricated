"""
Minimal deterministic recommendation engine for Zwift Music.

Design:
- CadenceResolver: get_target_cadence / estimate_cadence_from_power
- GenreFilter: USER_GENRES (hardcoded)
- BPMMatcher: calculate_bpm_match (considers half/double (×0.5, ×1, ×2))
- RecommendationRanker: ranks by bpm_confidence, then bpm_difference, then song id

Notes:
- Works with song objects that are either dict-like or attribute objects.
- Does not couple with Supabase; accepts a list of song candidates.
- BPM tolerance is absolute in BPM (BPM_TOLERANCE). Change to tune behavior.
"""
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any, List, Optional, Sequence
import logging

from workout.model import Interval
from music.model import Song
from user.model import User
from user.service import getCurrentUser
from database.songs import get_songs_around_target, fetch_songs
from database.admin_client import create_admin_supabase



logger = logging.getLogger(__name__)

# === Configuration ===
USER_GENRES = [
    "electronic",
    "rock",
    "pop",
]

admin_client = create_admin_supabase()

# Absolute BPM tolerance used when comparing effective BPM to target cadence.
# Initial sensible value: 4 BPM (allows small tempo detection noise while keeping selectivity).
BPM_TOLERANCE = 4.0

# === Models ===
@dataclass(frozen=True)
class BPMMatch:
    compatible: bool
    effective_bpm: Optional[float]
    difference: Optional[float]
    multiplier: Optional[float]  # 0.5, 1, 2


@dataclass(frozen=True)
class Recommendation:
    song: Any
    song_bpm: Optional[float]
    bpm_confidence: Optional[float]
    target_cadence: Optional[float]
    effective_bpm: Optional[float]
    bpm_difference: Optional[float]
    tempo_multiplier: Optional[float]


# === Utilities to access song/interval fields flexibly ===
def _get(obj: Any, key: str, default=None):
    if obj is None:
        return default
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)

# === Genre filter ===
def song_matches_user_genres(song: Any, user_genres: Sequence[str] = USER_GENRES) -> bool:
    """
    Accept song if at least one of its genres matches a user genre.
    Handles:
      - song.genre as single string
      - song.genres as list/sequence
    """
    g = _get(song, "genre", None)
    if g is None:
        g = _get(song, "genres", None)
    if g is None:
        return False
    if isinstance(g, str):
        if g.lower() in {ug.lower() for ug in user_genres}:
            return True
        return False
    try:
        for gg in g:
            if isinstance(gg, str) and gg.lower() in {ug.lower() for ug in user_genres}:
                return True
    except Exception:
        return False
    return False


# === BPM matching (including half/double tempo handling) ===
def calculate_bpm_match(song_bpm: Optional[float], target_cadence: Optional[float]) -> BPMMatch:
    """
    For a given song BPM and target cadence, evaluate compatibility.
    Considers multipliers [0.5, 1, 2] applied to song_bpm to find best effective BPM
    that is closest to target_cadence. Returns BPMMatch with compatibility and details.

    Compatibility rule: absolute difference <= BPM_TOLERANCE
    """
    if song_bpm is None or target_cadence is None:
        return BPMMatch(False, None, None, None)
    try:
        sb = float(song_bpm)
    except Exception:
        return BPMMatch(False, None, None, None)

    best_mult = None
    best_eff = None
    best_diff = None
    for mult in (0.5, 1.0, 2.0):
        eff = sb * mult
        diff = abs(eff - target_cadence)
        if best_diff is None or diff < best_diff:
            best_diff = diff
            best_eff = eff
            best_mult = mult
    compatible = best_diff is not None and best_diff <= BPM_TOLERANCE
    return BPMMatch(compatible=compatible, effective_bpm=best_eff, difference=best_diff, multiplier=best_mult)
def get_algorithm_cadence(cadence: int) -> int:
    """Normalize cadence to 60-120 range using half/double multipliers."""
    max_iterations = 20  # Prevent infinite loops
    iterations = 0
    while cadence not in range(60, 121) and iterations < max_iterations:
        if cadence < 60:
            cadence *= 2
        else:
            cadence //= 2
        iterations += 1
    if iterations >= max_iterations:
        logger.warning("Could not normalize cadence %s to 60-120 range", cadence)
        return 120  # Fallback
    return cadence


# === Parts of Recommendation engine ===
def approximate_filter_by_interval(interval: Interval) -> List[Song]:
    print(f"Power: {interval.power}, Cadence: {interval.cadence}")
    interval_algorithm_cadence = get_algorithm_cadence(interval.cadence)
    interval_algorithm_power = interval.power*100 if not interval.power is None else 60
    pool = get_songs_around_target(admin_client, interval_algorithm_cadence, interval_algorithm_power, limit=10)
    if pool:
        return pool
    else:   #Try to get songs that don't match that well, if it fails, gets at least some songs
        pool = get_songs_around_target(admin_client, interval_algorithm_cadence, interval_algorithm_power, 10, 0.2, limit=10)
        if pool:
            return pool
        else:
            pool = fetch_songs(admin_client)
            return pool


def rank_by_user_preference(songs: List[Song], user: User) -> List[Song]:
    """Filter songs by user genre preference."""
    if user is None or not songs:
        return songs
    return [s for s in songs if song_matches_user_genres(s, user.genres if hasattr(user, 'genres') else USER_GENRES)]


def rank_by_interval_match(songs: List[Song], interval: Interval) -> List[Recommendation]:
    """Rank songs by BPM compatibility with interval target cadence."""
    if not songs or interval.cadence is None:
        return []
    
    recommendations = []
    for song in songs:
        sbpm = _get(song, "bpm", None)
        if sbpm is None:
            continue
        match = calculate_bpm_match(sbpm, interval.cadence)
        if not match.compatible:
            continue
        conf = _get(song, "bpm_confidence", None)
        recommendations.append((song, sbpm, conf, match))
    
    # Sort by confidence (desc), then by BPM difference (asc), then by song id
    def sort_key(entry):
        s, sbpm, conf, match = entry
        has_conf = 1 if conf is not None else 0
        conf_val = float(conf) if conf is not None else 0.0
        diff_val = float(match.difference) if match.difference is not None else float("inf")
        sid = _get(s, "id", None) or str(s)
        return (-has_conf, -conf_val, diff_val, str(sid))
    
    recommendations.sort(key=sort_key)
    
    return [
        Recommendation(
            song=s,
            song_bpm=float(sbpm) if sbpm is not None else None,
            bpm_confidence=float(conf) if conf is not None else None,
            target_cadence=interval.cadence,
            effective_bpm=match.effective_bpm,
            bpm_difference=match.difference,
            tempo_multiplier=match.multiplier,
        )
        for s, sbpm, conf, match in recommendations
    ]


# === Recommendation engine ===
def recommend(interval: Interval, limit: int = 10, user_genres: Sequence[str] = USER_GENRES) -> List[Recommendation]:
    """
    Recommend a ranked list of songs for a given workout interval.
    """
    target_cadence = interval.cadence
    logger.info("Recommendation request: interval=%s => target_cadence=%s", getattr(interval, "__dict__", str(interval)), target_cadence)

    if target_cadence is None:
        logger.info("No target cadence could be determined for interval; returning empty recommendations.")
        return []
    
    user = getCurrentUser()
    first_candidate_pool = approximate_filter_by_interval(interval)
    second_candidate_pool = rank_by_user_preference(first_candidate_pool, user)
    third_candidate_pool = rank_by_interval_match(second_candidate_pool, interval)
    
    return third_candidate_pool[:limit]