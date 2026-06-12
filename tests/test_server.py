import copy
import unittest
from unittest.mock import patch

import server


class FakeTable:
    def __init__(self, records):
        self._records = [copy.deepcopy(record) for record in records]

    def all(self):
        return [copy.deepcopy(record) for record in self._records]


class CaptureHandler:
    def __init__(self):
        self.payload = None
        self.status = None

    def send_json(self, payload, status=200):
        self.payload = payload
        self.status = status


class ServerComparisonTests(unittest.TestCase):
    def setUp(self):
        self.track_a = {
            "file": "a.wav",
            "artist": "A",
            "title": "Track A",
            "bpm": 128.0,
            "camelot": "8A",
            "avg_energy_level": 7,
            "comparison_features": {
                "lufs": -14.0,
                "lra_lu": 6.0,
                "crest_factor_db": 7.0,
                "spectral_centroid_hz": 2200.0,
                "bass_ratio": 0.33,
                "mid_ratio": 0.45,
                "high_ratio": 0.22,
                "stereo_width": 1.2,
                "clipping_ratio": 0.0003,
                "transient_sharpness": 3.5,
                "mfcc_mean": [1.0] * 13,
                "mfcc_std": [0.5] * 13,
            },
        }

        self.track_b = {
            "file": "b.wav",
            "artist": "B",
            "title": "Track B",
            "bpm": 129.0,
            "camelot": "8B",
            "avg_energy_level": 7,
            "comparison_features": {
                "lufs": -13.8,
                "lra_lu": 6.2,
                "crest_factor_db": 6.8,
                "spectral_centroid_hz": 2280.0,
                "bass_ratio": 0.34,
                "mid_ratio": 0.44,
                "high_ratio": 0.22,
                "stereo_width": 1.15,
                "clipping_ratio": 0.0004,
                "transient_sharpness": 3.7,
                "mfcc_mean": [0.95] * 13,
                "mfcc_std": [0.52] * 13,
            },
        }

        self.track_c = {
            "file": "c.wav",
            "artist": "C",
            "title": "Track C",
            "bpm": 140.0,
            "camelot": "2A",
            "avg_energy_level": 4,
            "comparison_features": {
                "lufs": -9.0,
                "lra_lu": 3.0,
                "crest_factor_db": 3.8,
                "spectral_centroid_hz": 5100.0,
                "bass_ratio": 0.18,
                "mid_ratio": 0.40,
                "high_ratio": 0.42,
                "stereo_width": 0.7,
                "clipping_ratio": 0.009,
                "transient_sharpness": 8.8,
                "mfcc_mean": [-1.2] * 13,
                "mfcc_std": [1.4] * 13,
            },
        }

        self.track_d = {
            "file": "d.wav",
            "artist": "D",
            "title": "Track D",
            "bpm": 127.6,
            "camelot": "7A",
            "avg_energy_level": 6,
            "comparison_features": {
                "lufs": -14.2,
                "lra_lu": 6.5,
                "crest_factor_db": 7.1,
                "spectral_centroid_hz": 2100.0,
                "bass_ratio": 0.36,
                "mid_ratio": 0.43,
                "high_ratio": 0.21,
                "stereo_width": 1.1,
                "clipping_ratio": 0.0002,
                "transient_sharpness": 3.3,
                "mfcc_mean": [1.02] * 13,
                "mfcc_std": [0.49] * 13,
            },
        }

    def test_bpm_transition_recommendation_thresholds(self):
        straight = server._bpm_transition_recommendation(self.track_a, self.track_b)
        self.assertEqual(straight["recommendation"], "straight mix")
        self.assertEqual(straight["tag"], "tempo-safe")

        nudged_target = dict(self.track_b)
        nudged_target["bpm"] = 132.6
        nudge = server._bpm_transition_recommendation(self.track_a, nudged_target)
        self.assertEqual(nudge["recommendation"], "small nudge")
        self.assertEqual(nudge["tag"], "tempo-nudge")

        risky_target = dict(self.track_b)
        risky_target["bpm"] = 138.8
        risky = server._bpm_transition_recommendation(self.track_a, risky_target)
        self.assertEqual(risky["recommendation"], "risky")
        self.assertEqual(risky["tag"], "tempo-risk")

    def test_compare_tracks_returns_dj_workflow_shape(self):
        compared = server._compare_tracks(self.track_a, self.track_b)

        self.assertIn("similarity_score", compared)
        self.assertGreaterEqual(compared["similarity_score"], 0.0)
        self.assertLessEqual(compared["similarity_score"], 100.0)

        self.assertIn("dj_workflow", compared)
        self.assertIn("bpm_transition", compared["dj_workflow"])
        self.assertIn("energy_transition", compared["dj_workflow"])
        self.assertIn("harmonic", compared["dj_workflow"])
        self.assertIn("tags", compared["dj_workflow"])

        self.assertIn("tempo-safe", compared["tags"])

    def test_compare_tracks_by_file_includes_feature_snapshots(self):
        table = FakeTable([self.track_a, self.track_b])

        with (
            patch.object(server, "TRACKS_TABLE", table),
            patch.object(server, "ensure_seed_data", lambda: None),
        ):
            payload = server.compare_tracks_by_file("a.wav", "b.wav")

        self.assertIn("left_features", payload)
        self.assertIn("right_features", payload)
        self.assertIn("lufs", payload["left_features"])
        self.assertIn("spectral_centroid_hz", payload["right_features"])

    def test_find_track_prefers_feature_rich_duplicate(self):
        sparse_variant = {
            "file": "a.wav",
            "artist": "A",
            "title": "Track A",
            "bpm": 128.0,
            "camelot": "8A",
            "avg_energy_level": 7,
        }
        rich_variant = copy.deepcopy(self.track_a)
        rich_variant["analysis_version"] = 2

        table = FakeTable([sparse_variant, rich_variant])

        with (
            patch.object(server, "TRACKS_TABLE", table),
            patch.object(server, "ensure_seed_data", lambda: None),
        ):
            selected = server._find_track_by_file("a.wav")

        self.assertIn("comparison_features", selected)
        self.assertIn("lufs", selected["comparison_features"])

    def test_similar_tracks_sorted_and_excludes_source(self):
        table = FakeTable([self.track_a, self.track_b, self.track_c, self.track_d])

        with (
            patch.object(server, "TRACKS_TABLE", table),
            patch.object(server, "ensure_seed_data", lambda: None),
        ):
            payload = server.similar_tracks_for_file("a.wav", limit=3)

        self.assertEqual(payload["source"]["file"], "a.wav")
        self.assertEqual(len(payload["results"]), 3)
        self.assertTrue(
            all(item["track"]["file"] != "a.wav" for item in payload["results"])
        )

        scores = [item["similarity_score"] for item in payload["results"]]
        self.assertEqual(scores, sorted(scores, reverse=True))

        top_match_file = payload["results"][0]["track"]["file"]
        self.assertIn(top_match_file, {"b.wav", "d.wav"})

    def test_playlist_seed_returns_progression_and_transitions(self):
        table = FakeTable([self.track_a, self.track_b, self.track_c, self.track_d])

        with (
            patch.object(server, "TRACKS_TABLE", table),
            patch.object(server, "ensure_seed_data", lambda: None),
        ):
            payload = server.playlist_seed_for_file("a.wav", limit=4)

        self.assertEqual(payload["source"]["file"], "a.wav")
        self.assertEqual(len(payload["playlist"]), 4)
        self.assertEqual(len(payload["transitions"]), 3)

        for transition in payload["transitions"]:
            self.assertIn("dj_workflow", transition)
            self.assertIn("ranking", transition)
            self.assertIn("hard_jump", transition["ranking"])


class ServerApiHandlerTests(unittest.TestCase):
    def test_handle_compare_query_returns_payload_with_query(self):
        handler = CaptureHandler()
        expected = {
            "left": {"file": "a.wav"},
            "right": {"file": "b.wav"},
            "similarity_score": 88.5,
            "tags": ["harmonic", "tempo-safe"],
            "dj_workflow": {"harmonic_mix": True},
        }

        with patch.object(server, "compare_tracks_by_file", return_value=expected):
            server.AnalyzerHandler.handle_compare_query(
                handler, "left=a.wav&right=b.wav"
            )

        self.assertEqual(handler.status, 200)
        self.assertEqual(handler.payload["query"], {"left": "a.wav", "right": "b.wav"})
        self.assertIn("dj_workflow", handler.payload)

    def test_handle_similar_query_validates_limit(self):
        handler = CaptureHandler()

        with self.assertRaises(ValueError):
            server.AnalyzerHandler.handle_similar_query(handler, "file=a.wav&limit=abc")

        with self.assertRaises(ValueError):
            server.AnalyzerHandler.handle_similar_query(handler, "file=a.wav&limit=0")

    def test_handle_similar_query_returns_query_and_results(self):
        handler = CaptureHandler()
        expected = {
            "source": {"file": "a.wav"},
            "results": [
                {
                    "track": {"file": "b.wav"},
                    "similarity_score": 91.1,
                    "tags": ["harmonic", "tempo-safe"],
                    "dj_workflow": {"harmonic_mix": True},
                }
            ],
        }

        with patch.object(server, "similar_tracks_for_file", return_value=expected):
            server.AnalyzerHandler.handle_similar_query(handler, "file=a.wav&limit=1")

        self.assertEqual(handler.status, 200)
        self.assertEqual(handler.payload["query"], {"file": "a.wav", "limit": 1})
        self.assertEqual(handler.payload["results"][0]["track"]["file"], "b.wav")

    def test_handle_playlist_seed_query_validates_and_returns_payload(self):
        handler = CaptureHandler()

        with self.assertRaises(ValueError):
            server.AnalyzerHandler.handle_playlist_seed_query(
                handler, "file=a.wav&limit=1"
            )

        expected = {
            "source": {"file": "a.wav"},
            "playlist": [{"file": "a.wav"}, {"file": "b.wav"}],
            "transitions": [{"from": {"file": "a.wav"}, "to": {"file": "b.wav"}}],
        }

        with patch.object(server, "playlist_seed_for_file", return_value=expected):
            server.AnalyzerHandler.handle_playlist_seed_query(
                handler, "file=a.wav&limit=2"
            )

        self.assertEqual(handler.status, 200)
        self.assertEqual(handler.payload["query"], {"file": "a.wav", "limit": 2})
        self.assertEqual(len(handler.payload["playlist"]), 2)


if __name__ == "__main__":
    unittest.main()
