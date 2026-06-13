import argparse
import os
import sys
import time
from pathlib import Path

try:
    from youtube_transcript_api import YouTubeTranscriptApi
    from youtube_transcript_api._errors import (
        AgeRestricted,
        CouldNotRetrieveTranscript,
        IpBlocked,
        NoTranscriptFound,
        RequestBlocked,
        TranscriptsDisabled,
        VideoUnavailable,
        VideoUnplayable,
        YouTubeRequestFailed,
    )
except ImportError:
    print("Please install required packages: pip install -r requirements.txt")
    sys.exit(1)

from playlist_utils import (
    TRANSCRIPT_COLUMN,
    TRANSCRIPT_LANGUAGE_COLUMN,
    TRANSCRIPT_STATUS_COLUMN,
    cell_has_value,
    default_output_path,
    get_video_id,
    read_playlist,
    require_video_url_column,
    validate_playlist_paths,
    write_playlist,
)

DEFAULT_INPUT = "AL-ML Playlist_Enriched.xlsx"
DEFAULT_LANGUAGES = ["en", "en-US", "en-GB"]
TRANSCRIPT_COLUMNS = [
    TRANSCRIPT_COLUMN,
    TRANSCRIPT_LANGUAGE_COLUMN,
    TRANSCRIPT_STATUS_COLUMN,
]
MAX_RETRIES = 3
RETRY_BASE_DELAY_SEC = 2
DEFAULT_DELAY_SEC = 0.75

RETRYABLE_ERRORS = (
    IpBlocked,
    RequestBlocked,
    YouTubeRequestFailed,
    CouldNotRetrieveTranscript,
)


def parse_languages(language_arg):
    if not language_arg:
        return DEFAULT_LANGUAGES
    return [part.strip() for part in language_arg.split(",") if part.strip()]


def format_transcript_language(fetched):
    language = fetched.language_code or "unknown"
    if fetched.is_generated:
        return f"{language} (auto-generated)"
    return language


def row_has_transcript(row):
    return cell_has_value(row.get(TRANSCRIPT_COLUMN, ""))


def fetch_transcript_for_video(api, video_id, languages):
    last_error = None
    for attempt in range(MAX_RETRIES):
        try:
            fetched = api.fetch(video_id, languages=languages)
            text = " ".join(snippet.text.strip() for snippet in fetched.snippets if snippet.text)
            return {
                TRANSCRIPT_COLUMN: text,
                TRANSCRIPT_LANGUAGE_COLUMN: format_transcript_language(fetched),
                TRANSCRIPT_STATUS_COLUMN: "ok",
            }
        except RETRYABLE_ERRORS as exc:
            last_error = exc
            if attempt < MAX_RETRIES - 1:
                delay = RETRY_BASE_DELAY_SEC * (2 ** attempt)
                print(f"  Retryable error for {video_id}: {exc}. Retrying in {delay}s...")
                time.sleep(delay)
                continue
            return {
                TRANSCRIPT_COLUMN: "",
                TRANSCRIPT_LANGUAGE_COLUMN: "",
                TRANSCRIPT_STATUS_COLUMN: "error",
            }
        except (NoTranscriptFound, TranscriptsDisabled):
            return {
                TRANSCRIPT_COLUMN: "",
                TRANSCRIPT_LANGUAGE_COLUMN: "",
                TRANSCRIPT_STATUS_COLUMN: "no_captions",
            }
        except (VideoUnavailable, VideoUnplayable, AgeRestricted):
            return {
                TRANSCRIPT_COLUMN: "",
                TRANSCRIPT_LANGUAGE_COLUMN: "",
                TRANSCRIPT_STATUS_COLUMN: "unavailable",
            }
        except Exception as exc:
            print(f"  Unexpected error for {video_id}: {exc}")
            return {
                TRANSCRIPT_COLUMN: "",
                TRANSCRIPT_LANGUAGE_COLUMN: "",
                TRANSCRIPT_STATUS_COLUMN: "error",
            }

    print(f"  Failed to fetch transcript for {video_id}: {last_error}")
    return {
        TRANSCRIPT_COLUMN: "",
        TRANSCRIPT_LANGUAGE_COLUMN: "",
        TRANSCRIPT_STATUS_COLUMN: "error",
    }


def apply_transcripts(df, transcript_map):
    for column in TRANSCRIPT_COLUMNS:
        if column not in df.columns:
            df[column] = ""

    for idx, row in df.iterrows():
        video_id = row.get("video_id")
        if not video_id or video_id not in transcript_map:
            continue
        for column, value in transcript_map[video_id].items():
            df.at[idx, column] = value


def fetch_transcripts(input_path, output_path=None, force=False, languages=None, delay_sec=DEFAULT_DELAY_SEC):
    languages = languages or DEFAULT_LANGUAGES
    df = read_playlist(input_path)
    require_video_url_column(df)
    df["video_id"] = df["Video URL"].apply(get_video_id)

    if force:
        ids_to_fetch = df["video_id"].dropna().unique().tolist()
        skipped = 0
    else:
        needs_fetch = ~df.apply(row_has_transcript, axis=1)
        ids_to_fetch = df.loc[needs_fetch, "video_id"].dropna().unique().tolist()
        skipped = len(df) - needs_fetch.sum()

    if skipped:
        print(f"Skipping {skipped} row(s) with existing transcripts. Use --force to refresh all.")

    api = YouTubeTranscriptApi()
    transcript_map = {}
    total = len(ids_to_fetch)

    print(f"Fetching transcripts for {total} unique videos...")
    for index, video_id in enumerate(ids_to_fetch, start=1):
        print(f"  [{index}/{total}] {video_id}")
        transcript_map[video_id] = fetch_transcript_for_video(api, video_id, languages)
        if index < total and delay_sec > 0:
            time.sleep(delay_sec)

    if ids_to_fetch:
        apply_transcripts(df, transcript_map)

    status_counts = {}
    for result in transcript_map.values():
        status = result[TRANSCRIPT_STATUS_COLUMN]
        status_counts[status] = status_counts.get(status, 0) + 1

    if status_counts:
        summary = ", ".join(f"{count} {status}" for status, count in sorted(status_counts.items()))
        print(f"\nTranscript status summary: {summary}")

    df.drop(columns=["video_id"], inplace=True)

    if output_path is None:
        output_path = default_output_path(input_path, "Transcripts")

    write_playlist(df, output_path)
    print(f"\nSuccess! Playlist with transcripts saved as: {output_path}")
    return output_path


def parse_args():
    parser = argparse.ArgumentParser(
        description=(
            "Fetch YouTube video transcripts and add them to a playlist file. "
            "Uses youtube-transcript-api (no API key required)."
        )
    )
    parser.add_argument(
        "--input",
        "-i",
        default=DEFAULT_INPUT,
        help=f"Input playlist file (.xlsx or .csv, default: {DEFAULT_INPUT})",
    )
    parser.add_argument(
        "--output",
        "-o",
        default=None,
        help="Output file (default: <input>_Transcripts with same extension)",
    )
    parser.add_argument(
        "--force",
        "-f",
        action="store_true",
        help="Re-fetch transcripts for all rows, even if already populated",
    )
    parser.add_argument(
        "--language",
        "-l",
        default=",".join(DEFAULT_LANGUAGES),
        help="Preferred transcript languages, comma-separated (default: en,en-US,en-GB)",
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=DEFAULT_DELAY_SEC,
        help=f"Seconds to wait between transcript requests (default: {DEFAULT_DELAY_SEC})",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()

    if not os.path.isfile(args.input):
        print(f"Input file not found: {args.input}")
        sys.exit(1)

    try:
        validate_playlist_paths(args.input, args.output)
        fetch_transcripts(
            args.input,
            output_path=args.output,
            force=args.force,
            languages=parse_languages(args.language),
            delay_sec=args.delay,
        )
    except ValueError as exc:
        print(exc)
        sys.exit(1)
