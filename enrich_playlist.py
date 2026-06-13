import argparse
import os
import sys
import time
from pathlib import Path

try:
    from dotenv import load_dotenv
    from googleapiclient.discovery import build
    from googleapiclient.errors import HttpError
    import isodate
except ImportError:
    print("Please install required packages: pip install -r requirements.txt")
    sys.exit(1)

from pipeline_cli import add_db_args, add_playlist_args, maybe_export, open_db, parse_export_arg, validate_playlist_arg
from playlist_utils import URLS_COLUMN, extract_urls

load_dotenv(Path(__file__).resolve().parent / ".env")

BATCH_SIZE = 50
MAX_RETRIES = 5
RETRY_BASE_DELAY_SEC = 2


def format_duration(raw_duration):
    if not raw_duration:
        return ""
    try:
        duration = isodate.parse_duration(raw_duration)
        total_seconds = int(duration.total_seconds())
        hours, remainder = divmod(total_seconds, 3600)
        minutes, seconds = divmod(remainder, 60)
        if hours:
            return f"{hours}:{minutes:02d}:{seconds:02d}"
        return f"{minutes}:{seconds:02d}"
    except Exception:
        return raw_duration


def execute_with_retry(request):
    for attempt in range(MAX_RETRIES):
        try:
            return request.execute()
        except HttpError as exc:
            status = exc.resp.status
            if status in (403, 429, 500, 503) and attempt < MAX_RETRIES - 1:
                delay = RETRY_BASE_DELAY_SEC * (2 ** attempt)
                reason = "quota/rate limit" if status in (403, 429) else "server error"
                print(
                    f"  API {reason} (HTTP {status}). "
                    f"Retrying in {delay}s ({attempt + 1}/{MAX_RETRIES - 1})..."
                )
                time.sleep(delay)
                continue
            raise


def parse_video_metadata(item):
    snippet = item.get("snippet", {})
    content_details = item.get("contentDetails", {})
    statistics = item.get("statistics", {})

    description = snippet.get("description", "")
    tags = snippet.get("tags", [])

    return {
        "Channel Name": snippet.get("channelTitle", ""),
        "Channel ID": snippet.get("channelId", ""),
        "Publish Date": snippet.get("publishedAt", "")[:10],
        "Video Length": format_duration(content_details.get("duration", "")),
        "View Count": statistics.get("viewCount", ""),
        "Like Count": statistics.get("likeCount", ""),
        "Comment Count": statistics.get("commentCount", ""),
        "Full Video Description": description,
        "Tags/Keywords": ", ".join(tags),
        URLS_COLUMN: extract_urls(description, ", ".join(tags)),
    }


def fetch_metadata_for_ids(youtube, video_ids):
    metadata_map = {}
    unique_ids = list(dict.fromkeys(video_ids))

    print(f"Fetching metadata for {len(unique_ids)} unique videos...")
    for i in range(0, len(unique_ids), BATCH_SIZE):
        batch_ids = unique_ids[i : i + BATCH_SIZE]
        batch_num = i // BATCH_SIZE + 1
        total_batches = (len(unique_ids) + BATCH_SIZE - 1) // BATCH_SIZE
        print(f"  Batch {batch_num}/{total_batches} ({len(batch_ids)} videos)")

        request = youtube.videos().list(
            part="snippet,contentDetails,statistics",
            id=",".join(batch_ids),
        )
        response = execute_with_retry(request)

        for item in response.get("items", []):
            metadata_map[item["id"]] = parse_video_metadata(item)

    return metadata_map


def enrich_playlist_metadata(playlist_name, api_key, db_path=None, force=False, export_path=None):
    validate_playlist_arg(playlist_name, required=True)

    with open_db(db_path) as db:
        if not db.get_playlist_by_name(playlist_name):
            raise ValueError(f"Playlist not found in database: {playlist_name}")

        videos = db.get_videos_needing_metadata(playlist_name=playlist_name, force=force)
        if not videos:
            print("No videos need metadata enrichment.")
        else:
            youtube = build("youtube", "v3", developerKey=api_key)
            video_ids = [video["video_id"] for video in videos]
            metadata_map = fetch_metadata_for_ids(youtube, video_ids)

            for video_id in video_ids:
                if video_id in metadata_map:
                    db.upsert_video_metadata(video_id, metadata_map[video_id])

            missing_ids = set(video_ids) - set(metadata_map.keys())
            if missing_ids:
                print(
                    f"\nWarning: {len(missing_ids)} video(s) not returned by the API "
                    "(deleted, private, or unavailable):"
                )
                for video_id in sorted(missing_ids):
                    print(f"  {video_id}")

        summary = db.get_pipeline_summary(playlist_name)
        print(
            f"\nMetadata summary for '{playlist_name}': "
            f"{summary.get('metadata_done', 0)}/{summary.get('total', 0)} complete"
        )
        maybe_export(db, playlist_name, export_path)

    return playlist_name


def parse_args():
    parser = argparse.ArgumentParser(
        description="Enrich videos in a database playlist with YouTube Data API metadata."
    )
    add_playlist_args(parser, required=True)
    parser.add_argument(
        "--force",
        "-f",
        action="store_true",
        help="Re-fetch metadata for videos that already have metadata",
    )
    add_db_args(parser)
    parse_export_arg(parser)
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    api_key = os.environ.get("YOUTUBE_API_KEY", "").strip()

    if not api_key:
        print(
            "Missing API key. Add YOUTUBE_API_KEY to a .env file in the project root.\n"
            "Copy .env.example to .env and paste your key there."
        )
        sys.exit(1)

    try:
        enrich_playlist_metadata(
            args.playlist,
            api_key,
            db_path=args.db,
            force=args.force,
            export_path=args.export,
        )
    except ValueError as exc:
        print(exc)
        sys.exit(1)
