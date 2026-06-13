# YouTube Playlist Enricher

A Python script that enriches a playlist of YouTube videos with metadata from the [YouTube Data API v3](https://developers.google.com/youtube/v3). It reads video URLs from an Excel (`.xlsx`) or CSV (`.csv`) file, fetches channel info, statistics, descriptions, tags, and extracted links, then writes an enriched copy of the file.

## What it does

Given a playlist file with YouTube video URLs, `enrich_playlist.py` will:

1. Extract video IDs from each URL
2. Fetch metadata from the YouTube API (in batches of 50)
3. Add enriched columns to your playlist
4. Save the result as a new file (by default, `<input>_Enriched` with the same extension)

The script deduplicates video IDs before calling the API, skips rows that are already enriched, retries on rate-limit errors, and warns about missing or unparseable videos.

## Prerequisites

- Python 3.10+ (tested with 3.14)
- A Google Cloud project with the **YouTube Data API v3** enabled
- A YouTube Data API key

## Project files

| File | Purpose |
|------|---------|
| `enrich_playlist.py` | Main enrichment script |
| `requirements.txt` | Python dependencies |
| `.env.example` | Template for API key configuration |
| `.env` | Your local API key (not committed to git) |
| `.gitignore` | Excludes secrets, virtualenv, macOS metadata, and local spreadsheets |
| `AL-ML Playlist.xlsx` | Example/default input spreadsheet (local only; not tracked in git) |

## Setup

### 1. Clone and enter the project

```bash
cd yt-playlists
```

### 2. Create a virtual environment

```bash
python3 -m venv .venv
source .venv/bin/activate
```

### 3. Install dependencies

```bash
pip install -r requirements.txt
```

### 4. Get a YouTube Data API key

1. Go to the [Google Cloud Console](https://console.cloud.google.com/)
2. Create or select a project
3. Enable **YouTube Data API v3** (APIs & Services → Library)
4. Create an API key (APIs & Services → Credentials → Create credentials → API key)
5. Optionally restrict the key to YouTube Data API v3 only

### 5. Configure your API key

Copy the example env file and add your key:

```bash
cp .env.example .env
```

Edit `.env`:

```env
YOUTUBE_API_KEY=your-youtube-data-api-v3-key-here
```

> **Note:** `.env` is listed in `.gitignore` and should never be committed. Only `.env.example` is tracked in git.

## Input file format

The script accepts **Excel (`.xlsx`)** or **CSV (`.csv`)** files. The only required column is **`Video URL`**.

A minimal two-column file works:

| Column | Required | Description |
|--------|----------|-------------|
| `Video Title` | No | Existing title (preserved as-is) |
| `Video URL` | **Yes** | YouTube link for each video |

Any other columns in your input file are preserved unchanged. The script also adds the enriched columns listed below.

### CSV input notes

- Comma- and tab-delimited CSV files are both supported
- UTF-8 with or without BOM is supported
- Column names are trimmed of surrounding whitespace

### Supported URL formats

- `https://www.youtube.com/watch?v=VIDEO_ID`
- `https://youtu.be/VIDEO_ID`
- `https://youtube.com/shorts/VIDEO_ID`
- `https://youtube.com/embed/VIDEO_ID`

## Usage

### Basic run

Enriches the default input file and writes `AL-ML Playlist_Enriched.xlsx`:

```bash
python enrich_playlist.py
```

Or with the virtual environment explicitly:

```bash
.venv/bin/python enrich_playlist.py
```

### Specify input and output files

```bash
python enrich_playlist.py --input "AL-ML Playlist.xlsx" --output "AL-ML Playlist_Enriched.xlsx"
```

Short flags:

```bash
python enrich_playlist.py -i "AL-ML Playlist.xlsx" -o "AL-ML Playlist_Enriched.xlsx"
```

### CSV input

```bash
python enrich_playlist.py -i "AL-ML Playlist.csv"
```

This writes `AL-ML Playlist_Enriched.csv` by default.

### Cross-format conversion

You can read one format and write another:

```bash
python enrich_playlist.py -i "AL-ML Playlist.csv" -o "AL-ML Playlist_Enriched.xlsx"
```

### Re-fetch all rows

By default, rows that already have a `Channel Name` are skipped. Use `--force` to refresh everything:

```bash
python enrich_playlist.py --force
```

### Incremental enrichment

To add metadata for new videos only, run against an already-enriched file:

```bash
python enrich_playlist.py -i "AL-ML Playlist_Enriched.xlsx"
```

New rows without a `Channel Name` will be fetched; existing enriched rows are left unchanged.

## CLI reference

| Flag | Description |
|------|-------------|
| `--input`, `-i` | Input playlist file (`.xlsx` or `.csv`; default: `AL-ML Playlist.xlsx`) |
| `--output`, `-o` | Output file (default: `<input>_Enriched` with same extension) |
| `--force`, `-f` | Re-fetch metadata for all rows, even if already enriched |

## Output columns

The script adds (or updates) these columns:

| Column | Source |
|--------|--------|
| `Channel Name` | YouTube channel title |
| `Channel ID` | YouTube channel ID |
| `Publish Date` | Video publish date (`YYYY-MM-DD`) |
| `Video Length` | Human-readable duration (e.g. `15:33`, `1:05:30`) |
| `View Count` | Total views |
| `Like Count` | Total likes (may be hidden by YouTube for some videos) |
| `Comment Count` | Total comments |
| `Full Video Description` | Full video description text |
| `Tags/Keywords` | Comma-separated video tags |
| `All websites links and URLs listed in the description or other video meta data (comma-separated)` | URLs extracted from description and tags |

## Output format notes

### Excel (`.xlsx`)

Best choice for viewing and editing in Excel. Descriptions, tags, and URLs are preserved with original line breaks.

### CSV (`.csv`)

CSV output is written in an Excel-friendly format:

- **Tab-delimited** (even if your input CSV was comma-delimited)
- **All fields quoted**
- **Embedded newlines replaced with spaces** in text fields

This avoids the column-splitting problems that occur when descriptions contain commas or line breaks.

## Example workflow

```bash
# First-time setup
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# Edit .env with your API key

# Enrich the playlist (Excel)
python enrich_playlist.py

# Or start from CSV
python enrich_playlist.py -i "AL-ML Playlist.csv"

# Write Excel output from CSV input
python enrich_playlist.py -i "AL-ML Playlist.csv" -o "AL-ML Playlist_Enriched.xlsx"

# Later: add new videos and enrich only the new rows
python enrich_playlist.py -i "AL-ML Playlist_Enriched.xlsx"

# Refresh all metadata (e.g. updated view counts)
python enrich_playlist.py -i "AL-ML Playlist_Enriched.xlsx" --force
```

## API quota

The YouTube Data API has a default daily quota of **10,000 units**. A `videos.list` call costs **1 unit** per request and can fetch up to 50 videos per call.

For a playlist of ~150 videos with ~75 unique IDs, expect roughly **2 API calls** — well within the free daily limit.

If you hit quota limits, the script will automatically retry with exponential backoff. If retries are exhausted, wait until your quota resets (midnight Pacific Time) or request a quota increase in Google Cloud Console.

## Troubleshooting

### `Missing API key`

Ensure `.env` exists in the project root and contains:

```env
YOUTUBE_API_KEY=your-key-here
```

### `Input file not found`

Check the file path passed to `--input`, or confirm `AL-ML Playlist.xlsx` exists in the project directory.

### `Please install required packages`

Activate the virtual environment and install dependencies:

```bash
source .venv/bin/activate
pip install -r requirements.txt
```

### `Missing required column 'Video URL'`

Your input file must include a column named exactly `Video URL`. A two-column file with `Video Title` and `Video URL` is sufficient.

### `Unsupported input format` / `Unsupported output format`

Only `.xlsx` and `.csv` are supported. Check the file extension passed to `--input` or `--output`.

### Warnings about unparseable URLs

The script prints the spreadsheet row numbers for any `Video URL` values it cannot parse. Fix those URLs and re-run.

### Warnings about missing videos

Videos that are deleted, private, or unavailable will not be returned by the API. Those rows are left with empty enriched columns. The script lists the affected video IDs and row numbers.

### CSV looks malformed in Excel

Re-run the script to regenerate the enriched CSV, or write Excel output instead:

```bash
python enrich_playlist.py -i "AL-ML Playlist.csv" -o "AL-ML Playlist_Enriched.xlsx"
```

Older comma-delimited enriched CSV files with multiline descriptions may split across columns in Excel. The current script writes tab-delimited, quoted CSV output to prevent this.

### Empty like counts

YouTube sometimes hides like counts via the API. This is expected API behavior, not a script bug.

## Security

- Never commit `.env` or share your API key publicly
- Consider restricting your API key to YouTube Data API v3 in Google Cloud Console
- `.gitignore` excludes `.env`, `.venv/`, `.DS_Store`, and `*.xlsx` from version control
