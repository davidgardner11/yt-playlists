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
DEFAULT_DELAY_SEC = 2.5
IP_BLOCK_RETRY_DELAY_SEC = 30
CONSECUTIVE_IP_BLOCK_LIMIT = 2

TRANSIENT_ERRORS = (YouTubeRequestFailed,)
IP_BLOCK_ERRORS = (IpBlocked, RequestBlocked)


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


def is_ip_block_error(exc):
    if isinstance(exc, IP_BLOCK_ERRORS):
        return True
    if isinstance(exc, CouldNotRetrieveTranscript):
        message = str(exc).lower()
        return "blocking requests from your ip" in message or "ip has been blocked" in message
    return False


def format_error(exc):
    if is_ip_block_error(exc):
        return "YouTube IP rate limit"
    return f"{type(exc).__name__}: {exc}"


def empty_result(status):
    return {
        TRANSCRIPT_COLUMN: "",
        TRANSCRIPT_LANGUAGE_COLUMN: "",
        TRANSCRIPT_STATUS_COLUMN: status,
    }


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
        except (NoTranscriptFound, TranscriptsDisabled):
            return empty_result("no_captions")
        except (VideoUnavailable, VideoUnplayable, AgeRestricted):
            return empty_result("unavailable")
        except TRANSIENT_ERRORS + IP_BLOCK_ERRORS + (CouldNotRetrieveTranscript,) as exc:
            last_error = exc
            if is_ip_block_error(exc):
                if attempt < MAX_RETRIES - 1:
                    print(
                        f"  IP rate limit for {video_id}. "
                        f"Waiting {IP_BLOCK_RETRY_DELAY_SEC}s before retry..."
                    )
                    time.sleep(IP_BLOCK_RETRY_DELAY_SEC)
                    continue
                return empty_result("ip_blocked")

            if attempt < MAX_RETRIES - 1:
                delay = RETRY_BASE_DELAY_SEC * (2 ** attempt)
                print(f"  Transient error for {video_id} ({format_error(exc)}). Retrying in {delay}s...")
                time.sleep(delay)
                continue
            return empty_result("error")
        except Exception as exc:
            print(f"  Unexpected error for {video_id}: {format_error(exc)}")
            return empty_result("error")

    print(f"  Failed to fetch transcript for {video_id}: {format_error(last_error)}")
    return empty_result("error")


def ensure_transcript_columns(df):
    for column in TRANSCRIPT_COLUMNS:
        if column not in df.columns:
            df[column] = ""


def apply_transcript_for_video(df, video_id, result):
    ensure_transcript_columns(df)
    mask = df["video_id"] == video_id
    for idx in df.index[mask]:
        for column, value in result.items():
            df.at[idx, column] = value


def load_playlist_for_run(input_path, output_path, force):
    if not force and output_path and os.path.isfile(output_path):
        print(f"Resuming from existing output file: {output_path}")
        return read_playlist(output_path)
    return read_playlist(input_path)


def fetch_transcripts(
    input_path,
    output_path=None,
    force=False,
    languages=None,
    delay_sec=DEFAULT_DELAY_SEC,
    max_videos=None,
    stop_on_ip_block=True,
):
    languages = languages or DEFAULT_LANGUAGES

    if output_path is None:
        output_path = default_output_path(input_path, "Transcripts")

    df = load_playlist_for_run(input_path, output_path, force)
    require_video_url_column(df)
    df["video_id"] = df["Video URL"].apply(get_video_id)
    ensure_transcript_columns(df)

    if force:
        ids_to_fetch = df["video_id"].dropna().unique().tolist()
        skipped = 0
    else:
        needs_fetch = ~df.apply(row_has_transcript, axis=1)
        ids_to_fetch = df.loc[needs_fetch, "video_id"].dropna().unique().tolist()
        skipped = len(df) - needs_fetch.sum()

    if max_videos is not None:
        ids_to_fetch = ids_to_fetch[:max_videos]

    if skipped:
        print(f"Skipping {skipped} row(s) with existing transcripts. Use --force to refresh all.")

    api = YouTubeTranscriptApi()
    total = len(ids_to_fetch)
    status_counts = {}
    consecutive_ip_blocks = 0
    stopped_early = False

    print(f"Fetching transcripts for {total} unique videos...")
    print(f"Saving progress to: {output_path}")

    for index, video_id in enumerate(ids_to_fetch, start=1):
        print(f"  [{index}/{total}] {video_id}")
        result = fetch_transcript_for_video(api, video_id, languages)
        apply_transcript_for_video(df, video_id, result)

        status = result[TRANSCRIPT_STATUS_COLUMN]
        status_counts[status] = status_counts.get(status, 0) + 1

        df.drop(columns=["video_id"], inplace=True, errors="ignore")
        write_playlist(df, output_path)
        df["video_id"] = df["Video URL"].apply(get_video_id)

        if status == "ip_blocked":
            consecutive_ip_blocks += 1
            if stop_on_ip_block and consecutive_ip_blocks >= CONSECUTIVE_IP_BLOCK_LIMIT:
                print(
                    f"\nStopping early after {consecutive_ip_blocks} consecutive IP rate-limit errors. "
                    f"Progress saved to {output_path}. "
                    f"Wait 30-60 minutes, then re-run the same command to resume."
                )
                stopped_early = True
                break
        else:
            consecutive_ip_blocks = 0

        if index < total and delay_sec > 0:
            time.sleep(delay_sec)

    if status_counts:
        summary = ", ".join(f"{count} {status}" for status, count in sorted(status_counts.items()))
        print(f"\nTranscript status summary: {summary}")

    df.drop(columns=["video_id"], inplace=True, errors="ignore")

    if stopped_early:
        print(f"\nPartial results saved as: {output_path}")
    else:
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
    parser.add_argument(
        "--max-videos",
        type=int,
        default=None,
        help="Maximum number of videos to fetch this run (useful for batching)",
    )
    parser.add_argument(
        "--continue-on-ip-block",
        action="store_true",
        help="Keep going after IP rate-limit errors instead of stopping early",
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
            max_videos=args.max_videos,
            stop_on_ip_block=not args.continue_on_ip_block,
        )
    except ValueError as exc:
        print(exc)
        sys.exit(1)
