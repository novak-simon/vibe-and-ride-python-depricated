import pytest
from types import SimpleNamespace
from recommendation.recommender import (
    get_target_cadence,
    estimate_cadence_from_power,
    song_matches_user_genres,
    calculate_bpm_match,
    recommend,
    USER_GENRES,
    BPM_TOLERANCE,
)

# Helper to build song dicts / objects
def song(id, bpm=None, bpm_confidence=None, genre=None):
    return {"id": id, "bpm": bpm, "bpm_confidence": bpm_confidence, "genre": genre}

def interval_obj(cadence=None, power=None):
    return SimpleNamespace(cadence=cadence, power=power)


def test_explicit_cadence_used():
    iv = interval_obj(cadence=100, power=250)
    assert get_target_cadence(iv) == 100.0

def test_power_only_uses_estimate():
    iv = interval_obj(cadence=None, power=250)
    cad = get_target_cadence(iv)
    assert cad is not None
    # verify estimate formula behaviour is stable
    assert pytest.approx(80.0 + (250 - 200) / 10.0, rel=1e-6) == cad

def test_missing_cadence_and_power_returns_none():
    iv = interval_obj(cadence=None, power=None)
    assert get_target_cadence(iv) is None

def test_genre_filtering_single_genre():
    s1 = song("a", bpm=100, bpm_confidence=0.9, genre="electronic")
    s2 = song("b", bpm=100, bpm_confidence=0.9, genre="jazz")
    assert song_matches_user_genres(s1)
    assert not song_matches_user_genres(s2)

def test_genre_filtering_multi_genre_list():
    s = {"id": "x", "bpm": 100, "bpm_confidence": 0.5, "genres": ["classical", "rock"]}
    assert song_matches_user_genres(s)

def test_exact_bpm_match():
    target = 100
    match = calculate_bpm_match(100, target)
    assert match.compatible
    assert match.multiplier == 1.0
    assert match.difference == pytest.approx(0.0)

def test_half_tempo_match():
    target = 100
    match = calculate_bpm_match(50, target)
    assert match.compatible
    assert match.multiplier == 2.0 or match.multiplier == 0.5 or match.multiplier is not None
    # effective BPM should be close to target after multiplier
    assert abs(match.effective_bpm - target) <= BPM_TOLERANCE

def test_double_tempo_match():
    target = 100
    match = calculate_bpm_match(200, target)
    assert match.compatible
    assert abs(match.effective_bpm - target) <= BPM_TOLERANCE

def test_bad_bpm_rejected():
    target = 100
    # choose song far from target even using half/double
    match = calculate_bpm_match(140, target)
    assert not match.compatible

def test_confidence_ranking_and_missing_confidence():
    # Build songs: all same effective match, different confidences
    iv = interval_obj(cadence=100)
    s1 = song("high", bpm=100, bpm_confidence=0.99, genre="rock")
    s2 = song("med", bpm=100, bpm_confidence=0.6, genre="rock")
    s3 = song("none", bpm=100, bpm_confidence=None, genre="rock")
    recs = recommend(iv, [s2, s3, s1], limit=10)
    assert [r.song["id"] for r in recs] == ["high", "med", "none"]

def test_missing_bpm_excluded():
    iv = interval_obj(cadence=100)
    s1 = song("no_bpm", bpm=None, bpm_confidence=None, genre="rock")
    recs = recommend(iv, [s1], limit=10)
    assert recs == []

def test_empty_candidate_list_returns_empty():
    iv = interval_obj(cadence=90)
    recs = recommend(iv, [], limit=10)
    assert recs == []

def test_determinism_of_ranking():
    iv = interval_obj(cadence=100)
    s1 = song("1", bpm=100, bpm_confidence=0.5, genre="pop")
    s2 = song("2", bpm=50, bpm_confidence=0.5, genre="pop")
    s3 = song("3", bpm=200, bpm_confidence=0.5, genre="pop")
    # reorder inputs multiple ways and ensure same ranking result
    order1 = recommend(iv, [s1, s2, s3], limit=10)
    order2 = recommend(iv, [s3, s1, s2], limit=10)
    assert [r.song["id"] for r in order1] == [r.song["id"] for r in order2]