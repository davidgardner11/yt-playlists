import argparse
import os
import sys
import time

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

from pipeline_cli import add_db_args, add_playlist_args, maybe_export, open_db, parse_export_arg, validate_playlist_arg
from playlist_utils import TRANSCRIPT_COLUMN, TRANSCRIPT_LANGUAGE_COLUMN, TRANSCRIPT_STATUS_COLUMN

DEFAULT_LANGUAGES = ["en", "en-US", "en-GB"]
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


def fetch_transcripts(
    playlist_name,
    db_path=None,
    force=False,
    languages=None,
    delay_sec=DEFAULT_DELAY_SEC,
    max_videos=None,
    stop_on_ip_block=True,
    export_path=None,
):
    validate_playlist_arg(playlist_name, required=True)
    languages = languages or DEFAULT_LANGUAGES

    with open_db(db_path) as db:
        if not db.get_playlist_by_name(playlist_name):
            raise ValueError(f"Playlist not found in database: {playlist_name}")

        videos = db.get_videos_needing_transcripts(playlist_name=playlist_name, force=force)
        if max_videos is not None:
            videos = videos[:max_videos]

        if not videos:
            print("No videos need transcript fetching.")
        else:
            api = YouTubeTranscriptApi()
            total = len(videos)
            status_counts = {}
            consecutive_ip_blocks = 0
            stopped_early = False

            print(f"Fetching transcripts for {total} unique videos...")
            for index, video in enumerate(videos, start=1):
                video_id = video["video_id"]
                print(f"  [{index}/{total}] {video_id}")
                result = fetch_transcript_for_video(api, video_id, languages)
                db.upsert_video_transcript(video_id, result)

                status = result[TRANSCRIPT_STATUS_COLUMN]
                status_counts[status] = status_counts.get(status, 0) + 1

                if status == "ip_blocked":
                    consecutive_ip_blocks += 1
                    if stop_on_ip_block and consecutive_ip_blocks >= CONSECUTIVE_IP_BLOCK_LIMIT:
                        print(
                            f"\nStopping early after {consecutive_ip_blocks} consecutive IP rate-limit errors. "
                            "Progress saved to database. "
                            "Wait 30-60 minutes, then re-run the same command to resume."
                        )
                        stopped_early = True
                        break
                else:
                    consecutive_ip_blocks = 0

                if index < total and delay_sec > 0:
                    time.sleep(delay_sec)

            if status_counts:
                summary = ", ".join(
                    f"{count} {status}" for status, count in sorted(status_counts.items())
                )
                print(f"\nTranscript status summary: {summary}")
            if stopped_early:
                print("Partial transcript results saved to database.")

        summary = db.get_pipeline_summary(playlist_name)
        print(
            f"\nTranscript pipeline for '{playlist_name}': "
            f"{summary.get('transcript_ok', 0)} ok, "
            f"{summary.get('no_captions', 0)} no_captions, "
            f"{summary.get('unavailable', 0)} unavailable, "
            f"{summary.get('ip_blocked', 0)} ip_blocked, "
            f"{summary.get('errors', 0)} error, "
            f"{summary.get('transcript_pending', 0)} pending"
        )
        maybe_export(db, playlist_name, export_path)

    return playlist_name


def parse_args():
    parser = argparse.ArgumentParser(
        description=(
            "Fetch YouTube video transcripts for videos in a database playlist. "
            "Uses youtube-transcript-api (no API key required)."
        )
    )
    add_playlist_args(parser, required=True)
    parser.add_argument(
        "--force",
        "-f",
        action="store_true",
        help="Re-fetch transcripts for videos previously marked ok",
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
    add_db_args(parser)
    parse_export_arg(parser)
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()

    try:
        fetch_transcripts(
            args.playlist,
            db_path=args.db,
            force=args.force,
            languages=parse_languages(args.language),
            delay_sec=args.delay,
            max_videos=args.max_videos,
            stop_on_ip_block=not args.continue_on_ip_block,
            export_path=args.export,
        )
    except ValueError as exc:
        print(exc)
        sys.exit(1)
