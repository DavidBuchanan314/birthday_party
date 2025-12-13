"""Integration tests for the birthday party server."""

from aiohttp.test_utils import TestClient

from birthday_party.database import BirthdayDB


class TestDashboard:
	"""Tests for the dashboard endpoint."""

	async def test_dashboard_loads(self, client: TestClient) -> None:
		"""Test that the dashboard page loads successfully."""
		resp = await client.get("/")
		assert resp.status == 200
		assert resp.content_type.startswith("text/html")

	async def test_dashboard_contains_title(self, client: TestClient) -> None:
		"""Test that the dashboard contains the expected title."""
		resp = await client.get("/")
		text = await resp.text()
		assert "Birthday Party" in text

	async def test_dashboard_shows_config(self, client: TestClient) -> None:
		"""Test that the dashboard shows configuration information."""
		resp = await client.get("/")
		text = await resp.text()
		assert "Target collision length" in text
		assert "Distinguished Point difficulty" in text

	async def test_dashboard_shows_stats(self, client: TestClient) -> None:
		"""Test that the dashboard shows statistics."""
		resp = await client.get("/")
		text = await resp.text()
		assert "Distinguished Points found" in text
		assert "Network hashrate" in text
		assert "Pre-collisions found" in text

	async def test_dashboard_shows_users(self, client: TestClient) -> None:
		"""Test that the dashboard shows the user list."""
		resp = await client.get("/")
		text = await resp.text()
		# Should show our test users
		assert "testuser" in text
		assert "alice" in text
		assert "bob" in text


class TestSubmitWork:
	"""Tests for the submit_work endpoint."""

	async def test_submit_work_requires_post(self, client: TestClient) -> None:
		"""Test that GET requests are not allowed on submit_work."""
		resp = await client.get("/submit_work")
		assert resp.status == 405  # Method Not Allowed

	async def test_submit_work_rejects_invalid_json(self, client: TestClient) -> None:
		"""Test that invalid JSON is rejected."""
		resp = await client.post("/submit_work", data="not json")
		assert resp.status == 400

	async def test_submit_work_rejects_bad_credentials(self, client: TestClient) -> None:
		"""Test that bad credentials are rejected."""
		resp = await client.post(
			"/submit_work",
			json={
				"username": "wronguser",
				"usertoken": "wrongtoken",
				"results": [],
			},
		)
		assert resp.status == 401
		data = await resp.json()
		assert "bad username and/or usertoken" in data["status"]

	async def test_submit_work_accepts_valid_credentials(self, client: TestClient) -> None:
		"""Test that valid credentials are accepted with empty results."""
		resp = await client.post(
			"/submit_work",
			json={
				"username": "testuser",
				"usertoken": "testtoken",
				"results": [],
			},
		)
		assert resp.status == 200
		data = await resp.json()
		assert "accepted 0 results" in data["status"]

	async def test_submit_work_rejects_bad_hash_length(self, client: TestClient) -> None:
		"""Test that results with incorrect hash length are rejected."""
		resp = await client.post(
			"/submit_work",
			json={
				"username": "testuser",
				"usertoken": "testtoken",
				"results": [
					{
						"start": "deadbeef",  # Too short (4 bytes instead of 8)
						"dp": "deadbeef",
					}
				],
			},
		)
		assert resp.status == 400
		data = await resp.json()
		assert data["status"] == "bad hash length"


class TestCollisionDetection:
	"""Tests for collision detection logic."""

	async def test_duplicate_dp_creates_collision(self, client: TestClient, test_db: BirthdayDB) -> None:
		"""Test that submitting a duplicate distinguished point creates a collision."""
		# First, submit a DP to establish it in the database
		resp = await client.post(
			"/submit_work",
			json={
				"username": "alice",
				"usertoken": "alicetoken",
				"results": [
					{
						"start": "deadbeefcafebabe",
						"dp": "1111111111111111",  # This is the DP endpoint that will collide
					}
				],
			},
		)
		assert resp.status == 200
		
		# Verify the DP was added
		initial_dp_count = test_db.get_dp_count()
		assert initial_dp_count == 1
		
		# Now submit another DP with the SAME endpoint but different start
		resp = await client.post(
			"/submit_work",
			json={
				"username": "bob",
				"usertoken": "bobtoken",
				"results": [
					{
						"start": "fedcba9876543210",  # Different start
						"dp": "1111111111111111",      # Same DP endpoint - collision!
					}
				],
			},
		)
		assert resp.status == 200
		
		# Verify the collision was detected and recorded
		final_dp_count = test_db.get_dp_count()
		assert final_dp_count == 2  # Both DPs should be in the database
		
		collision_count = test_db.get_collision_count()
		assert collision_count == 1  # One collision should be recorded
		
		# Verify the collision details
		collisions = test_db.get_collisions()
		assert len(collisions) == 1
		starta, startb, end, usera, userb, timestamp = collisions[0]
		
		# Check that the collision links the correct data
		assert starta.hex() == "deadbeefcafebabe"
		assert startb.hex() == "fedcba9876543210"
		assert end.hex() == "1111111111111111"
		assert usera == "alice"
		assert userb == "bob"


class TestIntegration:
	"""End-to-end integration tests."""

	async def test_user_stats_update_after_submission(self, client: TestClient, test_db: BirthdayDB) -> None:
		"""Test that user stats update after submitting valid work."""
		# The server doesn't check distinguished-ness, only hash length
		# So we can submit any 8-byte (64-bit) hashes
		
		# Get initial DP count for alice
		users = {username: dpcount for _, username, dpcount in test_db.get_users_by_dpcount()}
		initial_dpcount = users.get("alice", 0)
		
		# Submit valid work with proper hash lengths (8 bytes for 64-bit hashes)
		resp = await client.post(
			"/submit_work",
			json={
				"username": "alice",
				"usertoken": "alicetoken",
				"results": [
					{
						"start": "deadbeefcafebabe",  # 8 bytes = 64 bits
						"dp": "0123456789abcdef",     # 8 bytes = 64 bits
					},
					{
						"start": "1111111111111111",
						"dp": "2222222222222222",
					},
				],
			},
		)
		assert resp.status == 200
		data = await resp.json()
		assert "accepted 2 results" in data["status"]
		
		# Verify user stats were updated
		users = {username: dpcount for _, username, dpcount in test_db.get_users_by_dpcount()}
		final_dpcount = users.get("alice", 0)
		assert final_dpcount == initial_dpcount + 2

	async def test_dashboard_reflects_database_state(self, client: TestClient, test_db: BirthdayDB) -> None:
		"""Test that dashboard shows current database state."""
		# Add a user with some DPs
		test_db.increment_user_dpcount(1, 100)  # testuser gets 100 DPs

		# Check dashboard shows this
		resp = await client.get("/")
		text = await resp.text()

		# Should show the user with their DP count
		assert "testuser" in text
		assert "100" in text  # DP count
