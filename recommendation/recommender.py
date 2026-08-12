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
import ast

from workout.model import Interval
from music.model import Song
from user.model import User
from user.service import getCurrentUser



logger = logging.getLogger(__name__)

# === Configuration ===
USER_GENRES = [
    "electronic",
    "rock",
    "pop",
]

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

def _genre_to_list(genre):
    if genre is None:
        return []
    return ast.literal_eval(genre)


# === Cadence resolution ===
def estimate_cadence_from_power(power: float, interval_context: Optional[Any] = None) -> Optional[float]:
    """
    Simple documented approximation mapping power -> cadence (fallback).
    Formula (first minimal implementation):
      max(75, min(115, 70 + 30 * p))
    Clamped to [75, 115] RPM.

    Rationale: 80 RPM is a reasonable mid-point for many structured workouts.
    This is only a heuristic fallback for intervals that specify power but not cadence.
    """
    try:
        p = float(power)
    except Exception:
        return 80 #Default cadence value if there is literally no information
    cadence = max(75, min(115, 70 + 30 * p))
    logger.debug("estimate_cadence_from_power: power=%s -> cadence=%.2f", power, cadence)
    return cadence


def get_target_cadence(interval: Any) -> Optional[float]:
    """
    Resolve target cadence for a workout interval.
    Priority:
      1. explicit interval.cadence
      2. estimate from interval.power (using estimate_cadence_from_power)
      3. None
    """
    cadence = _get(interval, "cadence", None)
    if cadence is not None:
        try:
            return float(cadence)
        except Exception:
            return None
    power = _get(interval, "power", None)
    if power is not None:
        return estimate_cadence_from_power(power, interval)
    return None


# === Genre filter ===
def song_matches_user_genres(song: Any, user_genres: Sequence[str] = USER_GENRES) -> bool:
    """
    Accept song if at least one of its genres matches a user genre.
    Handles:
      - song.genre as single string
      - song.genres as list/sequence
    """
    g = _get(song, "genre", None)
    g = _genre_to_list(g)
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

# === Parts of Recommendation engine ===
def approximate_filter_by_interval(songs: List[Song], interval: Interval) -> List[Song]:
    return []

def rank_by_user_preference(songs: List[Song], user: User) -> List[Song]:
    return []

def rank_by_interval_match(songs: List[Song], interval: Interval) -> List[Song]:
    return []

# === Recommendation engine ===
def recommend(interval: Interval, songs: List[Song], limit: int = 10, user_genres: Sequence[str] = USER_GENRES) -> List[Recommendation]:
    """
    Recommend a ranked list of songs for a given workout interval.

    Steps:
      - resolve target cadence
      - filter songs by user genres
      - filter songs with valid BPM and that are BPM-compatible (considering half/double)
      - rank primarily by bpm_confidence (higher better), then by bpm_difference (lower better), then by song id deterministically
    """
    target_cadence = get_target_cadence(interval)
    logger.info("Recommendation request: interval=%s => target_cadence=%s", getattr(interval, "__dict__", str(interval)), target)

    if target_cadence is None:
        logger.info("No target cadence could be determined for interval; returning empty recommendations.")
        return []
    user = getCurrentUser()
    first_candidate_pool = approximate_filter_by_interval(songs, interval)
    second_candidate_pool = rank_by_user_preference(first_candidate_pool, user)
    third_candidate_pool = rank_by_interval_match(second_candidate_pool, interval)
    return third_candidate_pool
    """
    # Genre filter
    genre_candidates = [s for s in songs if song_matches_user_genres(s, user_genres)]
    print(f"Candidates by genre: {len(genre_candidates)}")
    logger.debug("Genre candidates: %d / %d", len(genre_candidates), len(songs))
    if not genre_candidates:
        logger.info("No songs matched user genres: %s", user_genres)
        return []

    # Evaluate BPM compatibility
    candidates = []
    for s in genre_candidates:
        sbpm = _get(s, "bpm", None)
        if sbpm is None:
            continue
        match = calculate_bpm_match(sbpm, target_cadence)
        if not match.compatible:
            continue
        conf = _get(s, "bpm_confidence", None)
        candidates.append((s, sbpm, conf, match))

    if not candidates:
        logger.info("No BPM-compatible songs found for target cadence %s", target)
        return []

    # Deterministic ranking:
    # 1. has_confidence (True before False)
    # 2. bpm_confidence (desc)
    # 3. bpm_difference (asc)
    # 4. stable song id (if available) or str(song)
    def song_sort_key(entry):
        s, sbpm, conf, match = entry
        has_conf = 1 if (conf is not None) else 0
        conf_val = float(conf) if conf is not None else 0.0
        diff_val = float(match.difference) if match.difference is not None else float("inf")
        sid = _get(s, "id", None)
        sid_key = str(sid) if sid is not None else str(s)
        # we want has_conf True first => sort by -has_conf, then -conf_val
        return (-has_conf, -conf_val, diff_val, sid_key)

    candidates.sort(key=song_sort_key)

    recs: List[Recommendation] = []
    for s, sbpm, conf, match in candidates[:limit]:
        recs.append(Recommendation(
            song=s,
            song_bpm=float(sbpm) if sbpm is not None else None,
            bpm_confidence=(float(conf) if conf is not None else None),
            target_cadence=target,
            effective_bpm=match.effective_bpm,
            bpm_difference=match.difference,
            tempo_multiplier=match.multiplier,
        ))

    logger.info("Top %d recommendations (target %.1f): %d results", limit, target, len(recs))
    for r in recs[:10]:
        logger.debug("Recommendation: id=%s bpm=%.2f eff=%.2f diff=%.2f conf=%s mult=%s",
                     _get(r.song, "id", None),
                     r.song_bpm or 0.0,
                     r.effective_bpm or 0.0,
                     r.bpm_difference or 0.0,
                     r.bpm_confidence,
                     r.tempo_multiplier)
    """