import asyncio
import json
import os
import sqlite3
from datetime import datetime, timezone


class TorrentCacheService:
    def __init__(self, db_path=None):
        self.db_path = db_path or os.getenv('TORRENT_CACHE_DB', '/app/data/frenchio.db')
        if self.db_path.startswith('/app/') and not os.path.exists('/app'):
            self.db_path = os.path.join('data', 'frenchio.db')
        os.makedirs(os.path.dirname(self.db_path) or '.', exist_ok=True)
        self._init_db()

    def _connect(self):
        conn = sqlite3.connect(self.db_path, timeout=30)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self):
        with self._connect() as conn:
            conn.executescript('''
                CREATE TABLE IF NOT EXISTS torrent_cache (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    media_type TEXT NOT NULL,
                    tmdb_id INTEGER,
                    imdb_id TEXT,
                    season INTEGER NOT NULL DEFAULT -1,
                    episode INTEGER NOT NULL DEFAULT -1,
                    info_hash TEXT NOT NULL,
                    name TEXT NOT NULL,
                    size INTEGER NOT NULL DEFAULT 0,
                    tracker_name TEXT,
                    source TEXT,
                    seeders INTEGER NOT NULL DEFAULT 0,
                    leechers INTEGER NOT NULL DEFAULT 0,
                    first_seen_at TEXT NOT NULL,
                    last_seen_at TEXT NOT NULL,
                    UNIQUE(media_type, tmdb_id, season, episode, info_hash)
                );
                CREATE INDEX IF NOT EXISTS idx_torrent_cache_media
                    ON torrent_cache(media_type, tmdb_id, season, episode);
                CREATE INDEX IF NOT EXISTS idx_torrent_cache_imdb
                    ON torrent_cache(imdb_id, season, episode);

                CREATE TABLE IF NOT EXISTS media_catalog (
                    media_type TEXT NOT NULL,
                    tmdb_id INTEGER NOT NULL,
                    imdb_id TEXT,
                    name TEXT NOT NULL,
                    poster_path TEXT,
                    release_info TEXT,
                    description TEXT,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY(media_type, tmdb_id)
                );
                CREATE INDEX IF NOT EXISTS idx_media_catalog_imdb
                    ON media_catalog(imdb_id);

                CREATE TABLE IF NOT EXISTS runtime_config (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    config_json TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
            ''')

    async def save_config(self, config):
        # Le job d'indexation n'a pas besoin des clés de débridage ni de qBittorrent.
        # On ne persiste que les secrets strictement nécessaires aux sources de recherche.
        allowed = {
            'tmdb_key', 'trackers', 'abn_username', 'abn_password',
            'c411_apikey', 'torr9_passkey', 'tr4ker_apikey',
        }
        indexer_config = {key: value for key, value in config.items() if key in allowed}
        payload = json.dumps(indexer_config, separators=(',', ':'))
        now = datetime.now(timezone.utc).isoformat()
        await asyncio.to_thread(self._save_config_sync, payload, now)

    def _save_config_sync(self, payload, now):
        with self._connect() as conn:
            conn.execute('''
                INSERT INTO runtime_config(id, config_json, updated_at)
                VALUES (1, ?, ?)
                ON CONFLICT(id) DO UPDATE SET config_json=excluded.config_json, updated_at=excluded.updated_at
            ''', (payload, now))

    async def load_config(self):
        return await asyncio.to_thread(self._load_config_sync)

    def _load_config_sync(self):
        with self._connect() as conn:
            row = conn.execute('SELECT config_json FROM runtime_config WHERE id = 1').fetchone()
        return json.loads(row['config_json']) if row else None

    async def upsert_many(self, media_type, tmdb_id, imdb_id, season, episode, torrents):
        if not torrents:
            return 0
        return await asyncio.to_thread(
            self._upsert_many_sync, media_type, tmdb_id, imdb_id, season, episode, torrents
        )

    def _upsert_many_sync(self, media_type, tmdb_id, imdb_id, season, episode, torrents):
        now = datetime.now(timezone.utc).isoformat()
        season_key = -1 if season is None else int(season)
        episode_key = -1 if episode is None else int(episode)
        rows = []
        for torrent in torrents:
            info_hash = (torrent.get('info_hash') or '').strip().lower()
            name = (torrent.get('name') or '').strip()
            if not info_hash or not name:
                continue
            rows.append((
                media_type, tmdb_id, imdb_id, season_key, episode_key, info_hash, name,
                int(torrent.get('size') or 0), torrent.get('tracker_name'), torrent.get('source'),
                int(torrent.get('seeders') or 0), int(torrent.get('leechers') or 0), now, now,
            ))
        if not rows:
            return 0
        with self._connect() as conn:
            conn.executemany('''
                INSERT INTO torrent_cache(
                    media_type, tmdb_id, imdb_id, season, episode, info_hash, name, size,
                    tracker_name, source, seeders, leechers, first_seen_at, last_seen_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(media_type, tmdb_id, season, episode, info_hash) DO UPDATE SET
                    name=excluded.name,
                    size=excluded.size,
                    tracker_name=excluded.tracker_name,
                    source=excluded.source,
                    seeders=excluded.seeders,
                    leechers=excluded.leechers,
                    last_seen_at=excluded.last_seen_at
            ''', rows)
        return len(rows)

    async def get(self, media_type, tmdb_id=None, imdb_id=None, season=None, episode=None):
        return await asyncio.to_thread(self._get_sync, media_type, tmdb_id, imdb_id, season, episode)

    def _get_sync(self, media_type, tmdb_id, imdb_id, season, episode):
        clauses = ['media_type = ?']
        params = [media_type]
        if tmdb_id:
            clauses.append('tmdb_id = ?')
            params.append(tmdb_id)
        elif imdb_id:
            clauses.append('imdb_id = ?')
            params.append(imdb_id)
        else:
            return []
        clauses.append('season = ?')
        params.append(-1 if season is None else int(season))
        clauses.append('episode = ?')
        params.append(-1 if episode is None else int(episode))

        query = f"SELECT * FROM torrent_cache WHERE {' AND '.join(clauses)} ORDER BY seeders DESC, last_seen_at DESC"
        with self._connect() as conn:
            rows = conn.execute(query, params).fetchall()
        return [dict(row) for row in rows]

    async def upsert_media(
        self, media_type, tmdb_id, imdb_id, name,
        poster_path=None, release_info=None, description=None,
    ):
        if not tmdb_id or not name:
            return
        await asyncio.to_thread(
            self._upsert_media_sync,
            media_type, tmdb_id, imdb_id, name, poster_path, release_info, description,
        )

    def _upsert_media_sync(
        self, media_type, tmdb_id, imdb_id, name,
        poster_path, release_info, description,
    ):
        now = datetime.now(timezone.utc).isoformat()
        with self._connect() as conn:
            conn.execute('''
                INSERT INTO media_catalog(
                    media_type, tmdb_id, imdb_id, name, poster_path,
                    release_info, description, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(media_type, tmdb_id) DO UPDATE SET
                    imdb_id=COALESCE(excluded.imdb_id, media_catalog.imdb_id),
                    name=excluded.name,
                    poster_path=COALESCE(excluded.poster_path, media_catalog.poster_path),
                    release_info=COALESCE(excluded.release_info, media_catalog.release_info),
                    description=COALESCE(excluded.description, media_catalog.description),
                    updated_at=excluded.updated_at
            ''', (
                media_type, tmdb_id, imdb_id, name, poster_path,
                release_info, description, now,
            ))

    async def get_recent_french_catalog(self, media_type, limit=30):
        return await asyncio.to_thread(self._get_recent_french_catalog_sync, media_type, limit)

    def _get_recent_french_catalog_sync(self, media_type, limit):
        # Classe les médias selon la première découverte d'un nouveau hash FR/MULTi.
        french_match = '''
            UPPER(tc.name) LIKE '%FRENCH%' OR
            UPPER(tc.name) LIKE '%TRUEFRENCH%' OR
            UPPER(tc.name) LIKE '%MULTI%' OR
            UPPER(tc.name) LIKE '%VFF%' OR
            UPPER(tc.name) LIKE '%VFQ%' OR
            UPPER(tc.name) LIKE '%VFI%' OR
            UPPER(tc.name) LIKE '%VF2%'
        '''
        query = f'''
            SELECT
                mc.media_type, mc.tmdb_id, mc.imdb_id, mc.name, mc.poster_path,
                mc.release_info, mc.description, MAX(tc.first_seen_at) AS discovered_at
            FROM media_catalog mc
            JOIN torrent_cache tc
              ON tc.media_type = mc.media_type AND tc.tmdb_id = mc.tmdb_id
            WHERE mc.media_type = ?
              AND mc.imdb_id IS NOT NULL
              AND mc.imdb_id != ''
              AND ({french_match})
            GROUP BY
                mc.media_type, mc.tmdb_id, mc.imdb_id, mc.name,
                mc.poster_path, mc.release_info, mc.description
            ORDER BY discovered_at DESC
            LIMIT ?
        '''
        with self._connect() as conn:
            rows = conn.execute(query, (media_type, max(1, int(limit)))).fetchall()
        return [dict(row) for row in rows]
