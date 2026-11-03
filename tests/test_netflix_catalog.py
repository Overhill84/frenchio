import base64
import json
import os
import unittest
from datetime import date, timedelta
from unittest.mock import AsyncMock, patch

from aiohttp.test_utils import TestClient, TestServer
from services.tmdb import TMDBService
from services.netflix_catalog import NetflixCatalogService


class NetflixCatalogTest(unittest.IsolatedAsyncioTestCase):
    async def test_discovery_filters_region_provider_and_release_window(self):
        for media_type, endpoint, date_field in [
            ('movie', 'movie', 'primary_release_date'), ('series', 'tv', 'first_air_date')
        ]:
            with self.subTest(media_type=media_type):
                tmdb = TMDBService('test')
                tmdb._get = AsyncMock(side_effect=[
                    {'results': [{'provider_id': 8, 'provider_name': 'Netflix'},
                                 {'provider_id': 9, 'provider_name': 'Other'}]},
                    {'results': [{'id': 1}], 'total_pages': 1},
                ])
                self.assertEqual(await tmdb.get_recent_netflix(media_type), [{'id': 1}])
                path, params = tmdb._get.call_args.args
                self.assertEqual(path, '/discover/' + endpoint)
                self.assertEqual(params['watch_region'], 'FR')
                self.assertEqual(params['with_watch_providers'], '8')
                self.assertEqual(params['with_watch_monetization_types'], 'flatrate')
                self.assertEqual(params['sort_by'], date_field + '.desc')
                self.assertEqual(params[date_field + '.lte'], date.today().isoformat())
                self.assertEqual(params[date_field + '.gte'], (date.today() - timedelta(days=90)).isoformat())

    async def test_discovery_paginates_and_deduplicates(self):
        tmdb = TMDBService('test')
        tmdb._get = AsyncMock(side_effect=[
            {'results': [{'provider_id': 8, 'provider_name': 'Netflix'}]},
            {'results': [{'id': 1}], 'total_pages': 2},
            {'results': [{'id': 1}, {'id': 2}], 'total_pages': 2},
        ])
        self.assertEqual(await tmdb.get_recent_netflix('movie', limit=2), [{'id': 1}, {'id': 2}])

    async def test_metadata_cache_is_scoped_by_credentials_and_type(self):
        with patch('services.netflix_catalog.TMDBService') as factory:
            tmdb = factory.return_value
            tmdb.get_recent_netflix = AsyncMock(return_value=[{'id': 1, 'title': 'Test', 'poster_path': '/test.jpg'}])
            tmdb.get_imdb_id = AsyncMock(return_value='tt1234567')
            service = NetflixCatalogService()
            result = await service.get_catalog('key', 'movie')
            self.assertEqual(result[0]['id'], 'tt1234567')
            self.assertEqual(result[0]['poster'], 'https://image.tmdb.org/t/p/w500/test.jpg')
            self.assertEqual(await service.get_catalog('key', 'movie'), result)
            self.assertEqual(tmdb.get_recent_netflix.await_count, 1)
            await service.get_catalog('other-key', 'movie')
            await service.get_catalog('key', 'series')
            self.assertEqual(tmdb.get_recent_netflix.await_count, 3)

    async def test_provider_failure_uses_stale_cache_and_retries(self):
        with patch('services.netflix_catalog.TMDBService') as factory:
            tmdb = factory.return_value
            tmdb.get_recent_netflix = AsyncMock(return_value=[{'id': 1}])
            tmdb.get_imdb_id = AsyncMock(return_value='tt1234567')
            service = NetflixCatalogService(ttl=0)
            expected = await service.get_catalog('key', 'movie')
            tmdb.get_recent_netflix.side_effect = RuntimeError('offline')
            with self.assertLogs(level='ERROR'):
                self.assertEqual(await service.get_catalog('key', 'movie'), expected)
                self.assertEqual(await service.get_catalog('key', 'movie'), expected)
            self.assertEqual(tmdb.get_recent_netflix.await_count, 3)

    async def test_http_manifest_and_catalog_routing(self):
        from main import get_app, NETFLIX_CATALOG_KEY
        with patch.dict(os.environ, {'INDEXER_ENABLED': 'false'}), patch('main.TorrentCacheService') as cache:
            cache.return_value.save_config = AsyncMock()
            cache.return_value.get_recent_french_catalog = AsyncMock(return_value=[])
            async with TestClient(TestServer(await get_app())) as client:
                config = base64.b64encode(json.dumps({'tmdb_key': 'test'}).encode()).decode()
                response = await client.get(f'/{config}/manifest.json')
                manifest = await response.json()
                catalogs = {(c['type'], c['id']) for c in manifest['catalogs']}
                self.assertEqual(len(catalogs), 4)
                self.assertIn(('movie', 'frenchio-netflix-movie'), catalogs)
                self.assertIn(('series', 'frenchio-netflix-series'), catalogs)
                service = client.server.app[NETFLIX_CATALOG_KEY]
                service.get_catalog = AsyncMock(return_value=[{'id': 'tt1234567', 'type': 'movie', 'name': 'Test'}])
                response = await client.get(f'/{config}/catalog/movie/frenchio-netflix-movie.json')
                self.assertEqual((await response.json())['metas'][0]['id'], 'tt1234567')
                service.get_catalog.assert_awaited_once_with('test', 'movie', limit=30)
                response = await client.get(f'/{config}/catalog/series/frenchio-netflix-movie.json')
                self.assertEqual(await response.json(), {'metas': []})
                response = await client.get(f'/{config}/catalog/movie/frenchio-new-fr-movie.json')
                self.assertEqual(await response.json(), {'metas': []})
                cache.return_value.get_recent_french_catalog.assert_awaited_once_with('movie', 30)
                response = await client.get('/manifest.json')
                self.assertEqual((await response.json())['catalogs'], [])
