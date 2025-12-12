import hashlib
import requests
import time
import os
import argparse

DP_DIFFICULTY = 16  # bits  (this is deliberately a bit too easy, to help test the server)
MIN_REPORT_INTERVAL = 1  # seconds


def hash_fn(x: bytes):
	return hashlib.md5(x.hex().encode()).digest()[:8]  # half-md5


def is_distinguished(x: bytes):
	leading_zeroes = len(x) * 8 - int.from_bytes(x, "big").bit_length()
	return leading_zeroes >= DP_DIFFICULTY


HASH_LENGTH = len(hash_fn(b""))  # bytes


def mine(server_url: str, username: str, usertoken: str):
	"""Run the mining loop, finding distinguished points and reporting them to the server."""
	session = requests.session()

	def submit_work(results):
		r = session.post(
			server_url.rstrip("/") + "/submit_work",
			json={"username": username, "usertoken": usertoken, "results": results},
		)
		if not r.ok:
			print("SERVER ERROR:", r.content)
		else:
			print("Server says:", r.json()["status"])

	last_report_time = time.time()
	pending_results = []

	while True:
		point = start = os.urandom(HASH_LENGTH)
		while not is_distinguished(point):
			point = hash_fn(point)

		if point == start:  # we got unlucky and the point was already distinguished
			continue

		pending_results.append(
			{
				"start": start.hex(),
				"dp": point.hex(),
			}
		)
		elapsed = time.time() - last_report_time
		if elapsed > MIN_REPORT_INTERVAL:
			print(f"Reporting {len(pending_results)} DPs... ({len(pending_results)/elapsed:0.2f} DP/s)")
			submit_work(pending_results)
			last_report_time = time.time()
			pending_results = []


def main():
	parser = argparse.ArgumentParser(description="MD5 CPU miner for Birthday Party collision search")
	parser.add_argument("username", help="Username for authentication")
	parser.add_argument("--server", default="http://localhost:8080/", help="Server URL")
	parser.add_argument("--usertoken", default="foobar", help="User token for authentication")
	args = parser.parse_args()

	mine(args.server, args.username, args.usertoken)


if __name__ == "__main__":
	main()
