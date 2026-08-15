from typing import Any, List
from realtime import dataclass
from datetime import timedelta

from database.admin_client import create_admin_supabase
from database.songs import get_songs_around_target_cadence
from music.model import Song
from user.model import User
from workout.model import Interval
from user.service import get_current_user
from helper_methods.model_methods import current_timestampz
from database.user_song_stats import get_stat_by_user_and_song_id
from recommendation.methods import _get, _clamp01, _clamp02, _safe_list, calculate_bpm_match


@dataclass(frozen=True)
class Recommendation:
    song: Song = None
    score: float = 0.0
    cadence_score: float = 0.0
    conf_score: float = 0.0
    song_score: float = 0.0

admin_client = create_admin_supabase()

FIRST_CANDIDATE_POOL_LIMIT = 100

def get_user_preference_score(song: Song, user: User) -> float:
    if not user:
        user = get_current_user()
    if not song or not user:
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

def get_interval_match_score(song: Song, interval: Interval) -> float:
    target_cadence = _get(interval, "cadence", None)

    sbpm = _get(song, "bpm", None)
    bpm_conf = _get(song, "bpm_confidence", 0) or 0
    song_alg_cad = _get(song, "algorithm_cadence", None)

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
            def compute_cs(x):
                if x > 4.6:
                    return 0.3/(x-4)
                else:
                    return (0.3/(x-5.2))+1
            cadence_score = _clamp01(compute_cs(cadence_diff))
        else:
            cadence_score = 0.0
    else:
        # No cadence in interval -> neutral cadence contribution
        cadence_score = 0.4
        cadence_diff = 9999.0

    # 2) BPM confidence (optional)
    conf_score = _clamp01(float(bpm_conf) / 100.0)

    # 3) Song score (optional)
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
    GENRE_WEIGHTS = {
        "ambient": -1,
        "ambientdub": -1,
        "drone": -1,
    }
    tag_score = sum(TAG_WEIGHTS.get(t, 0) for t in song.vartags)
    instrument_score = sum(INSTRUMENT_WEIGHTS.get(i, 0) for i in song.instruments)
    genre_score = sum(GENRE_WEIGHTS.get(t, 0) for t in song.genre)
    song_score = _clamp02(tag_score + instrument_score + genre_score)   #Can be negative

    # Weighted total score
    total_score = (
        0.60 * cadence_score +
        0.15 * conf_score +
        0.25 * song_score +
        cadence_compatible_bonus
    )
    return total_score

def get_song_recommendation_score(song: Song, user: Any, interval: Interval) -> Recommendation:
    """
    Calculate a recommendation score for a given song based on user preferences and interval characteristics.
    Returns a Recommendation object containing the song and its recommendation score.
    """
    if user is None or interval is None or song is None:
        return Recommendation(song=song, score=0)
    user_preference_score = get_user_preference_score(song, user)
    interval_match_score = get_interval_match_score(song, interval)
    score = user_preference_score + interval_match_score

    return Recommendation(song=song, score=score)


def recommend(interval: Interval) -> List[Song]:
    """
    Recommend songs for a given interval based on cadence, power, and user preferences.
    Returns a list of recommended Song objects.
    """
    if interval is None:
        return []

    user = get_current_user()  # Assuming a function to get the current user
    first_candidate_pool = get_songs_around_target_cadence(admin_client, interval.cadence, algorithm_cadence_toleration=2, limit=FIRST_CANDIDATE_POOL_LIMIT)
    initial_pool_size = len(first_candidate_pool)
    if initial_pool_size < FIRST_CANDIDATE_POOL_LIMIT:
        additive_candidates = get_songs_around_target_cadence(admin_client, interval.cadence, algorithm_cadence_toleration=5, limit=FIRST_CANDIDATE_POOL_LIMIT-initial_pool_size)
        first_candidate_pool.extend(additive_candidates)
    candidates = []
    for candidate in first_candidate_pool:
        candidates.append(get_song_recommendation_score(candidate, user, interval))
    return [rec.song for rec in sorted(candidates, key=lambda x: (-1 * x.score, -1 * x.cadence_score, -1 * x.conf_score, -1 * x.song_score, x.song.id))][:10]