"""
Tests for the security module.
"""

import unittest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


class TestSecurity(unittest.TestCase):
    """Test security utilities."""

    def test_rate_limiter_imports(self):
        """Test rate limiter imports."""
        from utilities.security import RateLimiter
        rl = RateLimiter(max_requests=10, window_seconds=60)
        self.assertFalse(rl.is_rate_limited("test_user"))

    def test_rate_limit_enforcement(self):
        """Test that rate limiting works."""
        from utilities.security import RateLimiter
        # Use a unique user ID to avoid cross-test pollution from the global singleton
        rl = RateLimiter(max_requests=3, window_seconds=60)
        user = "unique_test_user_enforcement_12345"

        # First 3 requests should be within limit
        for i in range(3):
            rl.register_request(user)
            # After registering, the count should match but not exceed
            remaining = rl.get_remaining(user)
            self.assertGreaterEqual(remaining, 0)

        # 4th request triggers rate limit
        rl.register_request(user)
        self.assertTrue(rl.is_rate_limited(user))

    def test_validate_youtube_url(self):
        """Test YouTube URL validation."""
        from utilities.security import validate_youtube_url

        # Valid URLs
        valid_urls = [
            "https://youtube.com/watch?v=dQw4w9WgXcQ",
            "https://youtu.be/dQw4w9WgXcQ",
            "https://www.youtube.com/watch?v=abc123",
        ]
        for url in valid_urls:
            is_valid, _ = validate_youtube_url(url)
            self.assertTrue(is_valid, f"Should be valid: {url}")

        # Invalid URLs
        invalid_urls = [
            "https://example.com/video",
            "not_a_url",
            "https://youtube.com/playlist",
        ]
        for url in invalid_urls:
            is_valid, _ = validate_youtube_url(url)
            self.assertFalse(is_valid, f"Should be invalid: {url}")

    def test_validate_file_extension(self):
        """Test file extension validation."""
        from utilities.security import validate_file_extension

        valid_exts = ["video.mp4", "video.MP4"]
        for ext in valid_exts:
            self.assertTrue(validate_file_extension(ext), f"Should be valid: {ext}")

        invalid_exts = ["file.exe", "script.bat", "lib.dll"]
        for ext in invalid_exts:
            self.assertFalse(validate_file_extension(ext), f"Should be invalid: {ext}")

    def test_sanitize_filename(self):
        """Test filename sanitization."""
        from utilities.security import sanitise_filename

        self.assertEqual(sanitise_filename("normal.mp4"), "normal.mp4")
        self.assertNotIn("..", sanitise_filename("../../etc/passwd.mp4"))
        self.assertNotIn("/", sanitise_filename("path/to/file.mp4"))

    def test_sanitize_text(self):
        """Test text sanitization."""
        from utilities.security import sanitise_text

        # Control characters should be stripped
        text = "Hello\x00\x01World"
        result = sanitise_text(text)
        self.assertIn("Hello", result)
        self.assertIn("World", result)
        self.assertNotIn("\x00", result)
        self.assertNotIn("\x01", result)

        # Truncation should work
        long_text = "x" * 2000
        result = sanitise_text(long_text, max_length=100)
        self.assertEqual(len(result), 100)


if __name__ == "__main__":
    unittest.main()
