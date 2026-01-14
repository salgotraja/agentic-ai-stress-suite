"""Pytest configuration and global fixtures.

This file is automatically discovered by pytest and makes fixtures
available to all test files.
"""

# Import centralized container fixtures
pytest_plugins = ["tests.fixtures.containers"]
