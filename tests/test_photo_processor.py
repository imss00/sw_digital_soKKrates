from unittest import TestCase

from backend.collectors.photo_processor import filter_scene_labels


class PhotoProcessorTest(TestCase):
    def test_filter_scene_labels_removes_generic_and_low_score_labels(self):
        labels = filter_scene_labels([
            {"description": "Sky", "score": 0.99},
            {"description": "Mountain", "score": 0.91},
            {"description": "Blur", "score": 0.2},
            {"description": "Trail", "score": 0.72},
            {"description": "Mountain", "score": 0.88},
        ])

        self.assertEqual(
            labels,
            [
                {"description": "Mountain", "score": 0.91},
                {"description": "Trail", "score": 0.72},
            ],
        )
