import asyncio
import logging
import os

from services.abn import ABNService
from services.c411 import C411Service
from services.torr9 import Torr9Service
from services.tr4ker import Tr4kerService
from services.unit3d import Unit3DService
from services.ygg import YggService


class TorrentSearchService:
    async def search(self, config, media_type, tmdb_id, imdb_id, title, original_title='', year='', season=None, episode=None):
        tasks = []
        labels = []
        closables = []

        if config.get('trackers'):
            service = Unit3DService(config['trackers'])
            tasks.append(service.search_all(tmdb_id=tmdb_id, imdb_id=imdb_id, type=media_type, season=season, episode=episode))
            labels.append('unit3d')

        enable_ygg = os.getenv('ENABLE_YGG', 'false').lower() in ('true', '1', 'yes')
        if enable_ygg:
            ygg = YggService()
            if media_type == 'movie':
                tasks.append(ygg.search_movie(title, year, original_title=original_title, imdb_id=imdb_id, tmdb_id=tmdb_id))
            else:
                tasks.append(ygg.search_series(title, season, episode, original_title=original_title, imdb_id=imdb_id, tmdb_id=tmdb_id))
            labels.append('ygg')

        if config.get('abn_username') and config.get('abn_password'):
            abn = ABNService(config['abn_username'], config['abn_password'])
            closables.append(abn)
            if media_type == 'movie':
                tasks.append(abn.search_movie(title, year, original_title=original_title))
            else:
                tasks.append(abn.search_series(title, season, episode, original_title=original_title))
            labels.append('abn')

        provider_specs = [
            ('c411', config.get('c411_apikey'), C411Service),
            ('torr9', config.get('torr9_passkey'), Torr9Service),
            ('tr4ker', config.get('tr4ker_apikey'), Tr4kerService),
        ]
        for label, credential, cls in provider_specs:
            if not credential:
                continue
            service = cls(credential)
            if media_type == 'movie':
                tasks.append(service.search_movie(title, year, imdb_id=imdb_id, tmdb_id=tmdb_id))
            else:
                tasks.append(service.search_series(title, season, episode, imdb_id=imdb_id, tmdb_id=tmdb_id))
            labels.append(label)

        try:
            results = await asyncio.gather(*tasks, return_exceptions=True)
        finally:
            for service in closables:
                try:
                    await service.close()
                except Exception:
                    logging.exception('Failed to close torrent provider')

        combined = []
        counts = {}
        for label, result in zip(labels, results):
            if isinstance(result, Exception):
                logging.error('Torrent provider %s failed: %s', label, result)
                counts[label] = 0
                continue
            items = result or []
            for item in items:
                item.setdefault('source', label)
            counts[label] = len(items)
            combined.extend(items)

        logging.info('Torrent search results: %s', ', '.join(f'{k}={v}' for k, v in counts.items()))
        return combined
