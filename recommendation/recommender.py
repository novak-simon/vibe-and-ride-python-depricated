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
from dataclasses import dataclass, asdict
from types import SimpleNamespace
from typing import Any, List, Optional, Sequence, Dict
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

# === Debug models (captured during initial recommendation pass) ===
@dataclass
class RecommendationCandidateDebug:
    rank: Optional[int]
    song_id: Optional[int]
    title: Optional[str]
    artist: Optional[str]
    bpm: Optional[float]
    bpm_confidence: Optional[float]
    algorithm_cadence: Optional[float]
    algorithm_power: Optional[float]
    genre: List[Any]
    start_time: Optional[float]

    # cadence matching details
    cadence_difference: Optional[float]
    effective_bpm: Optional[float]
    tempo_multiplier: Optional[float]
    cadence_compatible: Optional[bool]
    cadence_distance_source: Optional[str]  # "bpm" / "algorithm_cadence" / "none"

    # scoring components from algorithm
    cadence_score: float
    power_score: float
    confidence_score: float
    song_score: float
    cadence_compatible_bonus: float
    final_score: float

    # user-preference stage info (already computed in recommend pre-sort)
    user_preference_score: Optional[float]
    genre_match_count: Optional[int]
    genre_match: Optional[bool]
    recent_play_penalty: Optional[float]
    liked: Optional[bool]
    play_count: Optional[int]
    skip_count: Optional[int]


@dataclass
class RecommendationIntervalDebug:
    interval_index: int
    interval_identifier: str
    duration: Optional[float]
    interval_type: Optional[str]
    target_cadence: Optional[float]
    cadence_source: str
    target_power: Optional[float]

    selected_song_id: Optional[int] = None
    selected_start_position: Optional[float] = None
    selected_final_score: Optional[float] = None

    candidates_top10: List[RecommendationCandidateDebug] = None


@dataclass
class RecommendationDebugResult:
    workout_name: Optional[str]
    interval_count: int
    candidate_pool_size: int
    ranking_pool_size: int
    second_candidate_pool_limit: int
    third_candidate_pool_limit: Optional[int]
    intervals: List[RecommendationIntervalDebug]


_LAST_RECOMMENDATION_DEBUG: Optional[RecommendationDebugResult] = None

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

# Currently not in use, rank_song_by_user_preference_with_details is in use due to debug
# Will be probably reused later when optimization will take plaec
# !!! IT IS PROBABLY NOT UP TO DATE !!!
def rank_song_by_user_preference(song: Song, user: User) -> int:
    """Ranks songs by user preferences and user_song_stats."""
    if user is None or not song:
        return 0
    number_of_matching_genres: float = len(set(song.genre) & set(user.genre_preferences)) if song.genre else 0.5
    stat = get_stat_by_user_and_song_id(user.id, song.id, admin_client)
    if stat:
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
    else:
        score = number_of_matching_genres * 8.1
    return score


def rank_by_interval_match(
    songs: List[Song],
    intervals: List[Interval],
    debug_intervals_out: Optional[List[RecommendationIntervalDebug]] = None,
    user_pref_debug_by_song_id: Optional[Dict[Optional[int], Dict[str, Any]]] = None,
) -> List[List[Song]]:
    """
    Rank songs for a workout interval and return up to THIRD_CANDIDATE_POOL_LIMIT songs.

    Ranking signals:
    - Cadence fit (strongest): uses BPM half/double matching + algorithm_cadence
    - Power fit: compares interval power (scaled to 0-100) with song.algorithm_power
    - BPM confidence: prefers more reliable BPM estimates
    """
    if not songs or intervals is None:
        return []

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
    
    interval_scores = []
    interval_ranked_rows = []  # keep score rows to mark selected later

    for idx, interval in enumerate(intervals):
        target_cadence = _get(interval, "cadence", None)
        target_power = _get(interval, "power", None)
        target_algorithm_power = (float(target_power) * 100.0) if target_power is not None else None

        

        ranked = []
        debug_candidates_raw: Dict[Optional[int], RecommendationCandidateDebug] = {}

        for song in songs:
            sbpm = _get(song, "bpm", None)
            bpm_conf = _get(song, "bpm_confidence", 0) or 0
            song_alg_cad = _get(song, "algorithm_cadence", None)
            song_alg_pow = _get(song, "algorithm_power", None)

            cadence_diff = float("inf")
            cadence_score = 0.0
            cadence_compatible_bonus = 0.0

            # debug cadence details
            best_bpm_diff = None
            best_bpm_eff = None
            best_bpm_mult = None
            bpm_compatible = None

            if target_cadence is not None:
                candidate_diffs = []

                if sbpm not in (None, 0):
                    match = calculate_bpm_match(sbpm, target_cadence)
                    if match.difference is not None:
                        best_bpm_diff = float(match.difference)
                        best_bpm_eff = match.effective_bpm
                        best_bpm_mult = match.multiplier
                        bpm_compatible = match.compatible

                        candidate_diffs.append(float(match.difference))
                        if match.compatible:
                            cadence_compatible_bonus = 0.15

                alg_cad_diff = None
                if song_alg_cad not in (None, 0):
                    alg_cad_diff = abs(float(song_alg_cad) - float(target_cadence))
                    candidate_diffs.append(alg_cad_diff)

                if candidate_diffs:
                    cadence_diff = min(candidate_diffs)

                    def compute_cs(x):
                        if x > 4.6:
                            return 0.3 / (x - 4)
                        else:
                            return (0.3 / (x - 5.2)) + 1

                    cadence_score = _clamp01(compute_cs(cadence_diff))
                else:
                    cadence_score = 0.0
            else:
                # No cadence in interval -> neutral cadence contribution
                cadence_score = 0.4
                cadence_diff = 9999.0
                alg_cad_diff = None

            # 2) Power fit (optional)
            power_diff = float("inf")
            power_score = 0.0
            if target_algorithm_power is not None and song_alg_pow is not None:
                power_diff = abs(float(song_alg_pow) - float(target_algorithm_power))
                # Soft decay: fades toward 0 at ~80 power points
                power_score = _clamp01(1.0 - (power_diff / 80.0))

            # 3) BPM confidence (optional)
            conf_score = _clamp01(float(bpm_conf) / 100.0)

            # 4) Song score (optional)
            TAG_WEIGHTS = {
                "energetic": 0.5,
                "motivational": 0.5,
                "upbeat": 0.3,
                "radio": 0.3,
                "groovy": 0.2,
                "powerful": 0.2,
                "beachmusic": 0.2,
                "handclaps": 0.2,
                "fast": 0.2,
                "epic": 0.1,
                "uplifting": 0.1,
                "upliftingrock": 0.1,
                "agressive": 0.1,
                "happy": 0.1,
                "cheerful": 0.1,
                "party": 0.1,
                "summer": 0.05,
                "popular": 0.05,
                "drumkit": 0.1,
                "lounge": -0.1,
                "film": -0.1,
                "filmscore": -0.1,
                "soft": -0.1,
                "ballad": -0.1,
                "melancholic": -0.1,
                "peaceful": -0.2,
                "cinematic": -0.2,
                "peace": -0.2,
                "chilloutmusic": -0.2,
                "chill": -0.2,
                "relaxing": -0.2,
                "mystery": -0.2,
                "sad": -0.3,
                "lonely": -0.3,
                "dark": -0.3,
                "podcast": -0.3,
                "calm": -0.3,
                "atmospheric": -0.3,
                "soundscape": -0.5,
                "introspective": -0.5,
                "ambient": -1,
                "ambientdub": -1,
                "drone": -1,
            }
            INSTRUMENT_WEIGHTS = {
                "drums": 0.1,
                "drummachine": 0.1,
                "bass": 0.1,
                "electricguitar": 0.05,
                "electroamplified": 0.05,
                "synthesizer": 0.05,
            }
            GENRE_WEIGHTS = {"ambient": -1, "ambientdub": -1, "drone": -1}

            vartags = _safe_list(_get(song, "vartags", []))
            instruments = _safe_list(_get(song, "instruments", []))
            genres = _safe_list(_get(song, "genre", []))

            tag_score = sum(TAG_WEIGHTS.get(t, 0) for t in vartags)
            instrument_score = sum(INSTRUMENT_WEIGHTS.get(i, 0) for i in instruments)
            genre_score = sum(GENRE_WEIGHTS.get(t, 0) for t in genres)
            song_score = _clamp02(tag_score + instrument_score + genre_score)

            total_score = (
                0.80 * cadence_score +
                0.00 * power_score +    #TEMPORARILY SET TO 0, WAITING FOR COMPLETE SONG ANALYSIS MODULE
                0.20 * conf_score +
                0.30 * song_score +
                cadence_compatible_bonus
            )

            sid = _get(song, "id", None)
            ranked.append((song, total_score, cadence_diff, power_diff, -conf_score, str(sid)))

            # --- tiny debug hook: capture already-computed values (no recomputation) ---
            if debug_intervals_out is not None:
                pref = (user_pref_debug_by_song_id or {}).get(sid, {})
                cadence_distance_source = "none"
                if target_cadence is not None:
                    bpm_d = best_bpm_diff if best_bpm_diff is not None else float("inf")
                    ac_d = alg_cad_diff if alg_cad_diff is not None else float("inf")
                    if bpm_d <= ac_d:
                        cadence_distance_source = "bpm"
                    elif ac_d < float("inf"):
                        cadence_distance_source = "algorithm_cadence"

                debug_candidates_raw[sid] = RecommendationCandidateDebug(
                    rank=None,
                    song_id=sid,
                    title=_get(song, "title", None),
                    artist=_get(song, "artist", None),
                    bpm=_get(song, "bpm", None),
                    bpm_confidence=_get(song, "bpm_confidence", None),
                    algorithm_cadence=_get(song, "algorithm_cadence", None),
                    algorithm_power=_get(song, "algorithm_power", None),
                    genre=genres,
                    start_time=_get(song, "start_time", None),
                    cadence_difference=None if cadence_diff == float("inf") else cadence_diff,
                    effective_bpm=best_bpm_eff,
                    tempo_multiplier=best_bpm_mult,
                    cadence_compatible=bpm_compatible,
                    cadence_distance_source=cadence_distance_source,
                    cadence_score=cadence_score,
                    power_score=power_score,
                    confidence_score=conf_score,
                    song_score=song_score,
                    cadence_compatible_bonus=cadence_compatible_bonus,
                    final_score=total_score,
                    user_preference_score=pref.get("score"),
                    genre_match_count=pref.get("genre_match_count"),
                    genre_match=pref.get("genre_match"),
                    recent_play_penalty=pref.get("recent_play_penalty"),
                    liked=pref.get("liked"),
                    play_count=pref.get("play_count"),
                    skip_count=pref.get("skip_count"),
                )

        ranked.sort(key=lambda x: (-x[1], x[2], x[3], x[4], x[5]))
        interval_scores.append([row[0] for row in ranked])
        interval_ranked_rows.append(ranked)

        if debug_intervals_out is not None:
            top10 = []
            for rank_i, row in enumerate(ranked[:10], start=1):
                s = row[0]
                sid = _get(s, "id", None)
                c = debug_candidates_raw.get(sid)
                if c is None:
                    continue
                c.rank = rank_i
                c.final_score = row[1]
                top10.append(c)

            debug_intervals_out.append(
                RecommendationIntervalDebug(
                    interval_index=idx,
                    interval_identifier=f"{idx + 1}/{len(intervals)}",
                    duration=_get(interval, "duration", None),
                    interval_type=_get(interval, "type", None),
                    target_cadence=_get(interval, "cadence", None),
                    cadence_source=_infer_cadence_source(interval),
                    target_power=_get(interval, "power", None),
                    candidates_top10=top10,
                )
            )

    usable_interval_scores = list(interval_scores)
    number_of_intervals = len(intervals)
    used_songs = set()
    interval_recs = [[] for i in range(number_of_intervals)]
    longest_interval_duration = max([interval.duration for interval in intervals])
    third_candidate_pool_limit = int((longest_interval_duration // 60) + 2)

    for i in range(third_candidate_pool_limit):
        for j in range(number_of_intervals):
            if usable_interval_scores[j]:
                song = None
                while (song is None or song.id in used_songs) and usable_interval_scores[j]:
                    song = usable_interval_scores[j].pop(0)
            else:
                song = interval_scores[j][len(interval_scores) - third_candidate_pool_limit + i]
            interval_recs[j].append(song)
            used_songs.add(song.id)

    # --- tiny debug hook: mark selected song after assignment pass ---
    if debug_intervals_out is not None:
        for j in range(number_of_intervals):
            selected = interval_recs[j][0] if interval_recs[j] else None
            if selected is None:
                continue
            sid = _get(selected, "id", None)
            debug_intervals_out[j].selected_song_id = sid
            debug_intervals_out[j].selected_start_position = _get(selected, "start_time", None)

            # lookup final score from ranked rows
            for row in interval_ranked_rows[j]:
                if _get(row[0], "id", None) == sid:
                    debug_intervals_out[j].selected_final_score = row[1]
                    break

    return interval_recs

def get_last_recommendation_debug() -> Optional[RecommendationDebugResult]:
    return _LAST_RECOMMENDATION_DEBUG


def get_last_recommendation_debug_payload() -> Optional[dict]:
    if _LAST_RECOMMENDATION_DEBUG is None:
        return None
    return asdict(_LAST_RECOMMENDATION_DEBUG)


def _infer_cadence_source(interval: Interval) -> str:
    attrs = _get(interval, "attrs", {}) or {}
    if attrs.get("Cadence") is not None or attrs.get("cadence") is not None:
        return "explicit"
    if _get(interval, "cadence", None) is not None:
        return "estimated"
    return "missing"


def _safe_list(value: Any) -> List[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        return [value]
    try:
        return list(value)
    except Exception:
        return []


def _rank_user_preference_with_details(song: Song, user: User) -> tuple[float, Dict[str, Any]]:
    """
    Exact same logic as rank_song_by_user_preference, plus details captured once.
    """
    details = {
        "genre_match_count": 0,
        "genre_match": False,
        "recent_play_penalty": None,
        "liked": None,
        "play_count": None,
        "skip_count": None,
    }

    if user is None or not song:
        return 0.0, details

    song_genres = set(_safe_list(_get(song, "genre", [])))
    user_genres = set(_safe_list(_get(user, "genre_preferences", [])))
    number_of_matching_genres = len(song_genres & user_genres) if song_genres else 0.5

    details["genre_match_count"] = int(number_of_matching_genres if song_genres else 0)
    details["genre_match"] = details["genre_match_count"] > 0

    stat = get_stat_by_user_and_song_id(user.id, song.id, admin_client)
    if stat:
        details["liked"] = bool(stat.is_liked)
        details["play_count"] = stat.play_count
        details["skip_count"] = stat.skip_count

        since_last_played = current_timestampz() - stat.last_played_at
        if since_last_played < timedelta(hours=1):
            details["recent_play_penalty"] = 1.0
            return 0.0, details
        else:
            details["recent_play_penalty"] = 0.0
            repetition_coefficient = min(2, since_last_played / timedelta(days=2))

        like_coefficient = 2 if stat.is_liked is True else 1
        if not stat.skip_count == 0:
            skip_coefficient = min(2, stat.play_count / 3 * stat.skip_count)
        else:
            skip_coefficient = 2
        score = number_of_matching_genres * repetition_coefficient * like_coefficient * skip_coefficient
    else:
        score = number_of_matching_genres * 8.1

    return float(score), details

# === Recommendation engine ===
def recommend(workout: Workout) -> List[List[Song]]:
    """
    Recommend a ranked list of songs for a given workout interval.
    """
    global _LAST_RECOMMENDATION_DEBUG

    intervals = workout.intervals
    if intervals is None:
        _LAST_RECOMMENDATION_DEBUG = None
        return []

    user = getCurrentUser()
    second_candidate_pool_limit = int(workout.total_duration // 6)

    candidate_pool = []
    existing_ids = set()
    for interval in intervals:
        pool = approximate_filter_by_interval(interval)
        for song in pool:
            if song.id not in existing_ids:
                candidate_pool.append(song)
                existing_ids.add(song.id)

    print(f"Initial candidate pool size: {len(candidate_pool)}")

    # Capture user-preference details ONCE during actual pre-ranking
    user_pref_debug_by_song_id: Dict[Optional[int], Dict[str, Any]] = {}

    def _pref_key(song: Song):
        score, details = _rank_user_preference_with_details(song, user)
        sid = _get(song, "id", None)
        user_pref_debug_by_song_id[sid] = {"score": score, **details}
        return score

    candidate_pool.sort(key=_pref_key, reverse=True)

    ranking_pool = candidate_pool[:second_candidate_pool_limit]

    interval_debug_models: List[RecommendationIntervalDebug] = []
    interval_recs = rank_by_interval_match(
        ranking_pool,
        intervals,
        debug_intervals_out=interval_debug_models,
        user_pref_debug_by_song_id=user_pref_debug_by_song_id,
    )

    third_candidate_pool_limit = int((max([i.duration for i in intervals]) // 60) + 2) if intervals else None

    _LAST_RECOMMENDATION_DEBUG = RecommendationDebugResult(
        workout_name=_get(workout, "name", None),
        interval_count=len(intervals),
        candidate_pool_size=len(candidate_pool),
        ranking_pool_size=len(ranking_pool),
        second_candidate_pool_limit=second_candidate_pool_limit,
        third_candidate_pool_limit=third_candidate_pool_limit,
        intervals=interval_debug_models,
    )

    # Emit payload for controller/UI
    _emit_recommendation_debug(get_last_recommendation_debug_payload())

    return interval_recs

# Optional external debug sink (UI/dev panel can register a callable here)
_RECOMMENDATION_DEBUG_SINK = None

def set_recommendation_debug_sink(sink) -> None:
    global _RECOMMENDATION_DEBUG_SINK
    _RECOMMENDATION_DEBUG_SINK = sink

def _emit_recommendation_debug(payload: dict) -> None:
    sink = _RECOMMENDATION_DEBUG_SINK
    if sink is None:
        return
    try:
        sink(payload)
    except Exception:
        logger.exception("Recommendation debug sink failed")