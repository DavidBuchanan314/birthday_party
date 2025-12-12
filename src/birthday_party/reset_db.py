#!/usr/bin/env python3
"""Helper script to reset the database and create a test user."""

import os
from birthday_party.database import BirthdayDB

DB_PATH = "birthdayparty.db"


def reset_database():
	if os.path.exists(DB_PATH):
		print(f"Deleting existing database at {DB_PATH}...")
		os.remove(DB_PATH)

	# Create new database (tables will be auto-initialized)
	print(f"Creating new database at {DB_PATH}...")
	db = BirthdayDB(DB_PATH)

	# Create test users
	print("Creating test users...")
	db.create_user("retr0id", "foobar")
	db.create_user("somebody", "foobar")
	db.create_user("hello", "foobar")

	db.commit()
	db.close()


if __name__ == "__main__":
	reset_database()
