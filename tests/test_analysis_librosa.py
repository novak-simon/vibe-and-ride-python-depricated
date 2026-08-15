import json
import struct
import wave
from unittest.mock import MagicMock

import pytest

from analysis.librosa_analyzer import LibrosaAnalyzer
from analysis.model import AudioAnalysis
from database.songs import fetch_unanalyzed_songs, update_song_analysis
from music.model import Song


def _write_click_track(path, bpm: int = 120, duration: float = 4.0, sr: int = 22050) -> None:
    num_samples = int(duration * sr)
    pulse_samples = max(1, int(sr * 0.01))
    interval = int(sr * 60 / bpm)

    samples = [0] * num_samples
    for start in range(0, num_samples, interval):
        for i in range(pulse_samples):
            if start + i < num_samples:
                samples[start + i] = 16000

    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sr)
        wf.writeframes(
            b"".join(struct.pack("<h", int(sample)) for sample in samples)
        )


def test_librosa_analyzer_detects_beats(tmp_path):
    path = tmp_path / "click_track.wav"
    _write_click_track(path)

    analysis = LibrosaAnalyzer().analyze(str(path))

    assert isinstance(analysis.bpm, float)
    assert 100 <= analysis.bpm <= 140
    assert len(analysis.beats) >= 4
    assert len(analysis.beat_intervals) == len(analysis.beats) - 1
    assert all(isinstance(value, float) for value in analysis.beats)
    assert all(isinstance(value, float) for value in analysis.beat_intervals)
    assert analysis.bpm_confidence is not None
    assert 0.0 <= analysis.bpm_confidence <= 1.0


def test_confidence_metric_is_application_defined\n\ndef test_edge_case_silence(tmp_path):\n    path = tmp_path / 'silence.wav'\n    with wave.open(str(path), 'wb') as wf:\n        wf.setnchannels(1)\n        wf.setsampwidth(2)\n        wf.setframerate(22050)\n        wf.writeframes(b'\x00' * 22050)\n\n    analysis = LibrosaAnalyzer().analyze(str(path))\n    assert analysis.bpm is None\n    assert analysis.bpm_confidence is None():
    analyzer = LibrosaAnalyzer()
    assert analyzer._confidence_for_intervals([0.5, 0.5, 0.5]) == 1.0
    assert analyzer._confidence_for_intervals([0.5, 0.45, 0.55]) < 1.0
    assert analyzer._confidence_for_intervals([0.5]) is None


def test_beats_and_intervals_are_json_serializable():
    analysis = AudioAnalysis(bpm=120.0, bpm_confidence=0.9, beats=[0.0, 0.5], beat_intervals=[0.5])
    serialized = json.dumps(
        {"beats": analysis.beats, "beat_intervals": analysis.beat_intervals}
    )
    assert json.loads(serialized) == {"beats": [0.0, 0.5], "beat_intervals": [0.5]}


def test_fetch_unanalyzed_songs_filters_existing_analysis(monkeypatch):
    fake_client = MagicMock()
    fake_table = MagicMock()
    fake_query = MagicMock()
    fake_client.table.return_value = fake_table
    fake_table.select.return_value = fake_query
    fake_query.or_.return_value = fake_query
    fake_query.limit.return_value = fake_query
    fake_query.execute.return_value = {
        "data": [
            {
                "id": 1,
                "title": "Already Analyzed",
                "jamendo_id": "abc",
                "bpm": 120,
                "beats": [0.0, 0.5],
                "beat_intervals": [0.5],
            },
            {
                "id": 2,
                "title": "Needs Analysis",
                "jamendo_id": "def",
                "bpm": None,
                "beats": None,
                "beat_intervals": None,
            },
        ],
        "error": None,
    }

    songs = fetch_unanalyzed_songs(fake_client, limit=10)
    assert len(songs) == 1
    assert songs[0].title == "Needs Analysis"


def test_update_song_analysis_calls_database():
    fake_client = MagicMock()
    fake_table = MagicMock()
    fake_query = MagicMock()
    fake_client.table.return_value = fake_table
    fake_table.update.return_value = fake_query
    fake_query.eq.return_value = fake_query
    fake_query.execute.return_value = {"data": [{"id": 2}], "error": None}

    analysis = AudioAnalysis(
        bpm=123.4,
        bpm_confidence=0.8,
        beats=[0.0, 0.5],
        beat_intervals=[0.5],
    )
    update_song_analysis(fake_client, 2, analysis)

    fake_table.update.assert_called_once_with(
        {
            "bpm": 123.4,
            "beats": [0.0, 0.5],
            "beat_intervals": [0.5],
            "bpm_confidence": 0.8,
        }
    )
