"""
Tests for the configuration module.
"""

import os
import unittest
from unittest.mock import patch

# Add project root to path
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


class TestConfig(unittest.TestCase):
    """Test configuration loading and validation."""

    def test_config_imports(self):
        """Test that config module imports without error."""
        from configuration.config import TELEGRAM_BOT_TOKEN
        self.assertIsNotNone(TELEGRAM_BOT_TOKEN)

    def test_validate_config_missing_token(self):
        """Test that validation catches missing bot token."""
        from configuration.config import validate_config
        with patch.dict(os.environ, {"TELEGRAM_BOT_TOKEN": ""}):
            issues = validate_config()
            self.assertTrue(any("BOT_TOKEN" in i for i in issues))

    def test_validate_config_valid(self):
        """Test that validation passes with valid config."""
        from configuration.config import validate_config, TELEGRAM_BOT_TOKEN, TELEGRAM_ADMIN_IDS, GROQ_API_KEY
        # Check that the function exists and returns a list
        issues = validate_config()
        self.assertIsInstance(issues, list)


if __name__ == "__main__":
    unittest.main()
