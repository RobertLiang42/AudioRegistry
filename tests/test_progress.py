import unittest

from audio_registry.i18n import t
from audio_registry.progress import DiarizationProgress


class ProgressTests(unittest.TestCase):
    def test_clustering_does_not_keep_embedding_percentage(self):
        with DiarizationProgress() as hook:
            hook("embeddings", total=10, completed=6)
            self.assertEqual(hook.progress.tasks[0].completed, 6)
            self.assertEqual(hook.progress.tasks[0].total, 10)
            hook("embeddings")
            self.assertIsNone(hook.progress.tasks[0].total)
            self.assertEqual(hook.progress.tasks[0].description, t("progress.clustering"))

    def test_error_is_not_displayed_as_completion(self):
        hook = DiarizationProgress()
        with self.assertRaisesRegex(RuntimeError, "model failed"):
            with hook:
                raise RuntimeError("model failed")
        self.assertEqual(hook.progress.tasks[0].description, t("progress.diarization_failed"))
        self.assertFalse(hook.progress.tasks[0].finished)


if __name__ == "__main__":
    unittest.main()
