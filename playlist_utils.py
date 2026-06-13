import csv
import re
from pathlib import Path
from urllib.parse import urlparse

import pandas as pd

SUPPORTED_EXTENSIONS = {".xlsx", ".csv"}
CSV_OUTPUT_DELIMITER = "\t"

URLS_COLUMN = (
    "All websites links and URLs listed in the description or other video meta data "
    "(comma-separated)"
)
TRANSCRIPT_COLUMN = "Full Video Transcript"
TRANSCRIPT_LANGUAGE_COLUMN = "Transcript Language"
TRANSCRIPT_STATUS_COLUMN = "Transcript Status"
TRANSCRIPT_URLS_COLUMN = "URLs from Transcript (comma-separated)"
ALL_URLS_COLUMN = "All URLs (description + transcript)"

VIDEO_ID_PATTERNS = [
    r"(?:youtube\.com/watch\?v=|youtu\.be/|youtube\.com/embed/"
    r"|youtube\.com/v/|youtube\.com/shorts/)([0-9A-Za-z_-]{11})",
    r"(?:v=|\/)([0-9A-Za-z_-]{11})",
]
HTTP_URL_PATTERN = re.compile(r"https?://[^\s<>\"'\[\]()]+", re.IGNORECASE)
WWW_URL_PATTERN = re.compile(
    r"\bwww\.[a-zA-Z0-9][-a-zA-Z0-9]*(?:\.[a-zA-Z0-9][-a-zA-Z0-9]*)+[^\s<>\"'\[\](),]*",
    re.IGNORECASE,
)
YOUTUBE_HOSTS = {"youtube.com", "www.youtube.com", "youtu.be", "m.youtube.com"}


def get_video_id(url):
    if not isinstance(url, str) or not url.strip():
        return None
    for pattern in VIDEO_ID_PATTERNS:
        match = re.search(pattern, url)
        if match:
            return match.group(1)
    return None


def normalize_url(url):
    cleaned = url.rstrip(".,;)")
    if cleaned.lower().startswith("www."):
        return f"https://{cleaned}"
    return cleaned


def is_youtube_url(url):
    try:
        host = urlparse(url).netloc.lower()
    except Exception:
        return False
    if host.startswith("www."):
        host = host[4:]
    return host in {"youtube.com", "youtu.be", "m.youtube.com"}


def extract_urls(*texts, include_youtube=True):
    found = []
    seen = set()

    for text in texts:
        if not isinstance(text, str) or not text.strip():
            continue

        for pattern in (HTTP_URL_PATTERN, WWW_URL_PATTERN):
            for match in pattern.findall(text):
                url = normalize_url(match)
                if not include_youtube and is_youtube_url(url):
                    continue
                if url not in seen:
                    seen.add(url)
                    found.append(url)

    return ", ".join(found)


def merge_url_columns(*columns):
    merged = []
    seen = set()
    for column in columns:
        if not isinstance(column, str) or not column.strip():
            continue
        for url in (part.strip() for part in column.split(",")):
            if url and url not in seen:
                seen.add(url)
                merged.append(url)
    return ", ".join(merged)


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


def require_column(df, column_name):
    if column_name in df.columns:
        return
    columns = ", ".join(df.columns.astype(str))
    raise ValueError(
        f"Missing required column '{column_name}'. Found columns: {columns}"
    )


def require_video_url_column(df):
    require_column(df, "Video URL")


def sanitize_csv_cell(value):
    if pd.isna(value):
        return value
    text = str(value)
    return text.replace("\r\n", " ").replace("\n", " ").replace("\r", " ").strip()


def prepare_df_for_csv_export(df):
    export_df = df.copy()
    for column in export_df.select_dtypes(include="object").columns:
        export_df[column] = export_df[column].map(sanitize_csv_cell)
    return export_df


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


def default_output_path(input_path, suffix):
    path = Path(input_path)
    return str(path.with_name(f"{path.stem}_{suffix}{path.suffix}"))


def validate_playlist_paths(input_path, output_path=None):
    input_ext = Path(input_path).suffix.lower()
    if input_ext not in SUPPORTED_EXTENSIONS:
        supported = ", ".join(sorted(SUPPORTED_EXTENSIONS))
        raise ValueError(f"Unsupported input format '{input_ext}'. Supported formats: {supported}")

    if output_path:
        output_ext = Path(output_path).suffix.lower()
        if output_ext not in SUPPORTED_EXTENSIONS:
            supported = ", ".join(sorted(SUPPORTED_EXTENSIONS))
            raise ValueError(
                f"Unsupported output format '{output_ext}'. Supported formats: {supported}"
            )


def cell_has_value(value):
    if pd.isna(value):
        return False
    return str(value).strip() != ""
