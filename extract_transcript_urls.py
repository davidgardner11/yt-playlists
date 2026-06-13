import argparse
import os
import sys

from playlist_utils import (
    ALL_URLS_COLUMN,
    TRANSCRIPT_COLUMN,
    TRANSCRIPT_STATUS_COLUMN,
    TRANSCRIPT_URLS_COLUMN,
    URLS_COLUMN,
    cell_has_value,
    default_output_path,
    extract_urls,
    merge_url_columns,
    read_playlist,
    require_column,
    validate_playlist_paths,
    write_playlist,
)

DEFAULT_INPUT = "AL-ML Playlist_Enriched_Transcripts.xlsx"


def row_has_transcript_urls(row):
    return cell_has_value(row.get(TRANSCRIPT_URLS_COLUMN, ""))


def transcript_is_usable(row):
    status = row.get(TRANSCRIPT_STATUS_COLUMN, "")
    if isinstance(status, str) and status.strip() and status.strip() != "ok":
        return False
    return cell_has_value(row.get(TRANSCRIPT_COLUMN, ""))


def extract_transcript_urls(
    input_path,
    output_path=None,
    force=False,
    include_youtube=True,
    add_combined_column=True,
):
    df = read_playlist(input_path)
    require_column(df, TRANSCRIPT_COLUMN)

    if TRANSCRIPT_URLS_COLUMN not in df.columns:
        df[TRANSCRIPT_URLS_COLUMN] = ""
    if add_combined_column and ALL_URLS_COLUMN not in df.columns:
        df[ALL_URLS_COLUMN] = ""

    updated = 0
    for idx, row in df.iterrows():
        if not force and row_has_transcript_urls(row):
            continue
        if not transcript_is_usable(row):
            continue

        transcript = row.get(TRANSCRIPT_COLUMN, "")
        urls = extract_urls(transcript, include_youtube=include_youtube)
        df.at[idx, TRANSCRIPT_URLS_COLUMN] = urls

        if add_combined_column:
            description_urls = row.get(URLS_COLUMN, "")
            df.at[idx, ALL_URLS_COLUMN] = merge_url_columns(description_urls, urls)

        updated += 1

    skipped = len(df) - updated
    if skipped and not force:
        print(f"Skipped {skipped} row(s) with existing transcript URLs. Use --force to refresh all.")
    print(f"Extracted URLs from {updated} transcript(s).")

    if output_path is None:
        output_path = default_output_path(input_path, "TranscriptURLs")

    write_playlist(df, output_path)
    print(f"\nSuccess! Playlist with transcript URLs saved as: {output_path}")
    return output_path


def parse_args():
    parser = argparse.ArgumentParser(
        description="Extract websites and URLs mentioned in video transcripts."
    )
    parser.add_argument(
        "--input",
        "-i",
        default=DEFAULT_INPUT,
        help=f"Input playlist file with transcripts (default: {DEFAULT_INPUT})",
    )
    parser.add_argument(
        "--output",
        "-o",
        default=None,
        help="Output file (default: <input>_TranscriptURLs with same extension)",
    )
    parser.add_argument(
        "--force",
        "-f",
        action="store_true",
        help="Re-extract transcript URLs for all rows",
    )
    parser.add_argument(
        "--exclude-youtube",
        action="store_true",
        help="Exclude youtube.com and youtu.be links from extracted URLs",
    )
    parser.add_argument(
        "--no-combined-column",
        action="store_true",
        help="Do not add the combined 'All URLs (description + transcript)' column",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()

    if not os.path.isfile(args.input):
        print(f"Input file not found: {args.input}")
        sys.exit(1)

    try:
        validate_playlist_paths(args.input, args.output)
        extract_transcript_urls(
            args.input,
            output_path=args.output,
            force=args.force,
            include_youtube=not args.exclude_youtube,
            add_combined_column=not args.no_combined_column,
        )
    except ValueError as exc:
        print(exc)
        sys.exit(1)
