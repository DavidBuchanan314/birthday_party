"""Pytest fixtures for integration tests."""

from pathlib import Path
from collections.abc import Generator

import pytest
from aiohttp.test_utils import TestClient
from pytest_aiohttp.plugin import AiohttpClient

from birthday_party.database import BirthdayDB
from birthday_party.server import create_app


@pytest.fixture
def test_db(tmp_path: Path) -> Generator[BirthdayDB, None, None]:
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
async def client(aiohttp_client: AiohttpClient, test_db: BirthdayDB) -> TestClient:
	"""Create a test client with a test database."""
	app = create_app(db=test_db)
	return await aiohttp_client(app)
