import asyncio
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

    async def get_recent_netflix(self, media_type, limit=30, days=90):
        """Recent releases currently available on Netflix in France, not catalog additions."""
        if media_type not in ('movie', 'series'):
            return []
        endpoint_type = 'movie' if media_type == 'movie' else 'tv'
        providers = await self._get(f'/watch/providers/{endpoint_type}', {
            'watch_region': 'FR', 'language': 'en-US',
        })
        if providers is None:
            raise RuntimeError('TMDB Netflix providers unavailable')
        provider_ids = [str(provider['provider_id']) for provider in providers.get('results', [])
                        if provider.get('provider_name', '').casefold() == 'netflix'
                        and provider.get('provider_id') is not None]
        if not provider_ids:
            return []

        today = date.today()
        date_field = 'primary_release_date' if media_type == 'movie' else 'first_air_date'
        params = {
            'language': 'fr-FR',
            'watch_region': 'FR',
            'with_watch_providers': '|'.join(provider_ids),
            'with_watch_monetization_types': 'flatrate',
            'include_adult': 'false',
            'sort_by': f'{date_field}.desc',
            f'{date_field}.gte': (today - timedelta(days=days)).isoformat(),
            f'{date_field}.lte': today.isoformat(),
        }
        if media_type == 'movie':
            params['include_video'] = 'false'
        results = []
        seen = set()
        semaphore = asyncio.Semaphore(5)

        async def allowed_origin(item):
            countries = item.get('origin_country')
            if countries is None:
                async with semaphore:
                    details = await self.get_media_details(item['id'], media_type)
                if details is None:
                    raise RuntimeError('TMDB Netflix origin lookup unavailable')
                countries = details.get('origin_country')
                if not countries:
                    countries = [country.get('iso_3166_1')
                                 for country in details.get('production_countries', [])]
            return not {'IN', 'CN'}.intersection(countries)

        for page in range(1, 6):
            if len(results) >= limit:
                break
            data = await self._get(f'/discover/{endpoint_type}', {**params, 'page': page})
            if data is None:
                raise RuntimeError('TMDB Netflix discovery unavailable')
            candidates = []
            for item in data.get('results', []):
                if item.get('id') and item['id'] not in seen:
                    seen.add(item['id'])
                    candidates.append(item)
            allowed = await asyncio.gather(*(allowed_origin(item) for item in candidates))
            for item, keep in zip(candidates, allowed):
                if keep:
                    results.append(item)
            if page >= data.get('total_pages', 1):
                break
        return results[:limit]
