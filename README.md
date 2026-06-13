# YouTube Playlist Enricher

A Python toolkit that enriches a playlist of YouTube videos in three stages:

1. **Metadata** — channel info, statistics, descriptions, tags (`enrich_playlist.py`)
2. **Transcripts** — full video captions (`fetch_transcripts.py`)
3. **URL extraction** — websites mentioned in transcripts (`extract_transcript_urls.py`)

It reads video URLs from an Excel (`.xlsx`) or CSV (`.csv`) file and writes enriched output in the same format.

## What it does

```mermaid
flowchart LR
    input[Playlist file] --> enrich[enrich_playlist.py]
    enrich --> enriched[Enriched file]
    enriched --> transcripts[fetch_transcripts.py]
    transcripts --> withTranscripts[File + transcripts]
    withTranscripts --> urls[extract_transcript_urls.py]
    urls --> final[File + transcript URLs]
```

### Stage 1: Metadata enrichment

`enrich_playlist.py` will:

1. Extract video IDs from each URL
2. Fetch metadata from the YouTube Data API (in batches of 50)
3. Add enriched columns to your playlist
4. Save the result as a new file (by default, `<input>_Enriched` with the same extension)

### Stage 2: Transcript fetching

`fetch_transcripts.py` will:

1. Fetch captions for each video via `youtube-transcript-api` (no API key required)
2. Add the full transcript text and status columns
3. Save back to the input file by default (or a custom output path)

### Stage 3: Transcript URL extraction

`extract_transcript_urls.py` will:

1. Scan each transcript for `http://`, `https://`, and `www.` URLs
2. Add a transcript URL column and an optional combined URL column
3. Save back to the input file by default (offline, no API calls)

All scripts deduplicate video IDs where applicable, support incremental re-runs, and skip already-populated rows unless `--force` is used.

## Prerequisites

- Python 3.10+ (tested with 3.14)
- A Google Cloud project with the **YouTube Data API v3** enabled (stage 1 only)
- A YouTube Data API key (stage 1 only)

## Project files

| File | Purpose |
|------|---------|
| `enrich_playlist.py` | Stage 1 — metadata enrichment via YouTube Data API |
| `fetch_transcripts.py` | Stage 2 — transcript fetching via youtube-transcript-api |
| `extract_transcript_urls.py` | Stage 3 — URL extraction from transcripts |
| `playlist_utils.py` | Shared I/O, video ID parsing, and URL extraction helpers |
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

### 4. Get a YouTube Data API key (stage 1 only)

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

> **Note:** `.env` is listed in `.gitignore` and should never be committed. Only `.env.example` is tracked in git. Stages 2 and 3 do not use this key.

## Input file format

The scripts accept **Excel (`.xlsx`)** or **CSV (`.csv`)** files. The only required column is **`Video URL`**.

A minimal two-column file works:

| Column | Required | Description |
|--------|----------|-------------|
| `Video Title` | No | Existing title (preserved as-is) |
| `Video URL` | **Yes** | YouTube link for each video |

Any other columns in your input file are preserved unchanged.

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

### Full 3-step pipeline

```bash
# Step 1: metadata (requires YOUTUBE_API_KEY in .env)
python enrich_playlist.py -i "AL-ML Playlist.xlsx"

# Step 2: transcripts (no API key required)
python fetch_transcripts.py -i "AL-ML Playlist_Enriched.xlsx"

# Step 3: extract URLs from transcripts (offline)
python extract_transcript_urls.py -i "AL-ML Playlist_Enriched_Transcripts.xlsx"
```

Stages 2 and 3 write new files by default (`<input>_Transcripts` and `<input>_TranscriptURLs`). Use `-o` to specify a custom output path.

### Stage 1: Metadata enrichment

```bash
python enrich_playlist.py
python enrich_playlist.py -i "AL-ML Playlist.xlsx" -o "AL-ML Playlist_Enriched.xlsx"
python enrich_playlist.py -i "AL-ML Playlist.csv" -o "AL-ML Playlist_Enriched.xlsx"
python enrich_playlist.py --force
```

### Stage 2: Transcript fetching

```bash
python fetch_transcripts.py -i "AL-ML Playlist_Enriched.xlsx"
python fetch_transcripts.py -i "AL-ML Playlist_Enriched.xlsx" --force
python fetch_transcripts.py -i "AL-ML Playlist_Enriched.xlsx" --language en,es --delay 1.0
```

### Stage 3: Transcript URL extraction

```bash
python extract_transcript_urls.py -i "AL-ML Playlist_Enriched.xlsx"
python extract_transcript_urls.py -i "AL-ML Playlist_Enriched.xlsx" --exclude-youtube
python extract_transcript_urls.py -i "AL-ML Playlist_Enriched.xlsx" --force
```

### Incremental updates

Each stage skips rows that are already populated:

```bash
# Add new videos to the enriched file, then:
python enrich_playlist.py -i "AL-ML Playlist_Enriched.xlsx"
python fetch_transcripts.py -i "AL-ML Playlist_Enriched.xlsx"
python extract_transcript_urls.py -i "AL-ML Playlist_Enriched_Transcripts.xlsx"
```

Use `--force` on any stage to refresh all rows.

## CLI reference

### enrich_playlist.py

| Flag | Description |
|------|-------------|
| `--input`, `-i` | Input playlist file (default: `AL-ML Playlist.xlsx`) |
| `--output`, `-o` | Output file (default: `<input>_Enriched` with same extension) |
| `--force`, `-f` | Re-fetch metadata for all rows |

### fetch_transcripts.py

| Flag | Description |
|------|-------------|
| `--input`, `-i` | Input playlist file (default: `AL-ML Playlist_Enriched.xlsx`) |
| `--output`, `-o` | Output file (default: `<input>_Transcripts` with same extension) |
| `--force`, `-f` | Re-fetch transcripts for all rows |
| `--language`, `-l` | Preferred languages, comma-separated (default: `en,en-US,en-GB`) |
| `--delay` | Seconds between requests (default: `2.5`) |
| `--max-videos` | Limit how many videos to fetch this run (batching) |
| `--continue-on-ip-block` | Keep going after IP rate-limit errors (default: stop early) |

### extract_transcript_urls.py

| Flag | Description |
|------|-------------|
| `--input`, `-i` | Input file with transcripts (default: `AL-ML Playlist_Enriched_Transcripts.xlsx`) |
| `--output`, `-o` | Output file (default: `<input>_TranscriptURLs` with same extension) |
| `--force`, `-f` | Re-extract URLs for all rows |
| `--exclude-youtube` | Omit youtube.com / youtu.be links |
| `--no-combined-column` | Skip the combined `All URLs (description + transcript)` column |

## Output columns

### Stage 1 — metadata

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
| `All websites links and URLs listed in the description or other video meta data (comma-separated)` | URLs from description and tags |

### Stage 2 — transcripts

| Column | Example values |
|--------|----------------|
| `Full Video Transcript` | Plain text, all caption segments joined |
| `Transcript Language` | `en`, `en (auto-generated)` |
| `Transcript Status` | `ok`, `no_captions`, `unavailable`, `ip_blocked`, `error` |

### Stage 3 — transcript URLs

| Column | Content |
|--------|---------|
| `URLs from Transcript (comma-separated)` | URLs found in the transcript |
| `All URLs (description + transcript)` | Merged, deduplicated URLs from description + transcript |

## Output format notes

### Excel (`.xlsx`)

Best choice for viewing and editing in Excel. Descriptions, transcripts, and URLs preserve original line breaks.

### CSV (`.csv`)

CSV output is written in an Excel-friendly format:

- **Tab-delimited** (even if your input CSV was comma-delimited)
- **All fields quoted**
- **Embedded newlines replaced with spaces** in text fields

Use `.xlsx` output when working with long transcripts.

## Transcript limitations

- Transcripts are fetched via the unofficial `youtube-transcript-api` library, not the official YouTube Data API
- Only videos with captions (manual or auto-generated) return transcript text
- Videos without captions get `Transcript Status = no_captions` and a blank transcript
- Making too many requests too quickly may trigger IP-based rate limiting; use `--delay` to slow down
- Private, age-restricted, or unavailable videos get `Transcript Status = unavailable`

## API quota (stage 1 only)

The YouTube Data API has a default daily quota of **10,000 units**. A `videos.list` call costs **1 unit** per request and can fetch up to 50 videos per call.

For a playlist of ~150 videos with ~75 unique IDs, expect roughly **2 API calls** — well within the free daily limit.

## Example workflow

```bash
# First-time setup
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# Edit .env with your API key

# Run the full pipeline
python enrich_playlist.py -i "AL-ML Playlist.xlsx"
python fetch_transcripts.py -i "AL-ML Playlist_Enriched.xlsx"
python extract_transcript_urls.py -i "AL-ML Playlist_Enriched_Transcripts.xlsx"

# Later: add new videos and update incrementally
python enrich_playlist.py -i "AL-ML Playlist_Enriched.xlsx"
python fetch_transcripts.py -i "AL-ML Playlist_Enriched.xlsx"
python extract_transcript_urls.py -i "AL-ML Playlist_Enriched_Transcripts.xlsx"

# Refresh all metadata and transcripts
python enrich_playlist.py -i "AL-ML Playlist_Enriched.xlsx" --force
python fetch_transcripts.py -i "AL-ML Playlist_Enriched.xlsx" --force
python extract_transcript_urls.py -i "AL-ML Playlist_Enriched_Transcripts.xlsx" --force
```

## Troubleshooting

### `Missing API key`

Only stage 1 requires an API key. Ensure `.env` exists and contains:

```env
YOUTUBE_API_KEY=your-key-here
```

### `Input file not found`

Check the file path passed to `--input`.

### `Please install required packages`

```bash
source .venv/bin/activate
pip install -r requirements.txt
```

### `Missing required column 'Video URL'`

Your input file must include a column named exactly `Video URL`.

### `Missing required column 'Full Video Transcript'`

Run `fetch_transcripts.py` before `extract_transcript_urls.py`.

### Transcript status `no_captions`

The video has no available captions. The transcript and URL columns will be left blank.

### Transcript fetching is slow or fails with rate-limit errors

YouTube blocked your IP after too many requests. The script now:

- Saves progress after **each video** to `<input>_Transcripts.xlsx`
- Stops early after consecutive `ip_blocked` errors (use `--continue-on-ip-block` to override)
- Resumes automatically from the output file on the next run

**What to do:**

1. Stop the current run (Ctrl+C) if it is still going
2. Wait **30–60 minutes**
3. Re-run the same command — it will skip videos already fetched:

```bash
python fetch_transcripts.py -i "AL-ML Playlist_Enriched.xlsx" --delay 3
```

For large playlists, fetch in batches:

```bash
python fetch_transcripts.py -i "AL-ML Playlist_Enriched.xlsx" --max-videos 30 --delay 3
```

### CSV looks malformed in Excel

Re-run with `.xlsx` output, or regenerate the CSV with the current scripts (tab-delimited, quoted output).

### Empty like counts

YouTube sometimes hides like counts via the API. This is expected API behavior, not a script bug.

## Security

- Never commit `.env` or share your API key publicly
- Consider restricting your API key to YouTube Data API v3 in Google Cloud Console
- `.gitignore` excludes `.env`, `.venv/`, `.DS_Store`, and `*.xlsx` from version control
