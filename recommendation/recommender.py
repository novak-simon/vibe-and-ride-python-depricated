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
from datetime import timedelta

from workout.model import Interval, Workout
from music.model import Song
from user.model import User
from user.service import getCurrentUser
from database.songs import get_songs_around_target, fetch_songs
from database.user_song_stats import get_stat_by_user_and_song_id
from database.admin_client import create_admin_supabase
from helper_methods.model_methods import current_timestampz



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
FIRST_CANDIDATE_POOL_LIMIT = 300
THIRD_CANDIDATE_POOL_LIMIT = 10


def approximate_filter_by_interval(interval: Interval) -> List[Song]:
    print(f"Power: {interval.power}, Cadence: {interval.cadence}")
    interval_algorithm_cadence = get_algorithm_cadence(interval.cadence)
    interval_algorithm_power = interval.power*100 if not interval.power is None else 60
    pool = get_songs_around_target(admin_client, interval_algorithm_cadence, interval_algorithm_power, algorithm_cadence_toleration=5, algorithm_power_toleration=50, limit=FIRST_CANDIDATE_POOL_LIMIT) #Temporarily set to 50
    if pool:
        return pool
    else:   #Try to get songs that don't match that well, if it fails, gets at least some songs
        pool = get_songs_around_target(admin_client, interval_algorithm_cadence, interval_algorithm_power, 10, 20, limit=FIRST_CANDIDATE_POOL_LIMIT)
        if pool:
            return pool
        else:
            pool = fetch_songs(admin_client, limit=FIRST_CANDIDATE_POOL_LIMIT)
            return pool


def rank_song_by_user_preference(song: Song, user: User) -> int:
    """Ranks songs by user preferences and user_song_stats."""
    if user is None or not song:
        return 0
    number_of_matching_genres = len(set(song.genre) & set(user.genre_preferences))
    stat = get_stat_by_user_and_song_id(user.id, song.id, admin_client)
    since_last_played = current_timestampz() - stat.last_played_at
    if since_last_played < timedelta(hours=1):
        return 0
    else:
        repetition_coefficient = min(2, since_last_played/timedelta(days=2))
    like_coefficient = 2 if stat.is_liked is True else 1
    if not stat.skip_count == 0:
        skip_coefficient = min(2, stat.play_count/3*stat.skip_count)
    else:
        skip_coefficient = 2
    score = number_of_matching_genres * repetition_coefficient * like_coefficient * skip_coefficient
    return score


def rank_by_interval_match(songs: List[Song], interval: Interval) -> List[Song]:
    """
    Rank songs for a workout interval and return up to THIRD_CANDIDATE_POOL_LIMIT songs.

    Ranking signals:
    - Cadence fit (strongest): uses BPM half/double matching + algorithm_cadence
    - Power fit: compares interval power (scaled to 0-100) with song.algorithm_power
    - BPM confidence: prefers more reliable BPM estimates
    """
    if not songs or interval is None:
        return []

    target_cadence = _get(interval, "cadence", None)
    target_power = _get(interval, "power", None)
    target_algorithm_power = (float(target_power) * 100.0) if target_power is not None else None

    def _clamp01(x: float) -> float:
        if x < 0.0:
            return 0.0
        if x > 1.0:
            return 1.0
        return x

    ranked = []

    for song in songs:
        sbpm = _get(song, "bpm", None)
        bpm_conf = _get(song, "bpm_confidence", 0) or 0
        song_alg_cad = _get(song, "algorithm_cadence", None)
        song_alg_pow = _get(song, "algorithm_power", None)

        cadence_diff = float("inf")
        cadence_score = 0.0
        cadence_compatible_bonus = 0.0

        # 1) Cadence fit: best of BPM-based matching and algorithm_cadence
        if target_cadence is not None:
            candidate_diffs = []

            if sbpm not in (None, 0):
                match = calculate_bpm_match(sbpm, target_cadence)
                if match.difference is not None:
                    candidate_diffs.append(float(match.difference))
                    if match.compatible:
                        cadence_compatible_bonus = 0.15

            if song_alg_cad not in (None, 0):
                candidate_diffs.append(abs(float(song_alg_cad) - float(target_cadence)))

            if candidate_diffs:
                cadence_diff = min(candidate_diffs)
                # Soft decay: full score near 0 diff, fades toward 0 at ~30 BPM diff
                cadence_score = _clamp01(1.0 - (cadence_diff / 30.0))
            else:
                cadence_score = 0.0
        else:
            # No cadence in interval -> neutral cadence contribution
            cadence_score = 0.4
            cadence_diff = 9999.0

        # 2) Power fit (optional)
        power_diff = float("inf")
        power_score = 0.0
        if target_algorithm_power is not None and song_alg_pow is not None:
            power_diff = abs(float(song_alg_pow) - float(target_algorithm_power))
            # Soft decay: fades toward 0 at ~80 power points
            power_score = _clamp01(1.0 - (power_diff / 80.0))

        # 3) BPM confidence (optional)
        conf_score = _clamp01(float(bpm_conf) / 100.0)

        # Weighted total score
        total_score = (
            0.70 * cadence_score +
            0.00 * power_score +    #TEMPORARILY SET TO 0, WAITING FOR COMPLETE SONG ANALYSIS MODULE
            0.30 * conf_score +
            cadence_compatible_bonus
        )

        sid = _get(song, "id", None)
        ranked.append((song, total_score, cadence_diff, power_diff, -conf_score, str(sid)))

    # Higher total score first, then tighter cadence, tighter power, higher confidence, stable id tie-break
    ranked.sort(key=lambda x: (-x[1], x[2], x[3], x[4], x[5]))

    return [row[0] for row in ranked[:THIRD_CANDIDATE_POOL_LIMIT]]


# === Recommendation engine ===
def recommend(workout: Workout) -> List[List[Song]]:
    """
    Recommend a ranked list of songs for a given workout interval.
    """
    intervals = workout.intervals
    if intervals is None:
        return []
    user = getCurrentUser()
    candidate_pool = []
    existing_ids = set()
    for interval in intervals:
        pool = approximate_filter_by_interval(interval)
        for song in pool:
            if song.id not in existing_ids:
                candidate_pool.append(song)
                existing_ids.add(song.id)
    candidate_pool.sort(key=lambda song: rank_song_by_user_preference(song, user), reverse=True)
    interval_recs = []
    for interval in intervals:
        interval_recs.append(rank_by_interval_match(candidate_pool, interval))
    return interval_recs