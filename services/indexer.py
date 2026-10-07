import asyncio
import logging
import os

from services.tmdb import TMDBService
from services.torrent_cache import TorrentCacheService
from services.torrent_search import TorrentSearchService
from utils import check_season_episode, check_title_match, is_video_file


class RecentMediaIndexer:
    def __init__(self, cache=None):
        self.cache = cache or TorrentCacheService()
        self.search = TorrentSearchService()
        self.interval = int(os.getenv('INDEXER_INTERVAL_SECONDS', '43200'))
        self.max_movies = int(os.getenv('INDEXER_MAX_MOVIES', '20'))
        self.max_series = int(os.getenv('INDEXER_MAX_SERIES', '20'))
        self.concurrency = max(1, int(os.getenv('INDEXER_CONCURRENCY', '3')))

    async def run_forever(self):
        await asyncio.sleep(int(os.getenv('INDEXER_START_DELAY_SECONDS', '60')))
        while True:
            try:
                await self.run_once()
            except asyncio.CancelledError:
                raise
            except Exception:
                logging.exception('Recent media indexer failed')
            await asyncio.sleep(self.interval)

    async def run_once(self):
        config = await self.cache.load_config()
        if not config or not config.get('tmdb_key'):
            logging.info('Indexer skipped: no saved Frenchio configuration yet')
            return

        tmdb = TMDBService(config['tmdb_key'])
        movies, series = await asyncio.gather(
            tmdb.get_recent_movies(limit=self.max_movies),
            tmdb.get_recent_series(limit=self.max_series),
        )
        jobs = [('movie', item) for item in movies] + [('series', item) for item in series]
        logging.info('Indexer starting: %d movies, %d series', len(movies), len(series))

        semaphore = asyncio.Semaphore(self.concurrency)

        async def worker(media_type, item):
            async with semaphore:
                try:
                    await self._index_item(config, tmdb, media_type, item)
                except Exception:
                    logging.exception('Indexer error for %s %s', media_type, item.get('id'))

        await asyncio.gather(*(worker(media_type, item) for media_type, item in jobs))
        logging.info('Indexer pass completed')

    async def _index_item(self, config, tmdb, media_type, item):
        tmdb_id = item.get('id')
        details = await tmdb.get_media_details(tmdb_id, media_type)
        if not details:
            return

        imdb_id = details.get('imdb_id') or await tmdb.get_imdb_id(tmdb_id, media_type)
        title = details.get('title') or details.get('name') or ''
        original_title = details.get('original_title') or details.get('original_name') or ''
        date = details.get('release_date') or details.get('first_air_date') or ''
        year = date[:4]
        season = episode = None
        if media_type == 'series':
            last_episode = details.get('last_episode_to_air') or {}
            season = last_episode.get('season_number')
            episode = last_episode.get('episode_number')
            if season is None or episode is None:
                return

        torrents = await self.search.search(
            config=config, media_type=media_type, tmdb_id=tmdb_id, imdb_id=imdb_id,
            title=title, original_title=original_title, year=year, season=season, episode=episode,
        )

        filtered = []
        for torrent in torrents:
            name = torrent.get('name', '')
            if not torrent.get('info_hash') or not is_video_file(name):
                continue
            if not check_title_match(name, title, original_title, year=year, is_movie=(media_type == 'movie')):
                continue
            if media_type == 'series' and not check_season_episode(name, season, episode):
                continue
            filtered.append(torrent)

        await self.cache.upsert_media(
            media_type=media_type,
            tmdb_id=tmdb_id,
            imdb_id=imdb_id,
            name=title,
            poster_path=details.get('poster_path'),
            release_info=(details.get('release_date') or details.get('first_air_date') or '')[:4],
            description=details.get('overview') or '',
        )
        await self.cache.upsert_many(media_type, tmdb_id, imdb_id, season, episode, filtered)
        logging.info('Indexed %s %s: %d torrents', media_type, title, len(filtered))
