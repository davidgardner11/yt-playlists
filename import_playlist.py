import argparse
import os
import sys
from pathlib import Path

import pandas as pd

from pipeline_cli import add_db_args, open_db
from playlist_db import PlaylistDB
from playlist_utils import get_video_id, read_playlist, require_video_url_column


def playlist_name_from_path(path):
    return Path(path).stem


def row_to_seed_fields(row):
    return {column: ("" if pd.isna(value) else value) for column, value in row.items()}


def import_playlist_file(db, name, input_path, migrate=False):
    df = read_playlist(input_path)
    require_video_url_column(df)

    playlist_id = db.get_or_create_playlist(name, source_file=input_path)
    rows_imported = 0
    new_videos = 0
    existing_videos = 0
    skipped_rows = 0

    for position, (_, row) in enumerate(df.iterrows(), start=1):
        video_url = row.get("Video URL", "")
        video_id = get_video_id(video_url)
        if not video_id:
            skipped_rows += 1
            continue

        video_title = row.get("Video Title", "")
        if pd.isna(video_title):
            video_title = ""

        is_new = db.upsert_video_identity(video_id, video_url, str(video_title).strip() or None)
        if is_new:
            new_videos += 1
        else:
            existing_videos += 1

        if migrate:
            db.seed_video_fields_if_empty(video_id, row_to_seed_fields(row))

        db.link_video_to_playlist(playlist_id, video_id, position)
        rows_imported += 1

    db.conn.commit()
    return {
        "rows_imported": rows_imported,
        "new_videos": new_videos,
        "existing_videos": existing_videos,
        "skipped_rows": skipped_rows,
    }


def import_playlist(input_path, name=None, db_path=None, migrate=False):
    if not name:
        name = playlist_name_from_path(input_path)

    with open_db(db_path) as db:
        stats = import_playlist_file(db, name, input_path, migrate=migrate)
        summary = db.get_pipeline_summary(name)

    print(f"Imported playlist '{name}' from {input_path}")
    print(
        f"  Rows: {stats['rows_imported']} imported, "
        f"{stats['new_videos']} new videos, "
        f"{stats['existing_videos']} already in DB"
    )
    if stats["skipped_rows"]:
        print(f"  Skipped {stats['skipped_rows']} row(s) with unparseable Video URLs")
    if migrate:
        print("  Migrated existing spreadsheet columns into empty DB fields")

    print(
        "  Pipeline summary: "
        f"{summary.get('metadata_done', 0)} metadata, "
        f"{summary.get('transcript_ok', 0)} transcripts ok, "
        f"{summary.get('no_captions', 0)} no_captions, "
        f"{summary.get('unavailable', 0)} unavailable, "
        f"{summary.get('transcript_pending', 0)} transcript pending, "
        f"{summary.get('urls_done', 0)} urls extracted"
    )
    return name


def parse_args():
    parser = argparse.ArgumentParser(
        description="Import a playlist spreadsheet into the SQLite database."
    )
    parser.add_argument(
        "--input",
        "-i",
        required=True,
        help="Input playlist file (.xlsx or .csv)",
    )
    parser.add_argument(
        "--name",
        "-n",
        default=None,
        help="Playlist name in the database (default: input filename without extension)",
    )
    parser.add_argument(
        "--migrate",
        action="store_true",
        help="Seed metadata/transcript/URL columns from the spreadsheet into empty DB fields",
    )
    add_db_args(parser)
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()

    if not os.path.isfile(args.input):
        print(f"Input file not found: {args.input}")
        sys.exit(1)

    try:
        import_playlist(
            args.input,
            name=args.name,
            db_path=args.db,
            migrate=args.migrate,
        )
    except ValueError as exc:
        print(exc)
        sys.exit(1)
