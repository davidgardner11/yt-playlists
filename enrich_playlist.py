import argparse
import csv
import os
import re
import sys
import time
from pathlib import Path

import pandas as pd

try:
    from dotenv import load_dotenv
    from googleapiclient.discovery import build
    from googleapiclient.errors import HttpError
    import isodate
except ImportError:
    print(
        "Please install required packages: "
        "pip install google-api-python-client pandas openpyxl isodate python-dotenv"
    )
    sys.exit(1)

load_dotenv(Path(__file__).resolve().parent / ".env")

DEFAULT_INPUT = "AL-ML Playlist.xlsx"
SUPPORTED_EXTENSIONS = {".xlsx", ".csv"}
URLS_COLUMN = (
    "All websites links and URLs listed in the description or other video meta data "
    "(comma-separated)"
)
ENRICHED_COLUMNS = [
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
]
VIDEO_ID_PATTERNS = [
    r"(?:youtube\.com/watch\?v=|youtu\.be/|youtube\.com/embed/"
    r"|youtube\.com/v/|youtube\.com/shorts/)([0-9A-Za-z_-]{11})",
    r"(?:v=|\/)([0-9A-Za-z_-]{11})",
]
HTTP_URL_PATTERN = re.compile(r"https?://[^\s<>\"'\[\]()]+", re.IGNORECASE)
BATCH_SIZE = 50
MAX_RETRIES = 5
RETRY_BASE_DELAY_SEC = 2


def get_video_id(url):
    if not isinstance(url, str) or not url.strip():
        return None
    for pattern in VIDEO_ID_PATTERNS:
        match = re.search(pattern, url)
        if match:
            return match.group(1)
    return None


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


def extract_urls(*texts):
    found = []
    seen = set()
    for text in texts:
        if not isinstance(text, str) or not text.strip():
            continue
        for match in HTTP_URL_PATTERN.findall(text):
            url = match.rstrip(".,;)")
            if url not in seen:
                seen.add(url)
                found.append(url)
    return ", ".join(found)


def row_is_enriched(row):
    value = row.get("Channel Name", "")
    return isinstance(value, str) and value.strip() != ""


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


CSV_OUTPUT_DELIMITER = "\t"


def detect_csv_delimiter(path):
    with open(path, encoding="utf-8-sig", newline="") as handle:
        sample = handle.read(8192)
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters="\t,")
        return dialect.delimiter
    except csv.Error:
        if "\t" in sample.splitlines()[0]:
            return "\t"
        return ","


def normalize_columns(df):
    df.columns = df.columns.astype(str).str.strip()
    return df


def require_video_url_column(df):
    if "Video URL" in df.columns:
        return
    columns = ", ".join(df.columns.astype(str))
    raise ValueError(
        "Missing required column 'Video URL'. "
        f"Found columns: {columns}"
    )


def prepare_df_for_csv_export(df):
    export_df = df.copy()
    for column in export_df.select_dtypes(include="object").columns:
        export_df[column] = export_df[column].map(sanitize_csv_cell)
    return export_df


def sanitize_csv_cell(value):
    if pd.isna(value):
        return value
    text = str(value)
    return text.replace("\r\n", " ").replace("\n", " ").replace("\r", " ").strip()


def read_playlist(path):
    ext = Path(path).suffix.lower()
    if ext == ".xlsx":
        return normalize_columns(pd.read_excel(path))
    if ext == ".csv":
        delimiter = detect_csv_delimiter(path)
        df = pd.read_csv(path, sep=delimiter, encoding="utf-8-sig")
        df = normalize_columns(df)
        df.attrs["csv_delimiter"] = delimiter
        return df
    supported = ", ".join(sorted(SUPPORTED_EXTENSIONS))
    raise ValueError(f"Unsupported input format '{ext}'. Supported formats: {supported}")


def write_playlist(df, path):
    ext = Path(path).suffix.lower()
    if ext == ".xlsx":
        df.to_excel(path, index=False)
    elif ext == ".csv":
        export_df = prepare_df_for_csv_export(df)
        export_df.to_csv(
            path,
            sep=CSV_OUTPUT_DELIMITER,
            index=False,
            encoding="utf-8-sig",
            quoting=csv.QUOTE_ALL,
            lineterminator="\n",
        )
    else:
        supported = ", ".join(sorted(SUPPORTED_EXTENSIONS))
        raise ValueError(f"Unsupported output format '{ext}'. Supported formats: {supported}")


def default_output_path(input_path):
    path = Path(input_path)
    return str(path.with_name(f"{path.stem}_Enriched{path.suffix}"))


def apply_metadata(df, metadata_map):
    for column in ENRICHED_COLUMNS:
        if column not in df.columns:
            df[column] = ""

    for idx, row in df.iterrows():
        video_id = row.get("video_id")
        if not video_id or video_id not in metadata_map:
            continue
        for column, value in metadata_map[video_id].items():
            df.at[idx, column] = value


def fetch_youtube_metadata(input_path, api_key, output_path=None, force=False):
    youtube = build("youtube", "v3", developerKey=api_key)
    df = read_playlist(input_path)
    require_video_url_column(df)
    df["video_id"] = df["Video URL"].apply(get_video_id)

    invalid_urls = df[df["video_id"].isna()]
    if not invalid_urls.empty:
        print(f"\nWarning: {len(invalid_urls)} row(s) have unparseable Video URLs:")
        for idx, row in invalid_urls.iterrows():
            print(f"  Row {idx + 2}: {row['Video URL']}")

    if force:
        ids_to_fetch = df["video_id"].dropna().unique().tolist()
        skipped = 0
    else:
        needs_fetch = ~df.apply(row_is_enriched, axis=1)
        ids_to_fetch = df.loc[needs_fetch, "video_id"].dropna().unique().tolist()
        skipped = len(df) - needs_fetch.sum()

    if skipped:
        print(f"Skipping {skipped} already-enriched row(s). Use --force to refresh all.")

    metadata_map = {}
    if ids_to_fetch:
        metadata_map = fetch_metadata_for_ids(youtube, ids_to_fetch)
        apply_metadata(df, metadata_map)

    requested_ids = set(ids_to_fetch)
    missing_ids = requested_ids - set(metadata_map.keys())
    if missing_ids:
        print(f"\nWarning: {len(missing_ids)} video(s) not returned by the API "
              "(deleted, private, or unavailable):")
        for video_id in sorted(missing_ids):
            matching_rows = df.index[df["video_id"] == video_id].tolist()
            row_nums = ", ".join(str(i + 2) for i in matching_rows)
            print(f"  {video_id} (rows {row_nums})")

    df.drop(columns=["video_id"], inplace=True)

    if output_path is None:
        output_path = default_output_path(input_path)

    write_playlist(df, output_path)
    print(f"\nSuccess! Enriched playlist saved as: {output_path}")
    return output_path


def parse_args():
    parser = argparse.ArgumentParser(
        description=(
            "Enrich a YouTube playlist file with metadata from the YouTube Data API. "
            "Supports Excel (.xlsx) and CSV (.csv) files with comma or tab delimiters."
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
        help="Output file (default: <input>_Enriched with same extension)",
    )
    parser.add_argument(
        "--force",
        "-f",
        action="store_true",
        help="Re-fetch metadata for all rows, even if already enriched",
    )
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

    if not os.path.isfile(args.input):
        print(f"Input file not found: {args.input}")
        sys.exit(1)

    input_ext = Path(args.input).suffix.lower()
    if input_ext not in SUPPORTED_EXTENSIONS:
        supported = ", ".join(sorted(SUPPORTED_EXTENSIONS))
        print(f"Unsupported input format '{input_ext}'. Supported formats: {supported}")
        sys.exit(1)

    if args.output:
        output_ext = Path(args.output).suffix.lower()
        if output_ext not in SUPPORTED_EXTENSIONS:
            supported = ", ".join(sorted(SUPPORTED_EXTENSIONS))
            print(f"Unsupported output format '{output_ext}'. Supported formats: {supported}")
            sys.exit(1)

    try:
        fetch_youtube_metadata(
            args.input,
            api_key,
            output_path=args.output,
            force=args.force,
        )
    except ValueError as exc:
        print(exc)
        sys.exit(1)
