import aiohttp.web
import hashlib
import time
import math
import os
from pathlib import Path

import jinja2
from humanbytes import HumanBytes
from database import BirthdayDB

# Type-safe app keys
db_key = aiohttp.web.AppKey("db", BirthdayDB)
jinja_key = aiohttp.web.AppKey("jinja_env", jinja2.Environment)

# collision parameters
DP_DIFFICULTY = 16  # bits


def HASH_FN(x: bytes) -> bytes:
	return hashlib.md5(x.hex().encode()).digest()[:8]  # half-md5


def IS_DISTINGUISHED(x: bytes) -> bool:
	leading_zeroes = len(x) * 8 - int.from_bytes(x, "big").bit_length()
	return leading_zeroes >= DP_DIFFICULTY


HASH_LENGTH_BYTES = len(HASH_FN(b""))  # bytes


def hashrate_to_string(hashrate: int | float) -> str:
	units = ["", "K", "M", "G", "T", "P", "E"]
	if hashrate > 1:
		unit_idx = max(round(math.log10(hashrate) / 3 - 1.0), 0)
	else:
		unit_idx = 0
	scaled_hashrate = hashrate / 10 ** (unit_idx * 3)
	return f"{round(scaled_hashrate):,}{units[unit_idx]}H/s"


async def handle_dashboard(request: aiohttp.web.Request) -> aiohttp.web.Response:
	start_time = time.time()
	db = request.app[db_key]
	jinja_env = request.app[jinja_key]

	# Gather stats
	db_size = HumanBytes.format(os.path.getsize(db.path))
	dps_found = db.get_dp_count()
	approx_hashes = dps_found * 2**DP_DIFFICULTY
	breakeven_hashes = round(math.sqrt((2 ** (HASH_LENGTH_BYTES * 8) * 2) * math.log(2)))
	prob_success = 1 - (math.e ** -(approx_hashes**2 / ((2 ** (HASH_LENGTH_BYTES * 8)) * 2)))
	precollisions_found = db.get_collision_count()
	dps_last_10mins = db.get_recent_dp_count(10)
	hashrate = (dps_last_10mins * 2**DP_DIFFICULTY) / (10 * 60)

	# Prepare user list
	users = [
		(userid, username, dpcount, dpcount * (2**DP_DIFFICULTY))
		for userid, username, dpcount in db.get_users_by_dpcount()
	]

	# Prepare recent DPs list
	recent_dps = [
		(dptime, dpstart.hex(), dpend.hex(), username) for username, dpstart, dpend, dptime in db.get_recent_dps(10)
	]

	# Prepare collisions list
	collisions = [
		(timestamp, starta.hex(), startb.hex(), end.hex(), usera, userb)
		for starta, startb, end, usera, userb, timestamp in db.get_collisions()
	]

	# Render template
	template = jinja_env.get_template("dashboard.html")
	html_content = template.render(
		hash_length_bits=HASH_LENGTH_BYTES * 8,
		dp_difficulty=DP_DIFFICULTY,
		db_size=db_size,
		dps_found_formatted=f"{dps_found:,}",
		dps_log=f"{math.log2(dps_found) if dps_found else float('NaN'):0.2f}",
		approx_hashes_formatted=f"{approx_hashes:,}",
		approx_hashes_log=f"{math.log2(approx_hashes) if approx_hashes else float('NaN'):0.2f}",
		breakeven_hashes_formatted=f"{breakeven_hashes:,}",
		breakeven_hashes_log=f"{math.log2(breakeven_hashes):0.2f}",
		progress_percent=f"{approx_hashes/breakeven_hashes*100:0.2f}",
		prob_success=f"{prob_success*100:0.2f}",
		precollisions_found=precollisions_found,
		hashrate_str=hashrate_to_string(hashrate),
		users=users,
		recent_dps=recent_dps,
		collisions=collisions,
		render_time=f"{(time.time()-start_time)*1000:0.2f}",
	)

	return aiohttp.web.Response(text=html_content, content_type="text/html")


async def handle_submit_work(request: aiohttp.web.Request) -> aiohttp.web.Response:
	"""
	{
		"username": "foo",
		"usertoken": "bar",
		"results": [
			"start": "deadbeef",
			"penultimate": "deadbeef"
		]
	}
	"""
	start_time = time.time()
	db = request.app[db_key]

	try:
		body = await request.json()
		username = body["username"]
		usertoken = body["usertoken"]
		results = body["results"]
	except Exception:
		return aiohttp.web.json_response({"status": "bad request"}, status=400)

	userid = db.authenticate_user(username, usertoken)
	if userid is None:
		return aiohttp.web.json_response({"status": "bad username and/or usertoken"}, status=401)

	good_results = []
	num_collisions = 0
	num_good = 0
	for result in results:
		start = bytes.fromhex(result["start"])
		penultimate = bytes.fromhex(result["penultimate"])
		if len(start) != len(penultimate) != HASH_LENGTH_BYTES:
			return aiohttp.web.json_response({"status": "bad hash length"}, status=400)
		end = HASH_FN(penultimate)
		if not IS_DISTINGUISHED(end):
			return aiohttp.web.json_response(
				{"status": f"hash({penultimate.hex()}) is not a distinguished point!"}, status=400
			)

		num_good += 1

		# check for collisions
		collision_result = db.check_collision(end)
		if collision_result is not None:
			num_collisions += 1
			dpid, colliding_start = collision_result
			print("COLLISION!!!", start.hex(), colliding_start.hex(), end.hex())
			# do dp insert now so we can grab its ID
			new_dpid = db.insert_dp(userid, start, end)
			db.insert_collision(dpid, new_dpid)
			# exit()
		else:  # batch up "normal" results for an executemany
			good_results.append((userid, start, end))

	# add new entries
	db.insert_dps_batch(good_results)
	db.increment_user_dpcount(userid, num_good)

	return aiohttp.web.json_response(
		{"status": f"accepted {len(good_results)} results in {(time.time()-start_time)*1000:0.2f}ms"}
	)


def main():
	"""Construct and run the aiohttp application."""
	# Initialize database
	db = BirthdayDB("birthdayparty.db")

	# Set up Jinja2 templates
	template_dir = Path(__file__).parent / "templates"
	jinja_env = jinja2.Environment(
		loader=jinja2.FileSystemLoader(template_dir), autoescape=jinja2.select_autoescape(["html", "xml"])
	)

	# Create app and store dependencies
	app = aiohttp.web.Application()
	app[db_key] = db
	app[jinja_key] = jinja_env

	app.add_routes(
		[
			aiohttp.web.get("/", handle_dashboard),
			aiohttp.web.post("/submit_work", handle_submit_work),
			aiohttp.web.static("/static", "./static/"),
		]
	)
	aiohttp.web.run_app(app)


if __name__ == "__main__":
	main()
