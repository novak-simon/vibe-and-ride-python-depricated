

from typing import Any, List

from realtime import dataclass

from database.admin_client import create_admin_supabase
from database.songs import get_songs_around_target_cadence
from music.model import Song
from workout.model import Interval
from user.service import get_current_user


@dataclass(frozen=True)
class Recommendation:
    song: Song
    score: float

admin_client = create_admin_supabase()

FIRST_CANDIDATE_POOL_LIMIT = 100

def get_song_recommendation_score(song: Song, user: Any, interval: Interval) -> Recommendation:
    """
    Calculate a recommendation score for a given song based on user preferences and interval characteristics.
    Returns a Recommendation object containing the song and its recommendation score.
    """
    score = 0

    # Example scoring logic (to be replaced with actual logic)
    if song.genre in user.genre_preferences:
        score += 10
    if abs(song.algorithm_cadence - interval.cadence) < 5:
        score += 5

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
    return [rec.song for rec in sorted(candidates, key=lambda x: x.score, reverse=True)][:10]