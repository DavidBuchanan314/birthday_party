#!/usr/bin/env python3
"""Script to create a new user in the birthday party database."""

import argparse
import uuid
from birthday_party.database import BirthdayDB


def create_user(username: str, password: str | None = None):
	if password is None:
		password = str(uuid.uuid4())
		print(f"Generated password: {password}")

	db = BirthdayDB()
	db.create_user(username, password)


def main():
	parser = argparse.ArgumentParser(description="Create a new user in the birthday party database")
	parser.add_argument("username", help="Username for the new user")
	parser.add_argument("-p", "--password", help="Password/token for the user (auto-generates UUIDv4 if not provided)")

	args = parser.parse_args()
	create_user(args.username, args.password)


if __name__ == "__main__":
	main()
