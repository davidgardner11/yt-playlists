import argparse
import sys
import time
from datetime import datetime

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
TRANSIENT_MAX_RETRIES = 5
TRANSIENT_BASE_DELAY_SEC = 2
DEFAULT_DELAY_SEC = 2.5
DEFAULT_INITIAL_IP_BACKOFF_SEC = 30
DEFAULT_MAX_IP_BACKOFF_SEC = 30 * 60

TRANSIENT_ERRORS = (YouTubeRequestFailed,)
IP_BLOCK_ERRORS = (IpBlocked, RequestBlocked)
PERMANENT_FAILURE_STATUSES = {"no_captions", "unavailable", "error"}


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


def format_delay(seconds):
    seconds = int(seconds)
    if seconds < 60:
        return f"{seconds}s"
    minutes, secs = divmod(seconds, 60)
    if minutes < 60:
        return f"{minutes}m {secs}s"
    hours, minutes = divmod(minutes, 60)
    return f"{hours}h {minutes}m {secs}s"


def log(message):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{timestamp}] {message}", flush=True)


def empty_result(status):
    return {
        TRANSCRIPT_COLUMN: "",
        TRANSCRIPT_LANGUAGE_COLUMN: "",
        TRANSCRIPT_STATUS_COLUMN: status,
    }


def fetch_transcript_for_video(api, video_id, languages, ip_backoff_sec, max_ip_backoff_sec):
    transient_attempt = 0

    while True:
        try:
            fetched = api.fetch(video_id, languages=languages)
            text = " ".join(snippet.text.strip() for snippet in fetched.snippets if snippet.text)
            return (
                {
                    TRANSCRIPT_COLUMN: text,
                    TRANSCRIPT_LANGUAGE_COLUMN: format_transcript_language(fetched),
                    TRANSCRIPT_STATUS_COLUMN: "ok",
                },
                DEFAULT_INITIAL_IP_BACKOFF_SEC,
            )
        except (NoTranscriptFound, TranscriptsDisabled):
            return empty_result("no_captions"), ip_backoff_sec
        except (VideoUnavailable, VideoUnplayable, AgeRestricted):
            return empty_result("unavailable"), ip_backoff_sec
        except TRANSIENT_ERRORS + IP_BLOCK_ERRORS + (CouldNotRetrieveTranscript,) as exc:
            if is_ip_block_error(exc):
                wait_sec = min(ip_backoff_sec, max_ip_backoff_sec)
                log(
                    f"IP rate limit for {video_id}. "
                    f"Waiting {format_delay(wait_sec)} before retry "
                    f"(next backoff up to {format_delay(min(wait_sec * 2, max_ip_backoff_sec))})..."
                )
                time.sleep(wait_sec)
                ip_backoff_sec = min(max(ip_backoff_sec * 2, DEFAULT_INITIAL_IP_BACKOFF_SEC), max_ip_backoff_sec)
                transient_attempt = 0
                continue

            transient_attempt += 1
            if transient_attempt < TRANSIENT_MAX_RETRIES:
                delay = TRANSIENT_BASE_DELAY_SEC * (2 ** (transient_attempt - 1))
                log(
                    f"Transient error for {video_id} ({format_error(exc)}). "
                    f"Retrying in {format_delay(delay)} ({transient_attempt}/{TRANSIENT_MAX_RETRIES - 1})..."
                )
                time.sleep(delay)
                continue

            log(f"Giving up on {video_id} after transient errors: {format_error(exc)}")
            return empty_result("error"), ip_backoff_sec
        except Exception as exc:
            log(f"Unexpected error for {video_id}: {format_error(exc)}")
            return empty_result("error"), ip_backoff_sec


def fetch_transcripts(
    playlist_name,
    db_path=None,
    force=False,
    languages=None,
    delay_sec=DEFAULT_DELAY_SEC,
    max_videos=None,
    export_path=None,
    initial_ip_backoff_sec=DEFAULT_INITIAL_IP_BACKOFF_SEC,
    max_ip_backoff_sec=DEFAULT_MAX_IP_BACKOFF_SEC,
):
    validate_playlist_arg(playlist_name, required=True)
    languages = languages or DEFAULT_LANGUAGES

    with open_db(db_path) as db:
        if not db.get_playlist_by_name(playlist_name):
            raise ValueError(f"Playlist not found in database: {playlist_name}")

        ip_backoff_sec = initial_ip_backoff_sec
        status_counts = {}
        processed = 0

        log(
            f"Starting overnight-safe transcript fetch for '{playlist_name}'. "
            f"IP backoff: {format_delay(initial_ip_backoff_sec)} -> {format_delay(max_ip_backoff_sec)}. "
            "The process will keep retrying and will not exit on rate limits."
        )

        while True:
            videos = db.get_videos_needing_transcripts(playlist_name=playlist_name, force=force)
            if max_videos is not None:
                remaining = max(0, max_videos - processed)
                videos = videos[:remaining]

            if not videos:
                log("No more videos need transcript fetching.")
                break

            total = len(videos)
            log(f"Work queue: {total} video(s) needing transcripts.")

            for index, video in enumerate(videos, start=1):
                video_id = video["video_id"]
                log(f"[{index}/{total}] Fetching {video_id}")

                result, ip_backoff_sec = fetch_transcript_for_video(
                    YouTubeTranscriptApi(),
                    video_id,
                    languages,
                    ip_backoff_sec,
                    max_ip_backoff_sec,
                )
                db.upsert_video_transcript(video_id, result)

                status = result[TRANSCRIPT_STATUS_COLUMN]
                status_counts[status] = status_counts.get(status, 0) + 1
                processed += 1

                if status in PERMANENT_FAILURE_STATUSES or status == "ok":
                    if delay_sec > 0:
                        time.sleep(delay_sec)
                else:
                    time.sleep(min(delay_sec, 5))

            if max_videos is not None and processed >= max_videos:
                log(f"Reached --max-videos limit ({max_videos}).")
                break

            pending = len(db.get_videos_needing_transcripts(playlist_name=playlist_name, force=force))
            if pending == 0:
                break

            log(f"{pending} video(s) still pending. Refreshing work queue...")

        if status_counts:
            summary = ", ".join(f"{count} {status}" for status, count in sorted(status_counts.items()))
            log(f"Run status summary: {summary}")

        summary = db.get_pipeline_summary(playlist_name)
        log(
            f"Transcript pipeline for '{playlist_name}': "
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
            "Uses youtube-transcript-api (no API key required). "
            "Retries indefinitely on IP rate limits with exponential backoff."
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
        help=f"Seconds to wait between successful transcript requests (default: {DEFAULT_DELAY_SEC})",
    )
    parser.add_argument(
        "--max-videos",
        type=int,
        default=None,
        help="Maximum number of videos to fetch this run (default: no limit)",
    )
    parser.add_argument(
        "--initial-ip-backoff",
        type=float,
        default=DEFAULT_INITIAL_IP_BACKOFF_SEC,
        help=f"Initial IP rate-limit backoff in seconds (default: {DEFAULT_INITIAL_IP_BACKOFF_SEC})",
    )
    parser.add_argument(
        "--max-ip-backoff",
        type=float,
        default=DEFAULT_MAX_IP_BACKOFF_SEC,
        help=f"Maximum IP rate-limit backoff in seconds (default: {DEFAULT_MAX_IP_BACKOFF_SEC})",
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
            export_path=args.export,
            initial_ip_backoff_sec=args.initial_ip_backoff,
            max_ip_backoff_sec=args.max_ip_backoff,
        )
    except ValueError as exc:
        print(exc)
        sys.exit(1)
