import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

DEFAULT_DB_PATH = "data/playlist.db"

TRANSCRIPT_SKIP_STATUSES = ("no_captions", "unavailable")
METADATA_COLUMNS = [
    "channel_name",
    "channel_id",
    "publish_date",
    "video_length",
    "view_count",
    "like_count",
    "comment_count",
    "description",
    "tags",
    "description_urls",
]
TRANSCRIPT_COLUMNS = [
    "transcript_text",
    "transcript_language",
    "transcript_status",
]
URL_COLUMNS = ["transcript_urls", "all_urls"]

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS playlists (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    source_file TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS videos (
    video_id TEXT PRIMARY KEY,
    video_url TEXT NOT NULL,
    video_title TEXT,
    channel_name TEXT,
    channel_id TEXT,
    publish_date TEXT,
    video_length TEXT,
    view_count TEXT,
    like_count TEXT,
    comment_count TEXT,
    description TEXT,
    tags TEXT,
    description_urls TEXT,
    transcript_text TEXT,
    transcript_language TEXT,
    transcript_status TEXT,
    transcript_urls TEXT,
    all_urls TEXT,
    metadata_fetched_at TEXT,
    transcript_fetched_at TEXT,
    urls_extracted_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS playlist_videos (
    playlist_id INTEGER NOT NULL,
    video_id TEXT NOT NULL,
    position INTEGER NOT NULL,
    PRIMARY KEY (playlist_id, video_id),
    FOREIGN KEY (playlist_id) REFERENCES playlists(id),
    FOREIGN KEY (video_id) REFERENCES videos(video_id)
);
"""


def utc_now():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def resolve_db_path(path=None):
    return path or os.environ.get("PLAYLIST_DB", DEFAULT_DB_PATH)


class PlaylistDB:
    def __init__(self, path=None):
        self.path = resolve_db_path(path)
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.path)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        self._init_schema()

    def close(self):
        self.conn.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self.close()

    def _init_schema(self):
        self.conn.executescript(SCHEMA_SQL)
        self.conn.commit()

    def get_playlist_by_name(self, name):
        row = self.conn.execute(
            "SELECT * FROM playlists WHERE name = ?",
            (name,),
        ).fetchone()
        return dict(row) if row else None

    def get_or_create_playlist(self, name, source_file=None):
        existing = self.get_playlist_by_name(name)
        if existing:
            self.conn.execute(
                "UPDATE playlists SET source_file = ?, updated_at = ? WHERE id = ?",
                (source_file or existing["source_file"], utc_now(), existing["id"]),
            )
            self.conn.commit()
            return existing["id"]

        now = utc_now()
        cursor = self.conn.execute(
            "INSERT INTO playlists (name, source_file, created_at, updated_at) VALUES (?, ?, ?, ?)",
            (name, source_file, now, now),
        )
        self.conn.commit()
        return cursor.lastrowid

    def video_exists(self, video_id):
        row = self.conn.execute(
            "SELECT 1 FROM videos WHERE video_id = ?",
            (video_id,),
        ).fetchone()
        return row is not None

    def get_video(self, video_id):
        row = self.conn.execute(
            "SELECT * FROM videos WHERE video_id = ?",
            (video_id,),
        ).fetchone()
        return dict(row) if row else None

    def upsert_video_identity(self, video_id, video_url, video_title=None):
        now = utc_now()
        existing = self.get_video(video_id)
        if existing:
            self.conn.execute(
                """
                UPDATE videos
                SET video_url = ?, video_title = COALESCE(?, video_title), updated_at = ?
                WHERE video_id = ?
                """,
                (video_url, video_title, now, video_id),
            )
            return False

        self.conn.execute(
            """
            INSERT INTO videos (
                video_id, video_url, video_title, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (video_id, video_url, video_title, now, now),
        )
        return True

    def link_video_to_playlist(self, playlist_id, video_id, position):
        self.conn.execute(
            """
            INSERT INTO playlist_videos (playlist_id, video_id, position)
            VALUES (?, ?, ?)
            ON CONFLICT(playlist_id, video_id) DO UPDATE SET position = excluded.position
            """,
            (playlist_id, video_id, position),
        )

    def _playlist_filter_clause(self, playlist_name):
        if not playlist_name:
            return "", []
        return (
            """
            AND v.video_id IN (
                SELECT pv.video_id
                FROM playlist_videos pv
                JOIN playlists p ON p.id = pv.playlist_id
                WHERE p.name = ?
            )
            """,
            [playlist_name],
        )

    def get_videos_needing_metadata(self, playlist_name=None, force=False):
        clause, params = self._playlist_filter_clause(playlist_name)
        if force:
            query = f"""
                SELECT v.*
                FROM videos v
                WHERE v.metadata_fetched_at IS NOT NULL
                  AND COALESCE(v.channel_name, '') != ''
                {clause}
                ORDER BY v.video_id
            """
        else:
            query = f"""
                SELECT v.*
                FROM videos v
                WHERE v.metadata_fetched_at IS NULL
                   OR COALESCE(v.channel_name, '') = ''
                {clause}
                ORDER BY v.video_id
            """
        rows = self.conn.execute(query, params).fetchall()
        return [dict(row) for row in rows]

    def get_videos_needing_transcripts(self, playlist_name=None, force=False):
        clause, params = self._playlist_filter_clause(playlist_name)
        if force:
            query = f"""
                SELECT v.*
                FROM videos v
                WHERE v.transcript_status = 'ok'
                  AND COALESCE(v.transcript_text, '') != ''
                {clause}
                ORDER BY v.video_id
            """
        else:
            query = f"""
                SELECT v.*
                FROM videos v
                WHERE COALESCE(v.transcript_status, '') NOT IN ('no_captions', 'unavailable')
                  AND NOT (
                      v.transcript_status = 'ok'
                      AND COALESCE(v.transcript_text, '') != ''
                  )
                {clause}
                ORDER BY v.video_id
            """
        rows = self.conn.execute(query, params).fetchall()
        return [dict(row) for row in rows]

    def get_videos_needing_url_extraction(self, playlist_name=None, force=False):
        clause, params = self._playlist_filter_clause(playlist_name)
        if force:
            query = f"""
                SELECT v.*
                FROM videos v
                WHERE v.transcript_status = 'ok'
                  AND COALESCE(v.transcript_text, '') != ''
                  AND v.urls_extracted_at IS NOT NULL
                {clause}
                ORDER BY v.video_id
            """
        else:
            query = f"""
                SELECT v.*
                FROM videos v
                WHERE v.transcript_status = 'ok'
                  AND COALESCE(v.transcript_text, '') != ''
                  AND (v.transcript_urls IS NULL OR v.transcript_urls = '')
                {clause}
                ORDER BY v.video_id
            """
        rows = self.conn.execute(query, params).fetchall()
        return [dict(row) for row in rows]

    def upsert_video_metadata(self, video_id, fields):
        now = utc_now()
        mapping = {
            "channel_name": fields.get("Channel Name", fields.get("channel_name", "")),
            "channel_id": fields.get("Channel ID", fields.get("channel_id", "")),
            "publish_date": fields.get("Publish Date", fields.get("publish_date", "")),
            "video_length": fields.get("Video Length", fields.get("video_length", "")),
            "view_count": fields.get("View Count", fields.get("view_count", "")),
            "like_count": fields.get("Like Count", fields.get("like_count", "")),
            "comment_count": fields.get("Comment Count", fields.get("comment_count", "")),
            "description": fields.get("Full Video Description", fields.get("description", "")),
            "tags": fields.get("Tags/Keywords", fields.get("tags", "")),
            "description_urls": fields.get(
                "All websites links and URLs listed in the description or other video meta data (comma-separated)",
                fields.get("description_urls", ""),
            ),
        }
        self.conn.execute(
            """
            UPDATE videos SET
                channel_name = ?,
                channel_id = ?,
                publish_date = ?,
                video_length = ?,
                view_count = ?,
                like_count = ?,
                comment_count = ?,
                description = ?,
                tags = ?,
                description_urls = ?,
                metadata_fetched_at = ?,
                updated_at = ?
            WHERE video_id = ?
            """,
            (
                mapping["channel_name"],
                mapping["channel_id"],
                mapping["publish_date"],
                mapping["video_length"],
                mapping["view_count"],
                mapping["like_count"],
                mapping["comment_count"],
                mapping["description"],
                mapping["tags"],
                mapping["description_urls"],
                now,
                now,
                video_id,
            ),
        )
        self.conn.commit()

    def upsert_video_transcript(self, video_id, fields):
        now = utc_now()
        transcript_text = fields.get("Full Video Transcript", fields.get("transcript_text", ""))
        transcript_language = fields.get("Transcript Language", fields.get("transcript_language", ""))
        transcript_status = fields.get("Transcript Status", fields.get("transcript_status", ""))
        self.conn.execute(
            """
            UPDATE videos SET
                transcript_text = ?,
                transcript_language = ?,
                transcript_status = ?,
                transcript_fetched_at = ?,
                updated_at = ?
            WHERE video_id = ?
            """,
            (transcript_text, transcript_language, transcript_status, now, now, video_id),
        )
        self.conn.commit()

    def upsert_video_urls(self, video_id, transcript_urls, all_urls):
        now = utc_now()
        self.conn.execute(
            """
            UPDATE videos SET
                transcript_urls = ?,
                all_urls = ?,
                urls_extracted_at = ?,
                updated_at = ?
            WHERE video_id = ?
            """,
            (transcript_urls, all_urls, now, now, video_id),
        )
        self.conn.commit()

    def seed_video_fields_if_empty(self, video_id, fields):
        video = self.get_video(video_id)
        if not video:
            return

        updates = []
        values = []

        field_map = {
            "video_title": ("Video Title", "video_title"),
            "channel_name": ("Channel Name", "channel_name"),
            "channel_id": ("Channel ID", "channel_id"),
            "publish_date": ("Publish Date", "publish_date"),
            "video_length": ("Video Length", "video_length"),
            "view_count": ("View Count", "view_count"),
            "like_count": ("Like Count", "like_count"),
            "comment_count": ("Comment Count", "comment_count"),
            "description": ("Full Video Description", "description"),
            "tags": ("Tags/Keywords", "tags"),
            "description_urls": (
                "All websites links and URLs listed in the description or other video meta data (comma-separated)",
                "description_urls",
            ),
            "transcript_text": ("Full Video Transcript", "transcript_text"),
            "transcript_language": ("Transcript Language", "transcript_language"),
            "transcript_status": ("Transcript Status", "transcript_status"),
            "transcript_urls": ("URLs from Transcript (comma-separated)", "transcript_urls"),
            "all_urls": ("All URLs (description + transcript)", "all_urls"),
        }

        for db_col, (sheet_col, _) in field_map.items():
            current = video.get(db_col)
            if current not in (None, ""):
                continue
            new_value = fields.get(sheet_col, fields.get(db_col))
            if new_value in (None, ""):
                continue
            updates.append(f"{db_col} = ?")
            values.append(new_value)

        if video.get("metadata_fetched_at") is None and fields.get("Channel Name"):
            updates.append("metadata_fetched_at = ?")
            values.append(utc_now())

        if video.get("transcript_fetched_at") is None and fields.get("Full Video Transcript"):
            updates.append("transcript_fetched_at = ?")
            values.append(utc_now())

        if video.get("urls_extracted_at") is None and fields.get("URLs from Transcript (comma-separated)"):
            updates.append("urls_extracted_at = ?")
            values.append(utc_now())

        if not updates:
            return

        values.extend([utc_now(), video_id])
        self.conn.execute(
            f"UPDATE videos SET {', '.join(updates)}, updated_at = ? WHERE video_id = ?",
            values,
        )
        self.conn.commit()

    def get_playlist_videos(self, playlist_name):
        rows = self.conn.execute(
            """
            SELECT v.*, pv.position
            FROM playlist_videos pv
            JOIN playlists p ON p.id = pv.playlist_id
            JOIN videos v ON v.video_id = pv.video_id
            WHERE p.name = ?
            ORDER BY pv.position
            """,
            (playlist_name,),
        ).fetchall()
        return [dict(row) for row in rows]

    def get_pipeline_summary(self, playlist_name=None):
        clause, params = self._playlist_filter_clause(playlist_name)
        rows = self.conn.execute(
            f"""
            SELECT
                COUNT(*) AS total,
                SUM(CASE WHEN COALESCE(v.channel_name, '') != '' THEN 1 ELSE 0 END) AS metadata_done,
                SUM(CASE
                    WHEN v.transcript_status = 'ok' AND COALESCE(v.transcript_text, '') != '' THEN 1
                    ELSE 0
                END) AS transcript_ok,
                SUM(CASE WHEN v.transcript_status = 'no_captions' THEN 1 ELSE 0 END) AS no_captions,
                SUM(CASE WHEN v.transcript_status = 'unavailable' THEN 1 ELSE 0 END) AS unavailable,
                SUM(CASE WHEN v.transcript_status = 'ip_blocked' THEN 1 ELSE 0 END) AS ip_blocked,
                SUM(CASE WHEN v.transcript_status = 'error' THEN 1 ELSE 0 END) AS errors,
                SUM(CASE
                    WHEN v.transcript_status = 'ok'
                     AND COALESCE(v.transcript_text, '') != ''
                     AND COALESCE(v.transcript_urls, '') != '' THEN 1
                    ELSE 0
                END) AS urls_done,
                SUM(CASE
                    WHEN COALESCE(v.transcript_status, '') NOT IN ('no_captions', 'unavailable')
                     AND NOT (
                         v.transcript_status = 'ok'
                         AND COALESCE(v.transcript_text, '') != ''
                     ) THEN 1 ELSE 0
                END) AS transcript_pending
            FROM videos v
            WHERE 1 = 1
            {clause}
            """,
            params,
        ).fetchone()
        return dict(rows) if rows else {}
