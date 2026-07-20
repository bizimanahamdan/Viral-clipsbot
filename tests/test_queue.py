"""
Tests for the queue manager.
"""

import asyncio
import unittest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


class TestQueueManager(unittest.TestCase):
    """Test queue manager functionality."""

    def test_queue_imports(self):
        """Test that queue manager imports without error."""
        from utilities.queue_manager import QueueManager, QueueJob
        self.assertTrue(hasattr(QueueManager, "start"))
        self.assertTrue(hasattr(QueueManager, "stop"))
        self.assertTrue(hasattr(QueueManager, "submit_job"))
        self.assertTrue(hasattr(QueueManager, "cancel_user_jobs"))

    def test_queue_job_creation(self):
        """Test QueueJob dataclass creation."""
        from utilities.queue_manager import QueueJob

        job = QueueJob(
            job_id="test_123",
            user_id=42,
            source_type="youtube",
            source_url="https://youtube.com/watch?v=test",
        )
        self.assertEqual(job.job_id, "test_123")
        self.assertEqual(job.user_id, 42)
        self.assertEqual(job.source_type, "youtube")

    def test_queue_job_with_settings(self):
        """Test QueueJob with settings."""
        from utilities.queue_manager import QueueJob

        job = QueueJob(
            job_id="test_456",
            user_id=99,
            source_type="upload",
            source_file_path="/tmp/video.mp4",
            settings={"num_shorts": 5, "caption_style": "hormozi"},
        )
        self.assertEqual(job.settings["num_shorts"], 5)


if __name__ == "__main__":
    unittest.main()
