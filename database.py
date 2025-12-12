import sqlite3
from typing import Optional, List, Tuple


class BirthdayDB:
	def __init__(self, db_path: str = "birthdayparty.db"):
		self.path = db_path
		self.con = sqlite3.connect(db_path)
		self.cur = self.con.cursor()
		self._init_tables()

	def _init_tables(self):
		"""Initialize database tables if they don't exist."""
		# User table
		self.cur.execute("""CREATE TABLE IF NOT EXISTS user(
			userid INTEGER PRIMARY KEY AUTOINCREMENT,
			username TEXT UNIQUE NOT NULL,
			usertoken TEXT NOT NULL,
			userdpcount INTEGER NOT NULL DEFAULT 0
		)""")

		# Distinguished points table
		self.cur.execute("""CREATE TABLE IF NOT EXISTS dp(
			dpid INTEGER PRIMARY KEY AUTOINCREMENT,
			dpuserid INTEGER NOT NULL,
			dpstart BLOB NOT NULL,
			dpend BLOB NOT NULL,
			dptime INTEGER NOT NULL,
			FOREIGN KEY(dpuserid) REFERENCES user(userid)
		)""")

		# Indexes for dp table
		self.cur.execute("CREATE INDEX IF NOT EXISTS hashend ON dp(dpend)")
		self.cur.execute("CREATE INDEX IF NOT EXISTS hashtime ON dp(dptime)")

		# Recent table for hashrate calculations
		self.cur.execute("""CREATE TABLE IF NOT EXISTS recent(
			rid INTEGER PRIMARY KEY AUTOINCREMENT,
			rdpid INTEGER NOT NULL,
			FOREIGN KEY(rdpid) REFERENCES dp(dpid)
		)""")

		# Collision table
		self.cur.execute("""CREATE TABLE IF NOT EXISTS collision(
			collid INTEGER PRIMARY KEY AUTOINCREMENT,
			colldpidone INTEGER NOT NULL,
			colldpidtwo INTEGER NOT NULL,
			FOREIGN KEY(colldpidone) REFERENCES dp(dpid),
			FOREIGN KEY(colldpidtwo) REFERENCES dp(dpid)
		)""")

		self.con.commit()

	def get_dp_count(self) -> int:
		"""Get total number of distinguished points found."""
		return self.cur.execute("SELECT COUNT(*) FROM dp").fetchone()[0]

	def get_collision_count(self) -> int:
		"""Get total number of pre-collisions found."""
		return self.cur.execute("SELECT COUNT(*) FROM collision").fetchone()[0]

	def get_recent_dp_count(self, minutes: int = 10) -> int:
		"""Get number of DPs found in the last N minutes."""
		return self.cur.execute(
			"SELECT COUNT(*) FROM dp WHERE dptime > UNIXEPOCH('now', ?)",
			(f'-{minutes} minutes',)
		).fetchone()[0]

	def get_users_by_dpcount(self) -> List[Tuple[int, str, int]]:
		"""Get all users ordered by their DP count (descending).

		Returns:
			List of (userid, username, userdpcount) tuples
		"""
		return self.cur.execute(
			"SELECT userid, username, userdpcount FROM user ORDER BY userdpcount DESC"
		).fetchall()

	def get_recent_dps(self, limit: int = 10) -> List[Tuple[str, bytes, bytes, str]]:
		"""Get the most recent distinguished points.

		Args:
			limit: Maximum number of DPs to return

		Returns:
			List of (username, dpstart, dpend, dptime) tuples
		"""
		return self.cur.execute("""
			SELECT username, dpstart, dpend, DATETIME(dptime, 'unixepoch')
			FROM dp
			INNER JOIN user ON dpuserid = userid
			ORDER BY dptime DESC
			LIMIT ?
		""", (limit,)).fetchall()

	def get_collisions(self) -> List[Tuple[bytes, bytes, bytes, str, str, str]]:
		"""Get all pre-collisions with details.

		Returns:
			List of (starta, startb, end, usera, userb, timestamp) tuples
		"""
		return self.cur.execute("""
			SELECT dp1.dpstart, dp2.dpstart, dp1.dpend, user1.username, user2.username, DATETIME(dp2.dptime, 'unixepoch')
			FROM collision
			INNER JOIN dp AS dp1 ON colldpidone = dp1.dpid
			INNER JOIN dp AS dp2 ON colldpidtwo = dp2.dpid
			INNER JOIN user AS user1 ON dp1.dpuserid = user1.userid
			INNER JOIN user AS user2 ON dp2.dpuserid = user2.userid
		""").fetchall()

	def authenticate_user(self, username: str, usertoken: str) -> Optional[int]:
		"""Authenticate a user by username and token.

		Args:
			username: The username
			usertoken: The user's token

		Returns:
			The userid if authentication succeeds, None otherwise
		"""
		result = self.cur.execute(
			"SELECT userid FROM user WHERE username=? AND usertoken=?",
			(username, usertoken)
		).fetchone()
		return result[0] if result else None

	def check_collision(self, dpend: bytes) -> Optional[Tuple[int, bytes]]:
		"""Check if a DP end hash already exists (collision detection).

		Args:
			dpend: The DP end hash to check

		Returns:
			Tuple of (dpid, dpstart) if collision found, None otherwise
		"""
		result = self.cur.execute(
			"SELECT dpid, dpstart FROM dp WHERE dpend=?",
			(dpend,)
		).fetchone()
		return result if result else None

	def insert_dp(self, userid: int, dpstart: bytes, dpend: bytes) -> int:
		"""Insert a single distinguished point.

		Args:
			userid: The user ID who found this DP
			dpstart: The starting hash
			dpend: The ending (distinguished) hash

		Returns:
			The dpid of the inserted row
		"""
		self.cur.execute(
			"INSERT INTO dp (dpuserid, dpstart, dpend, dptime) VALUES (?, ?, ?, UNIXEPOCH('now'))",
			(userid, dpstart, dpend)
		)
		dpid = self.cur.lastrowid
		self.con.commit()
		return dpid

	def insert_collision(self, dpid_one: int, dpid_two: int):
		"""Insert a collision record.

		Args:
			dpid_one: First DP ID in the collision
			dpid_two: Second DP ID in the collision
		"""
		self.cur.execute(
			"INSERT INTO collision (colldpidone, colldpidtwo) VALUES (?, ?)",
			(dpid_one, dpid_two)
		)
		self.con.commit()

	def insert_dps_batch(self, dps: List[Tuple[int, bytes, bytes]]):
		"""Insert multiple distinguished points at once.

		Args:
			dps: List of (userid, dpstart, dpend) tuples
		"""
		self.cur.executemany(
			"INSERT INTO dp (dpuserid, dpstart, dpend, dptime) VALUES (?, ?, ?, UNIXEPOCH('now'))",
			dps
		)
		self.con.commit()

	def increment_user_dpcount(self, userid: int, count: int):
		"""Increment a user's DP count.

		Args:
			userid: The user ID
			count: Amount to increment by
		"""
		self.cur.execute(
			"UPDATE user SET userdpcount = userdpcount + ? WHERE userid = ?",
			(count, userid)
		)
		self.con.commit()

	def create_user(self, username: str, usertoken: str) -> int:
		"""Create a new user.

		Args:
			username: The username
			usertoken: The user's authentication token

		Returns:
			The userid of the created user
		"""
		self.cur.execute(
			"INSERT INTO user (username, usertoken) VALUES (?, ?)",
			(username, usertoken)
		)
		userid = self.cur.lastrowid
		self.con.commit()
		return userid

	def commit(self):
		"""Commit the current transaction."""
		self.con.commit()

	def close(self):
		"""Close the database connection."""
		self.con.close()
