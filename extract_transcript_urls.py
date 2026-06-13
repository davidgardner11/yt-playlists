import argparse
import sys

from pipeline_cli import add_db_args, add_playlist_args, maybe_export, open_db, parse_export_arg, validate_playlist_arg
from playlist_utils import extract_urls, merge_url_columns


def extract_transcript_urls(
    playlist_name,
    db_path=None,
    force=False,
    include_youtube=True,
    export_path=None,
):
    validate_playlist_arg(playlist_name, required=True)

    with open_db(db_path) as db:
        if not db.get_playlist_by_name(playlist_name):
            raise ValueError(f"Playlist not found in database: {playlist_name}")

        videos = db.get_videos_needing_url_extraction(playlist_name=playlist_name, force=force)
        updated = 0

        for video in videos:
            transcript = video.get("transcript_text", "")
            if not transcript:
                continue

            transcript_urls = extract_urls(transcript, include_youtube=include_youtube)
            all_urls = merge_url_columns(video.get("description_urls", ""), transcript_urls)
            db.upsert_video_urls(video["video_id"], transcript_urls, all_urls)
            updated += 1

        print(f"Extracted URLs from {updated} transcript(s).")

        summary = db.get_pipeline_summary(playlist_name)
        print(
            f"\nURL extraction for '{playlist_name}': "
            f"{summary.get('urls_done', 0)}/{summary.get('transcript_ok', 0)} transcripts processed"
        )
        maybe_export(db, playlist_name, export_path)

    return playlist_name


def parse_args():
    parser = argparse.ArgumentParser(
        description="Extract websites and URLs mentioned in database-stored video transcripts."
    )
    add_playlist_args(parser, required=True)
    parser.add_argument(
        "--force",
        "-f",
        action="store_true",
        help="Re-extract transcript URLs for videos already processed",
    )
    parser.add_argument(
        "--exclude-youtube",
        action="store_true",
        help="Exclude youtube.com and youtu.be links from extracted URLs",
    )
    add_db_args(parser)
    parse_export_arg(parser)
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()

    try:
        extract_transcript_urls(
            args.playlist,
            db_path=args.db,
            force=args.force,
            include_youtube=not args.exclude_youtube,
            export_path=args.export,
        )
    except ValueError as exc:
        print(exc)
        sys.exit(1)
