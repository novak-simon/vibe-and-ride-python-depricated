from __future__ import annotations

import argparse
from database.admin_client import get_admin_supabase
from analysis.service import analyze_songs


def main() -> int:
    parser = argparse.ArgumentParser(description="Analyze songs using Essentia")
    parser.add_argument("--limit", type=int, default=50, help="Maximum number of songs to analyze")
    args = parser.parse_args()

    client = get_admin_supabase()
    results = analyze_songs(limit=args.limit, client=client)

    for idx, (song, analysis, error) in enumerate(results, start=1):
        if error:
            print(f"{idx}/{len(results)}: {song.title} FAILED: {error}")
        else:
            print(f"{idx}/{len(results)}: {song.title}")
            print(f"  BPM: {analysis.bpm}")
            print(f"  Confidence: {analysis.confidence}")
            print(f"  Beats: {len(analysis.beats or [])}")
            print(f"  Intervals: {len(analysis.beat_intervals or [])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())