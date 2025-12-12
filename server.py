from aiohttp import web
import hashlib
import html
import time
import math
import os

from humanbytes import HumanBytes
from database import BirthdayDB

DB_PATH = "birthdayparty.db"
db = BirthdayDB(DB_PATH)

# collision parameters
DP_DIFFICULTY = 16 # bits

def HASH_FN(x):
	return hashlib.md5(x.hex().encode()).digest()[:8] # half-md5

def IS_DISTINGUISHED(x):
	leading_zeroes = len(x) * 8 - int.from_bytes(x, "big").bit_length()
	return leading_zeroes >= DP_DIFFICULTY

HASH_LENGTH = len(HASH_FN(b"")) # bytes


def render_html_table(headings, rows, escape=True):
	escapefunc = html.escape if escape else lambda x: x
	res = "<table>"
	res += "<tr>" + "".join(["<th>"+escapefunc(str(h))+"</th>" for h in headings]) + "</tr>"
	for row in rows:
		res += "<tr>" + "".join(["<td>"+escapefunc(str(r))+"</td>" for r in row]) + "</tr>"
	res += "</table>"
	return res


def hashrate_to_string(hashrate): # hashrate in hashes per second
	units = ["","K","M","G","T","P","E"]
	if hashrate > 1:
		unit_idx = max(round(math.log10(hashrate)/3 - 1.0), 0)
	else:
		unit_idx = 0
	scaled_hashrate = hashrate / 10**(unit_idx*3)
	return f"{round(scaled_hashrate):,}{units[unit_idx]}H/s"


async def handle_dashboard(request):
	start_time = time.time()
	res = "<!DOCTYPE html><html>"
	res += '<head><meta charset="UTF-8"><link rel="stylesheet" href="/static/style.css"></head>'
	res += "<body>"
	res += "<h1>Birthday Party 🥳</h1>"
	res += '<p>A distributed search for hash collisions, leveraging the <a href="https://en.wikipedia.org/wiki/Birthday_problem">Birthday Paradox</a>, using <a href="https://www.cs.csi.cuny.edu/~zhangx/papers/P_2018_LISAT_Weber_Zhang.pdf">"Parallel Hash Collision Search by Rho Method with Distinguished Points"</a> (Brian Weber and Xiaowen Zhang, 2018).</p>'
	res += "<h2>Config</h2>"
	res += f"<p><strong>Target collision length:</strong> {HASH_LENGTH*8} bits</p>"
	res += f"<p><strong>Distinguished Point difficulty:</strong> {DP_DIFFICULTY} bits</p>"

	res += "<h2>Stats</h2>"
	db_size = os.path.getsize(DB_PATH)
	res += f"<p><strong>Database size:</strong> {HumanBytes.format(db_size)}</p>"
	dps_found = db.get_dp_count()
	res += f"<p><strong>Distinguished Points found:</strong> {dps_found:,} (2<sup>{math.log2(dps_found) if dps_found else float('NaN'):0.2f}</sup>)</p>"
	approx_hashes = dps_found * 2**DP_DIFFICULTY
	res += f"<p><strong>Approx. total hashes computed:</strong> {approx_hashes:,} (2<sup>{math.log2(approx_hashes) if approx_hashes else float('NaN'):0.2f}</sup>)</p>"
	breakeven_hashes = round(math.sqrt((2**(HASH_LENGTH*8) * 2) * math.log(2)))
	res += f"<p><strong>Total hashes required for 50% success chance:</strong> {breakeven_hashes:,} (2<sup>{math.log2(breakeven_hashes):0.2f}</sup>) - We're {approx_hashes/breakeven_hashes*100:0.2f}% of the way there!</p>"
	prob_success = 1-(math.e**-(approx_hashes**2/((2**(HASH_LENGTH*8))*2)))
	res += f"<p><strong>Probability of having found at least one collision by now:</strong> {prob_success*100:0.2f}% (Note: this percentage will climb non-linearly!)</p>"
	precollisions_found = db.get_collision_count()
	res += f"<p><strong>Pre-collisions found:</strong> {precollisions_found}</p>"
	dps_last_10mins = db.get_recent_dp_count(10)
	hashrate = (dps_last_10mins * 2**DP_DIFFICULTY) / (10*60)
	res += f"<p><strong>Network hashrate (10 min avg):</strong> {hashrate_to_string(hashrate)}</p>"

	res += "<h2>Users</h2>"
	userlist = []
	for userid, username, dpcount in db.get_users_by_dpcount():
		userlist.append((userid, username, dpcount, dpcount*(2**DP_DIFFICULTY)))

	res += render_html_table(
		["id", "username", "dp count", "est. hash count"],
		userlist
	)

	res += "<h2>Recent Distinguished Points</h2>"
	dplist = []
	for username, dpstart, dpend, dptime in db.get_recent_dps(10):
		dplist.append((dptime, "<code>"+dpstart.hex()+"</code>", "<code>"+dpend.hex()+"</code>", html.escape(username)))
	
	res += render_html_table(
		["timestamp (UTC+0)", "start hash", "end hash", "username"],
		dplist,
		escape=False
	)

	res += "<h2>Pre-Collisions</h2>"
	coll = []
	for starta, startb, end, usera, userb, timestamp in db.get_collisions():
		coll.append((
			timestamp,
			"<code>"+starta.hex()+"</code>",
			"<code>"+startb.hex()+"</code>",
			"<code>"+end.hex()+"</code>",
			html.escape(usera),
			html.escape(userb),
		))
	res += render_html_table(
		["timestamp (UTC+0)", "start hash A", "start hash B", "end hash", "user A", "user B"],
		coll,
		escape=False
	)

	res += f"<p>Page rendered in {(time.time()-start_time)*1000:0.2f}ms</p>"
	res += "</body></html>"
	return web.Response(text=res, content_type="text/html")

async def handle_submit_work(request):
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

	try:
		body = await request.json()
		username = body["username"]
		usertoken = body["usertoken"]
		results = body["results"]
	except:
		return web.json_response({"status": "bad request"}, status=400)
	
	userid = db.authenticate_user(username, usertoken)
	if userid is None:
		return web.json_response({"status": "bad username and/or usertoken"}, status=401)
	
	good_results = []
	num_collisions = 0
	num_good = 0
	for result in results:
		start = bytes.fromhex(result["start"])
		penultimate = bytes.fromhex(result["penultimate"])
		if len(start) != len(penultimate) != HASH_LENGTH:
			return web.json_response({"status": "bad hash length"}, status=400)
		end = HASH_FN(penultimate)
		if not IS_DISTINGUISHED(end):
			return web.json_response({
				"status": f"hash({penultimate.hex()}) is not a distinguished point!"
			}, status=400)
		
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
			#exit()
		else: # batch up "normal" results for an executemany
			good_results.append((userid, start, end))

	# add new entries
	db.insert_dps_batch(good_results)
	db.increment_user_dpcount(userid, num_good)
	db.commit()


	return web.json_response({"status": f"accepted {len(good_results)} results in {(time.time()-start_time)*1000:0.2f}ms"})

app = web.Application()
app.add_routes([
	web.get('/', handle_dashboard),
	web.post('/submit_work', handle_submit_work),
	web.static('/static', "./static/"), # TODO: let the reverse proxy handle this?
])

if __name__ == '__main__':
	web.run_app(app)
