import aiohttp.web
import argparse
import logging
import time
import math
import os
from pathlib import Path

import jinja2
from birthday_party.humanbytes import HumanBytes
from birthday_party.database import BirthdayDB

logger = logging.getLogger(__name__)

# Type-safe app keys
db_key = aiohttp.web.AppKey("db", BirthdayDB)
jinja_key = aiohttp.web.AppKey("jinja_env", jinja2.Environment)
dp_difficulty_bits_key = aiohttp.web.AppKey("dp_difficulty", int)  # in bits
hash_length_bits_key = aiohttp.web.AppKey("hash_length", int)  # in bits


def hashrate_to_string(hashrate: int | float) -> str:
	units = ["", "K", "M", "G", "T", "P", "E"]
	if hashrate <= 0:
		return "0H/s"
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
	dp_difficulty = request.app[dp_difficulty_bits_key]
	hash_length_bits = request.app[hash_length_bits_key]

	# Gather stats
	db_size = HumanBytes.format(os.path.getsize(db.path))
	dps_found = db.get_dp_count()
	approx_hashes = dps_found * 2**dp_difficulty
	breakeven_hashes = round(math.sqrt((2**hash_length_bits * 2) * math.log(2)))
	prob_success = 1 - (math.e ** -(approx_hashes**2 / ((2**hash_length_bits) * 2)))
	precollisions_found = db.get_collision_count()
	dps_last_10mins = db.get_recent_dp_count(10)
	hashrate = (dps_last_10mins * 2**dp_difficulty) / (10 * 60)

	# Prepare user list
	users = [
		(userid, username, dpcount, dpcount * (2**dp_difficulty))
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
		hash_length_bits=hash_length_bits,
		dp_difficulty=dp_difficulty,
		db_size=db_size,
		dps_found_formatted=f"{dps_found:,}",
		dps_log=f"{math.log2(dps_found) if dps_found else float('NaN'):0.2f}",
		approx_hashes_formatted=f"{approx_hashes:,}",
		approx_hashes_log=f"{math.log2(approx_hashes) if approx_hashes else float('NaN'):0.2f}",
		breakeven_hashes_formatted=f"{breakeven_hashes:,}",
		breakeven_hashes_log=f"{math.log2(breakeven_hashes):0.2f}",
		progress_percent=approx_hashes / breakeven_hashes * 100,
		success_percent=prob_success * 100,
		precollisions_found=precollisions_found,
		hashrate_str=hashrate_to_string(hashrate),
		users=users,
		recent_dps=recent_dps,
		collisions=collisions,
		render_time=f"{(time.time() - start_time) * 1000:0.2f}",
	)

	return aiohttp.web.Response(text=html_content, content_type="text/html")


async def handle_submit_work(request: aiohttp.web.Request) -> aiohttp.web.Response:
	"""
	{
		"username": "foo",
		"usertoken": "bar",
		"results": [
			{
				"start": "deadbeef",
				"dp": "deadbeef"
			},
			...
		]
	}
	"""
	start_time = time.time()
	db = request.app[db_key]
	hash_length = request.app[hash_length_bits_key]

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
		dp = bytes.fromhex(result["dp"])
		if len(start) * 8 != hash_length or len(dp) * 8 != hash_length:
			return aiohttp.web.json_response({"status": "bad hash length"}, status=400)

		num_good += 1

		# check for collisions
		collision_result = db.check_collision(dp)
		if collision_result is not None:
			num_collisions += 1
			dpid, colliding_start = collision_result
			logger.info(
				"COLLISION FOUND! start=%s colliding_start=%s dp=%s",
				start.hex(),
				colliding_start.hex(),
				dp.hex(),
			)
			# do dp insert now so we can grab its ID
			new_dpid = db.insert_dp(userid, start, dp)
			db.insert_collision(dpid, new_dpid)
		else:  # batch up "normal" results for an executemany
			good_results.append((userid, start, dp))

	# add new entries
	db.insert_dps_batch(good_results)
	db.increment_user_dpcount(userid, num_good)

	return aiohttp.web.json_response(
		{"status": f"accepted {len(good_results)} results in {(time.time() - start_time) * 1000:0.2f}ms"}
	)


def create_app(
	db: BirthdayDB | None = None,
	jinja_env: jinja2.Environment | None = None,
	dp_difficulty_bits: int = 16,
	hash_length_bits: int = 64,
) -> aiohttp.web.Application:
	"""Create and configure the aiohttp application.

	Args:
		db: Optional BirthdayDB instance (for testing)
		jinja_env: Optional Jinja2 Environment (for testing)
		dp_difficulty_bits: Distinguished point difficulty in bits (default: 16)
		hash_length_bits: Hash length in bits (default: 64)

	Returns:
		Configured aiohttp application
	"""
	# Initialize database if not provided
	if db is None:
		db = BirthdayDB("birthdayparty.db")

	# Set up Jinja2 templates if not provided
	if jinja_env is None:
		template_dir = Path(__file__).parent / "templates"
		jinja_env = jinja2.Environment(
			loader=jinja2.FileSystemLoader(template_dir), autoescape=jinja2.select_autoescape(["html", "xml"])
		)

	# Calculate static directory path
	static_dir = Path(__file__).parent / "static"

	# Create app and store dependencies
	app = aiohttp.web.Application()
	app[db_key] = db
	app[jinja_key] = jinja_env
	app[dp_difficulty_bits_key] = dp_difficulty_bits
	app[hash_length_bits_key] = hash_length_bits

	app.add_routes(
		[
			aiohttp.web.get("/", handle_dashboard),
			aiohttp.web.post("/submit_work", handle_submit_work),
			aiohttp.web.static("/static", static_dir),
		]
	)

	return app


def main() -> None:
	"""Construct and run the aiohttp application."""
	# Configure logging
	logging.basicConfig(
		level=logging.INFO,
		format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
	)

	parser = argparse.ArgumentParser(description="Birthday Party collision search server")
	parser.add_argument("--dp-difficulty", type=int, default=16, help="Distinguished point difficulty in bits")
	parser.add_argument("--hash-length", type=int, default=64, help="Hash length in bits")
	args = parser.parse_args()

	app = create_app(dp_difficulty_bits=args.dp_difficulty, hash_length_bits=args.hash_length)
	aiohttp.web.run_app(app)


if __name__ == "__main__":
	main()
