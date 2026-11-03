import asyncio
import hashlib
import logging
from collections import OrderedDict
from time import monotonic

from services.tmdb import TMDBService


class NetflixCatalogService:
    """Small per-credential cache; never caches provider failures as empty catalogs."""

    def __init__(self, ttl=21600, max_entries=64):
        self.ttl = ttl
        self.max_entries = max_entries
        self._cache = OrderedDict()
        self._lock = asyncio.Lock()

    async def get_catalog(self, api_key, media_type, limit=30, days=90):
        if not api_key or media_type not in ('movie', 'series'):
            return []
        key = (hashlib.sha256(api_key.encode()).hexdigest(), media_type, limit, days)
        async with self._lock:
            cached = self._cache.get(key)
            if cached and monotonic() - cached[0] < self.ttl:
                self._cache.move_to_end(key)
                return cached[1]
            try:
                tmdb = TMDBService(api_key)
                items = await tmdb.get_recent_netflix(media_type, limit=limit, days=days)
                semaphore = asyncio.Semaphore(5)

                async def build_meta(item):
                    async with semaphore:
                        imdb_id = await tmdb.get_imdb_id(item['id'], media_type)
                    if not imdb_id:
                        return None
                    meta = {
                        'id': imdb_id,
                        'type': media_type,
                        'name': item.get('title') or item.get('name') or imdb_id,
                        'posterShape': 'poster',
                        'description': item.get('overview') or '',
                        'releaseInfo': (item.get('release_date') or item.get('first_air_date') or '')[:4],
                    }
                    poster = item.get('poster_path')
                    if poster:
                        meta['poster'] = f'https://image.tmdb.org/t/p/w500{poster}'
                    return meta

                metas = await asyncio.gather(*(build_meta(item) for item in items))
                metas = [meta for meta in metas if meta]
                # IMDb resolution may fail temporarily; retry instead of caching lost entries.
                if len(metas) == len(items):
                    self._cache[key] = (monotonic(), metas)
                    self._cache.move_to_end(key)
                    while len(self._cache) > self.max_entries:
                        self._cache.popitem(last=False)
                return metas
            except Exception:
                logging.exception('Unable to load Netflix catalog for %s', media_type)
                return cached[1] if cached else []
