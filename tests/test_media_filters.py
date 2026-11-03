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

    def test_series_require_vff_or_full_french_subtitles(self):
        for tag in ["MULTI", "VF", "VFI", "VFQ", "FRENCH", "SUBFRENCH.FORCED", "VOSTFR.FORCED"]:
            with self.subTest(tag=tag):
                self.assertEqual(rank_stream_candidates(candidates("Serie.S01E01." + tag), "series", {}), [])
        for tag in ["VFF", "MULTI.VFF", "VFF.SUBFRENCH.FORCED", "VOSTFR", "SUBFRENCH", "SUBFR", "FRENCH.SUBS", "SUBFRENCH.FULL"]:
            with self.subTest(tag=tag):
                self.assertEqual(len(rank_stream_candidates(candidates("Serie.S01E01." + tag), "series", {})), 1)

    def test_below_pack_with_installed_series_profile(self):
        name = "Below.S01.MULTi.VFF.1080p.WEB.EAC3.5.1.H265-GL0P"
        config = {"series_filters": {
            "smart_require_french_subtitles": True,
            "smart_require_eac3": True,
            "smart_quality_mode": "prefer-4k",
            "smart_fallback": True,
        }}
        result = rank_stream_candidates(candidates(name), "series", config)
        self.assertEqual([t["name"] for t, _ in result], [name])

    def test_series_fallback_does_not_restore_unwanted_language(self):
        for enabled in (True, False):
            config = {"smart_filter_enabled": enabled, "smart_quality_mode": "4k-only"}
            result = rank_stream_candidates(candidates("Serie.1080p.VFF", "Serie.2160p.VFQ"), "series", config)
            self.assertEqual([t["name"] for t, _ in result], ["Serie.1080p.VFF"])

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
