import os
import time
import pyopencl as cl
import numpy as np
import hashlib
import argparse
import requests
import threading
import queue

from .hash_config import HashConfig, DEFAULT_CONFIG

WORK_SIZE = 0x4000
STEPS_PER_TASK = 0x400
MAX_DPS_PER_CALL = 1024  # Maximum DPs to collect per mine() call

DEBUG = 0


def bytes_to_ascii(x: bytes) -> str:
	"""Convert bytes to ASCII representation using nibble->ASCII encoding"""
	return "".join(chr((b >> 4) + ord("A")) + chr((b & 0xF) + ord("A")) for b in x)


def hash_fn(x: bytes, hash_config: HashConfig = DEFAULT_CONFIG) -> bytes:
	"""Hash function matching the OpenCL implementation: truncated SHA256 with nibble->ASCII encoding"""
	ascii_repr = bytes_to_ascii(x)
	full_hash = hashlib.sha256(ascii_repr.encode()).digest()
	return hash_config.truncate_hash(full_hash)


def is_distinguished(x: bytes, dp_bits: int) -> bool:
	"""Check if a hash is a distinguished point"""
	leading_zeroes = len(x) * 8 - int.from_bytes(x, "big").bit_length()
	return leading_zeroes >= dp_bits


class PollardRhoMiner:
	def __init__(
		self, work_size: int = WORK_SIZE, steps_per_task: int = STEPS_PER_TASK, hash_config: HashConfig = DEFAULT_CONFIG
	) -> None:
		self.work_size = work_size
		self.steps_per_task = steps_per_task
		self.hash_config = hash_config

		# Initialize random states for each thread
		num_uint32s = hash_config.num_uint32s
		self.current_states = np.random.randint(0, 2**32, size=(work_size, num_uint32s), dtype=np.uint32)
		self.start_points = self.current_states.copy()

		ctx = cl.create_some_context()
		self.ctx = ctx
		self.queue = cl.CommandQueue(ctx)

		# Create buffers
		self.current_states_buf = cl.Buffer(ctx, cl.mem_flags.READ_WRITE, size=self.current_states.nbytes)
		self.start_points_buf = cl.Buffer(ctx, cl.mem_flags.READ_WRITE, size=self.start_points.nbytes)

		# DP buffer: pre-filled with random data, also used for output (num_uint32s*2 per entry: start + dp)
		dp_buffer_width = num_uint32s * 2
		self.dp_buffer = np.random.randint(0, 2**32, size=(MAX_DPS_PER_CALL, dp_buffer_width), dtype=np.uint32)
		# Set the first bit of each entry to ensure start points are not distinguished
		self.dp_buffer[:, 0] |= 0x80000000
		self.dp_count = np.array([0], dtype=np.uint32)

		self.dp_buffer_buf = cl.Buffer(ctx, cl.mem_flags.READ_WRITE, size=self.dp_buffer.nbytes)
		self.dp_count_buf = cl.Buffer(ctx, cl.mem_flags.READ_WRITE, size=self.dp_count.nbytes)

		# Copy initial states to device
		cl.enqueue_copy(self.queue, self.current_states_buf, self.current_states)
		cl.enqueue_copy(self.queue, self.start_points_buf, self.start_points)
		cl.enqueue_copy(self.queue, self.dp_buffer_buf, self.dp_buffer)

		# Build kernel
		srcdir = os.path.dirname(os.path.realpath(__file__))
		build_options = (
			f"-DSTEPS_PER_TASK={self.steps_per_task} "
			f"-DMAX_DPS_PER_CALL={MAX_DPS_PER_CALL} "
			f"{hash_config.get_opencl_defines()}"
		)
		with open(srcdir + "/sha256.cl") as f:
			kernel_src = f.read()
		prg = cl.Program(ctx, kernel_src).build(options=build_options)
		self.kernel = cl.Kernel(prg, "mine")

	def mine(self, dp_bits: int = 16) -> tuple[list[tuple[bytes, bytes]], float]:
		"""
		Advance all threads by STEPS_PER_TASK iterations.
		Returns a list of (start_point, dp) tuples for any DPs found.

		Args:
			dp_bits: Number of leading zero bits required for a distinguished point
		"""
		start = time.time()

		# Compute masks for distinguished point check
		if dp_bits <= 32:
			mask0 = (0xFFFFFFFF << (32 - dp_bits)) & 0xFFFFFFFF
			mask1 = 0
		else:
			mask0 = 0xFFFFFFFF
			mask1 = (0xFFFFFFFF << (64 - dp_bits)) & 0xFFFFFFFF

		# Reset DP counter
		self.dp_count[0] = 0
		cl.enqueue_copy(self.queue, self.dp_count_buf, self.dp_count)

		# Run kernel
		self.kernel(
			self.queue,
			(self.work_size,),
			None,
			self.current_states_buf,
			self.start_points_buf,
			self.dp_buffer_buf,
			self.dp_count_buf,
			np.uint32(mask0),
			np.uint32(mask1),
		)

		# Read back results
		cl.enqueue_copy(self.queue, self.dp_count, self.dp_count_buf)
		num_dps = self.dp_count[0]
		if num_dps > MAX_DPS_PER_CALL:
			print("WARNING: MAX_DPS_PER_CALL exceeded! You should probably increase dp_bits.")
			num_dps = MAX_DPS_PER_CALL

		if num_dps > 0:
			cl.enqueue_copy(self.queue, self.dp_buffer, self.dp_buffer_buf)

		# Update local state for next call
		cl.enqueue_copy(self.queue, self.current_states, self.current_states_buf)
		cl.enqueue_copy(self.queue, self.start_points, self.start_points_buf)

		# Convert DPs to bytes tuples
		results = []
		num_uint32s = self.hash_config.num_uint32s
		total_bytes = self.hash_config.total_bytes
		for i in range(num_dps):
			# Convert uint32s to bytes, then truncate to exact byte count
			start_point = b"".join(int(x).to_bytes(4, "big") for x in self.dp_buffer[i, :num_uint32s])[:total_bytes]
			dp = b"".join(int(x).to_bytes(4, "big") for x in self.dp_buffer[i, num_uint32s : num_uint32s * 2])[
				:total_bytes
			]
			results.append((start_point, dp))

		# Refill only the used dp_buffer entries with fresh random data for next iteration
		if num_dps > 0:
			dp_buffer_width = num_uint32s * 2
			self.dp_buffer[:num_dps] = np.random.randint(0, 2**32, size=(num_dps, dp_buffer_width), dtype=np.uint32)
			# Set the first bit of each entry to ensure start points are not distinguished
			self.dp_buffer[:num_dps, 0] |= 0x80000000
			cl.enqueue_copy(self.queue, self.dp_buffer_buf, self.dp_buffer)

		duration = time.time() - start
		num_hashes = self.work_size * self.steps_per_task
		rate = num_hashes / duration

		return results, rate


def submission_worker(
	server_url: str, username: str, usertoken: str, dp_queue: queue.Queue, stop_event: threading.Event
):
	"""Background thread that drains and submits DPs every second."""
	session = requests.Session()

	def submit_work(results):
		try:
			r = session.post(
				server_url.rstrip("/") + "/submit_work",
				json={"username": username, "usertoken": usertoken, "results": results},
			)
			if not r.ok:
				print(f"SERVER ERROR: {r.content}")
			else:
				print(f"Server says: {r.json()['status']}")
		except Exception as e:
			print(f"Submission error: {e}")

	while not stop_event.is_set():
		time.sleep(1.0)

		# Drain the queue
		pending_results = []
		try:
			while True:
				pending_results.append(dp_queue.get_nowait())
		except queue.Empty:
			pass

		# Submit if we have any DPs
		if pending_results:
			print(f"Submitting {len(pending_results)} DPs...")
			submit_work(pending_results)


def mine(
	server_url: str | None = None,
	username: str | None = None,
	usertoken: str | None = None,
	dp_bits: int = 16,
	dry_run: bool = False,
	hash_config: HashConfig = DEFAULT_CONFIG,
):
	"""Run the mining loop, finding distinguished points and reporting them to the server."""
	print(f"Initializing Pollard Rho miner with {hash_config}...")
	miner = PollardRhoMiner(hash_config=hash_config)

	# Create queue and background submission thread (only if not dry run)
	dp_queue = None
	stop_event = None
	submission_thread = None
	if not dry_run:
		dp_queue = queue.Queue()
		stop_event = threading.Event()
		submission_thread = threading.Thread(
			target=submission_worker, args=(server_url, username, usertoken, dp_queue, stop_event), daemon=True
		)
		submission_thread.start()

	mode_str = "DRY RUN" if dry_run else f"submitting to {server_url}"
	print(f"Running continuous mining loop with dp_bits={dp_bits} ({mode_str}) (Ctrl+C to stop)...")
	total_dps = 0
	total_hashes = 0
	start_time = time.time()

	try:
		while True:
			results, _ = miner.mine(dp_bits=dp_bits)
			total_hashes += miner.work_size * miner.steps_per_task

			if results:
				total_dps += len(results)
				elapsed = time.time() - start_time
				print(
					f"Found {len(results)} DPs! Total: {total_dps} DPs in {elapsed:.1f}s ({total_hashes/elapsed:,.0f} H/s, {total_dps/elapsed:.2f} DP/s)"
				)

				for start_point, dp in results:
					msg = {
						"start": start_point.hex(),
						"dp": dp.hex(),
					}
					if dp_queue is None:
						print(msg)  # dry run mode
					else:
						dp_queue.put(msg)  # queue for submission to server

				if DEBUG:
					# Hash function for verification (uses the miner's hash_config)
					def hash_fn_local(x: bytes):
						"""Hash function matching the OpenCL implementation: truncated SHA256 with nibble->ASCII encoding"""
						ascii_repr = "".join(chr((b >> 4) + ord("A")) + chr((b & 0xF) + ord("A")) for b in x)
						full_hash = hashlib.sha256(ascii_repr.encode()).digest()
						return miner.hash_config.truncate_hash(full_hash)

					def is_distinguished(x: bytes, dp_bits: int):
						"""Check if a hash is a distinguished point"""
						leading_zeroes = len(x) * 8 - int.from_bytes(x, "big").bit_length()
						return leading_zeroes >= dp_bits

					# Verify first DP
					start_point, dp = results[0]
					print(f"  Start: {start_point.hex()}")
					print(f"  DP:    {dp.hex()}")

					# Trace the chain to verify
					point = start_point
					iterations = 0
					while point != dp and iterations < 1000000:
						point = hash_fn_local(point)
						iterations += 1

					if point == dp:
						print(f"  ✓ Verified! Chain length: {iterations}")
						if is_distinguished(dp, dp_bits):
							print(f"  ✓ DP has {dp_bits}+ leading zero bits")
						else:
							print(f"  ✗ ERROR: DP does not have {dp_bits} leading zero bits!")
					else:
						print(f"  ✗ ERROR: Could not verify chain (gave up after {iterations} iterations)")

	except KeyboardInterrupt:
		elapsed = time.time() - start_time
		print(f"\nStopping... Total: {total_dps} DPs, {total_hashes:,} hashes in {elapsed:.1f}s")
		print(f"Average: {total_hashes/elapsed:,.0f} H/s, {total_dps/elapsed:.2f} DP/s")

		if stop_event is not None:
			stop_event.set()
		if submission_thread is not None:
			submission_thread.join(timeout=2.0)

		print("Shutdown complete.")


def main():
	parser = argparse.ArgumentParser(description="SHA256 OpenCL miner for Birthday Party collision search")
	parser.add_argument("username", nargs="?", help="Username for authentication (not needed for --dry-run)")
	parser.add_argument("usertoken", nargs="?", help="User token for authentication (not needed for --dry-run)")
	parser.add_argument("--server", default="http://localhost:8080/", help="Server URL")
	parser.add_argument(
		"--dp-bits", type=int, default=16, help="Number of leading zero bits for distinguished points (default: 16)"
	)
	parser.add_argument(
		"--dry-run", action="store_true", help="Run without submitting to server (no username/token needed)"
	)
	parser.add_argument(
		"--hash-prefix-bytes",
		type=int,
		default=8,
		help="Number of prefix bytes from SHA256 hash (0-27, default: 8). Total with suffix must be 5-27 bytes.",
	)
	parser.add_argument(
		"--hash-suffix-bytes",
		type=int,
		default=0,
		help="Number of suffix bytes from SHA256 hash (0-27, default: 0). Total with prefix must be 5-27 bytes (5-26 if both used).",
	)
	args = parser.parse_args()

	# Validate required arguments when not in dry run mode
	if not args.dry_run and (not args.username or not args.usertoken):
		parser.error("username and usertoken are required unless --dry-run is specified")

	hash_config = HashConfig(prefix_bytes=args.hash_prefix_bytes, suffix_bytes=args.hash_suffix_bytes)
	mine(args.server, args.username, args.usertoken, args.dp_bits, dry_run=args.dry_run, hash_config=hash_config)


if __name__ == "__main__":
	main()
