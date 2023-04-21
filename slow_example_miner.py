import hashlib
import requests
import time
import os
import sys

SERVER = "http://localhost:8080/"

# collision parameters (MUST BE SAME AS SERVER'S!!!)
DP_DIFFICULTY = 8 # bits

def HASH_FN(x):
	return hashlib.md5(x.hex().encode()).digest()[:8] # half-md5

def IS_DISTINGUISHED(x):
	leading_zeroes = len(x) * 8 - int.from_bytes(x, "big").bit_length()
	return leading_zeroes >= DP_DIFFICULTY

HASH_LENGTH = len(HASH_FN(b"")) # bytes

# miner config
MIN_REPORT_INTERVAL = 1
USERNAME = sys.argv[1]
USERTOKEN = "foobar"

s = requests.session()
def report_results(results):
	r = s.post(SERVER + "submit_work", json={
		"username": USERNAME,
		"usertoken": USERTOKEN,
		"results": results
	})
	if not r.ok:
		print("SERVER ERROR:", r.content)
	else:
		print("Server says:", r.json()["status"])

prev_report = time.time()
report = []
point = os.urandom(HASH_LENGTH)
start_point = point
while True:
	prev_point = point
	point = HASH_FN(point)
	if IS_DISTINGUISHED(point):
		report.append({
			"start": start_point.hex(),
			"penultimate": prev_point.hex(),
		})
		delta = time.time() - prev_report
		if delta > MIN_REPORT_INTERVAL:
			print(f"Reporting {len(report)} DPs... ({len(report)/delta:0.2f} DP/s)")
			report_results(report)
			prev_report = time.time()
			report = []
		# this randomisation is not essential, it just means we won't get stuck in a loop
		point = os.urandom(HASH_LENGTH)
		start_point = point
