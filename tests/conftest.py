"""Pytest fixtures for integration tests."""

import sys
from pathlib import Path

import pytest

# Add src to path so we can import modules
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from database import BirthdayDB
from server import create_app


@pytest.fixture
def test_db(tmp_path):
	"""Create a temporary test database with test users."""
	db_path = tmp_path / "test.db"
	db = BirthdayDB(str(db_path))

	# Create test users
	db.create_user("testuser", "testtoken")
	db.create_user("alice", "alicetoken")
	db.create_user("bob", "bobtoken")

	yield db

	db.close()


@pytest.fixture
async def client(aiohttp_client, test_db):
	"""Create a test client with a test database."""
	app = create_app(db=test_db)
	return await aiohttp_client(app)
