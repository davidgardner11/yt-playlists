import argparse

from playlist_db import DEFAULT_DB_PATH, PlaylistDB


def add_db_args(parser):
    parser.add_argument(
        "--db",
        default=None,
        help=f"SQLite database path (default: {DEFAULT_DB_PATH} or PLAYLIST_DB env var)",
    )


def add_playlist_args(parser, required=True):
    parser.add_argument(
        "--playlist",
        "-p",
        required=required,
        help="Playlist name in the database",
    )


def open_db(db_path=None):
    return PlaylistDB(db_path)


def maybe_export(db, playlist_name, export_path):
    if not export_path:
        return
    if not playlist_name:
        raise ValueError("--export requires --playlist to specify which playlist to export")

    from export_playlist import export_playlist_to_file

    export_playlist_to_file(db, playlist_name, export_path)


def parse_export_arg(parser):
    parser.add_argument(
        "--export",
        "-o",
        default=None,
        help="Export playlist to xlsx/csv after the run (requires --playlist)",
    )


def validate_playlist_arg(playlist_name, required=False):
    if required and not playlist_name:
        raise ValueError("--playlist is required for this command")
