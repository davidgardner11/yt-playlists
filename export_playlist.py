import argparse
import os
import sys

import pandas as pd

from pipeline_cli import add_db_args, open_db, validate_playlist_arg
from playlist_utils import (
    ALL_URLS_COLUMN,
    TRANSCRIPT_COLUMN,
    TRANSCRIPT_LANGUAGE_COLUMN,
    TRANSCRIPT_STATUS_COLUMN,
    TRANSCRIPT_URLS_COLUMN,
    URLS_COLUMN,
    validate_playlist_paths,
    write_playlist,
)

EXPORT_COLUMNS = [
    "Video Title",
    "Video URL",
    "Channel Name",
    "Channel ID",
    "Publish Date",
    "Video Length",
    "View Count",
    "Like Count",
    "Comment Count",
    "Full Video Description",
    "Tags/Keywords",
    URLS_COLUMN,
    TRANSCRIPT_COLUMN,
    TRANSCRIPT_LANGUAGE_COLUMN,
    TRANSCRIPT_STATUS_COLUMN,
    TRANSCRIPT_URLS_COLUMN,
    ALL_URLS_COLUMN,
]


def video_row_to_export(video):
    return {
        "Video Title": video.get("video_title", ""),
        "Video URL": video.get("video_url", ""),
        "Channel Name": video.get("channel_name", ""),
        "Channel ID": video.get("channel_id", ""),
        "Publish Date": video.get("publish_date", ""),
        "Video Length": video.get("video_length", ""),
        "View Count": video.get("view_count", ""),
        "Like Count": video.get("like_count", ""),
        "Comment Count": video.get("comment_count", ""),
        "Full Video Description": video.get("description", ""),
        "Tags/Keywords": video.get("tags", ""),
        URLS_COLUMN: video.get("description_urls", ""),
        TRANSCRIPT_COLUMN: video.get("transcript_text", ""),
        TRANSCRIPT_LANGUAGE_COLUMN: video.get("transcript_language", ""),
        TRANSCRIPT_STATUS_COLUMN: video.get("transcript_status", ""),
        TRANSCRIPT_URLS_COLUMN: video.get("transcript_urls", ""),
        ALL_URLS_COLUMN: video.get("all_urls", ""),
    }


def export_playlist_to_file(db, playlist_name, output_path):
    videos = db.get_playlist_videos(playlist_name)
    if not videos:
        raise ValueError(f"No videos found for playlist '{playlist_name}'")

    rows = [video_row_to_export(video) for video in videos]
    df = pd.DataFrame(rows, columns=EXPORT_COLUMNS)
    write_playlist(df, output_path)
    return output_path


def export_playlist(playlist_name, output_path, db_path=None):
    with open_db(db_path) as db:
        if not db.get_playlist_by_name(playlist_name):
            raise ValueError(f"Playlist not found in database: {playlist_name}")
        path = export_playlist_to_file(db, playlist_name, output_path)
        count = len(db.get_playlist_videos(playlist_name))

    print(f"Exported {count} videos to {path}")
    return path


def parse_args():
    parser = argparse.ArgumentParser(
        description="Export a playlist from the SQLite database to xlsx/csv."
    )
    parser.add_argument(
        "--playlist",
        "-p",
        required=True,
        help="Playlist name to export",
    )
    parser.add_argument(
        "--output",
        "-o",
        required=True,
        help="Output file (.xlsx or .csv)",
    )
    add_db_args(parser)
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()

    try:
        validate_playlist_arg(args.playlist, required=True)
        validate_playlist_paths("dummy.xlsx", args.output)
        with open_db(args.db) as db:
            if not db.get_playlist_by_name(args.playlist):
                print(f"Playlist not found in database: {args.playlist}")
                sys.exit(1)
            output_path = export_playlist_to_file(db, args.playlist, args.output)
            count = len(db.get_playlist_videos(args.playlist))
        print(f"Exported {count} videos to {output_path}")
    except ValueError as exc:
        print(exc)
        sys.exit(1)
