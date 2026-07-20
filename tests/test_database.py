"""
Tests for the database module.
"""

import asyncio
import unittest
from unittest.mock import patch, AsyncMock
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


class TestDatabaseSchema(unittest.TestCase):
    """Test database schema and operations."""

    def test_schema_imports(self):
        """Test that schema module imports without error."""
        from database.schema import (
            USERS_TABLE_SQL,
            USER_SETTINGS_TABLE_SQL,
            HISTORY_TABLE_SQL,
            JOBS_TABLE_SQL,
            STATISTICS_TABLE_SQL,
        )
        self.assertIn("CREATE TABLE IF NOT EXISTS users", USERS_TABLE_SQL)
        self.assertIn("CREATE TABLE IF NOT EXISTS user_settings", USER_SETTINGS_TABLE_SQL)
        self.assertIn("CREATE TABLE IF NOT EXISTS history", HISTORY_TABLE_SQL)
        self.assertIn("CREATE TABLE IF NOT EXISTS jobs", JOBS_TABLE_SQL)
        self.assertIn("CREATE TABLE IF NOT EXISTS statistics", STATISTICS_TABLE_SQL)

    def test_connection_imports(self):
        """Test that connection module imports without error."""
        from database.connection import get_connection, init_database
        self.assertTrue(callable(get_connection))
        self.assertTrue(callable(init_database))


class TestDatabaseOperations(unittest.TestCase):
    """Test database CRUD operations (mocked)."""

    def test_users_module_imports(self):
        """Test that users module imports without error."""
        from database import users
        self.assertTrue(hasattr(users, "upsert_user"))
        self.assertTrue(hasattr(users, "get_user"))
        self.assertTrue(hasattr(users, "set_admin"))

    def test_settings_module_imports(self):
        """Test that settings module imports without error."""
        from database import settings
        self.assertTrue(hasattr(settings, "get_or_create_settings"))
        self.assertTrue(hasattr(settings, "update_caption_style"))
        self.assertTrue(hasattr(settings, "reset_settings"))

    def test_jobs_module_imports(self):
        """Test that jobs module imports without error."""
        from database import jobs
        self.assertTrue(hasattr(jobs, "create_job"))
        self.assertTrue(hasattr(jobs, "get_user_active_jobs"))
        self.assertTrue(hasattr(jobs, "cancel_job"))

    def test_history_module_imports(self):
        """Test that history module imports without error."""
        from database import history
        self.assertTrue(hasattr(history, "add_history_record"))
        self.assertTrue(hasattr(history, "get_user_history"))

    def test_statistics_module_imports(self):
        """Test that statistics module imports without error."""
        from database import statistics
        self.assertTrue(hasattr(statistics, "log_event"))
        self.assertTrue(hasattr(statistics, "get_global_stats_summary"))


if __name__ == "__main__":
    unittest.main()
