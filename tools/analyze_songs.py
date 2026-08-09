from __future__ import annotations

import argparse

from analysis.service import AudioAnalysisService
from database.methods import _effective_client
from database.admin_client import get_admin_supabase

admin_client = get_admin_supabase()

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Analyze songs from Supabase using librosa."
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=50,
        help="Maximum number of songs to analyze in this batch.",
    )
    args = parser.parse_args()

    client = _effective_client(client=admin_client)
    service = AudioAnalysisService(client)
    service.analyze_batch(limit=args.limit)


if __name__ == "__main__":
    main()