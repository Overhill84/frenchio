import aiohttp
import logging
from datetime import date, timedelta


class TMDBService:
    def __init__(self, api_key):
        self.api_key = api_key
        self.base_url = "https://api.themoviedb.org/3"

    async def _get(self, path, params=None):
        params = dict(params or {})
        params['api_key'] = self.api_key
        async with aiohttp.ClientSession(trust_env=True) as session:
            try:
                async with session.get(f"{self.base_url}{path}", params=params, timeout=20) as response:
                    if response.status == 200:
                        return await response.json()
                    logging.warning("TMDB %s returned HTTP %s", path, response.status)
            except Exception as e:
                logging.error("TMDB request error on %s: %s", path, e)
        return None

    async def get_tmdb_id(self, imdb_id, media_type):
        data = await self._get(f"/find/{imdb_id}", {"external_source": "imdb_id"})
        if not data:
            return None
        results = data.get("movie_results", []) if media_type == "movie" else data.get("tv_results", [])
        return results[0]["id"] if results else None

    async def get_imdb_id(self, tmdb_id, media_type):
        endpoint_type = 'movie' if media_type == 'movie' else 'tv'
        data = await self._get(f"/{endpoint_type}/{tmdb_id}/external_ids")
        return data.get('imdb_id') if data else None

    async def get_media_details(self, tmdb_id, media_type, language='fr-FR'):
        endpoint_type = 'movie' if media_type == 'movie' else 'tv'
        return await self._get(f"/{endpoint_type}/{tmdb_id}", {"language": language})

    async def get_recent_movies(self, limit=20, days=90):
        today = date.today()
        start = today - timedelta(days=days)
        results = []
        page = 1
        while len(results) < limit and page <= 5:
            data = await self._get('/discover/movie', {
                'language': 'fr-FR',
                'region': 'FR',
                'sort_by': 'popularity.desc',
                'include_adult': 'false',
                'include_video': 'false',
                'primary_release_date.gte': start.isoformat(),
                'primary_release_date.lte': today.isoformat(),
                'page': page,
            })
            if not data:
                break
            results.extend(data.get('results', []))
            if page >= data.get('total_pages', 1):
                break
            page += 1
        return results[:limit]

    async def get_recent_series(self, limit=20):
        results = []
        page = 1
        while len(results) < limit and page <= 5:
            data = await self._get('/tv/on_the_air', {
                'language': 'fr-FR',
                'page': page,
            })
            if not data:
                break
            results.extend(data.get('results', []))
            if page >= data.get('total_pages', 1):
                break
            page += 1
        return results[:limit]
