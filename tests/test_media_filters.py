import unittest

from stream_filter import rank_stream_candidates


def candidates(*names):
    return [({"name": name, "size": 1024 ** 3}, str(i)) for i, name in enumerate(names)]


class MediaFiltersTest(unittest.TestCase):
    def test_movies_require_explicit_vff_even_with_fallback(self):
        for tag in ["VF", "VFI", "FRENCH", "MULTI", "VFQ"]:
            with self.subTest(tag=tag):
                self.assertEqual(rank_stream_candidates(candidates("Film.1080p." + tag), "movie", {}), [])
        self.assertEqual(len(rank_stream_candidates(candidates("Film.MULTI.VFF"), "movie", {})), 1)

    def test_series_require_full_french_subtitles(self):
        for tag in ["MULTI", "VFF", "SUBFRENCH.FORCED", "VOSTFR.FORCED"]:
            with self.subTest(tag=tag):
                self.assertEqual(rank_stream_candidates(candidates("Serie.S01E01." + tag), "series", {}), [])
        for tag in ["VOSTFR", "SUBFRENCH", "SUBFR", "FRENCH.SUBS", "SUBFRENCH.FULL"]:
            with self.subTest(tag=tag):
                self.assertEqual(len(rank_stream_candidates(candidates("Serie.S01E01." + tag), "series", {})), 1)

    def test_language_requirement_survives_disabled_ranking(self):
        self.assertEqual(rank_stream_candidates(candidates("Film.MULTI"), "movie", {"smart_filter_enabled": False}), [])

    def test_profiles_are_independent(self):
        config = {"movie_filters": {"smart_quality_mode": "4k-only", "smart_fallback": False},
                  "series_filters": {"smart_quality_mode": "prefer-1080p", "smart_max_results": 1}}
        self.assertEqual(rank_stream_candidates(candidates("Film.1080p.VFF"), "movie", config), [])
        result = rank_stream_candidates(candidates("Serie.2160p.VOSTFR", "Serie.1080p.VOSTFR"), "series", config)
        self.assertEqual(result[0][0]["name"], "Serie.1080p.VOSTFR")
        self.assertEqual(len(result), 1)

    def test_legacy_settings_are_preserved(self):
        self.assertEqual(rank_stream_candidates(candidates("Film.1080p.VFF"), "movie",
                         {"smart_require_x265": True, "smart_fallback": False}), [])

    def test_fallback_never_reintroduces_wrong_language(self):
        result = rank_stream_candidates(candidates("Film.1080p.VFF", "Film.2160p.VFQ"), "movie",
                                        {"smart_quality_mode": "4k-only"})
        self.assertEqual([t["name"] for t, _ in result], ["Film.1080p.VFF"])


if __name__ == "__main__":
    unittest.main()
