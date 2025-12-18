import os
import time
import wgpu
import numpy as np
import hashlib
import argparse
import requests
import threading
import queue

from ..ocl_sha256.hash_config import HashConfig, DEFAULT_CONFIG

WORK_SIZE = 0x4000
STEPS_PER_TASK = 0x400
MAX_DPS_PER_CALL = 1024
WORKGROUP_SIZE = 256

DEBUG = 0


def bytes_to_ascii(x: bytes) -> str:
	"""Convert bytes to ASCII representation using nibble->ASCII encoding"""
	return "".join(chr((b >> 4) + ord("A")) + chr((b & 0xF) + ord("A")) for b in x)


def hash_fn(x: bytes, hash_config: HashConfig = DEFAULT_CONFIG) -> bytes:
	"""Hash function matching the WGSL implementation: truncated SHA256 with nibble->ASCII encoding"""
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

		# Request WebGPU adapter and device
		adapter = wgpu.gpu.request_adapter_sync(power_preference="high-performance")
		if adapter is None:
			raise RuntimeError("No WebGPU adapter found!")

		print(f"Using GPU: {adapter.summary}")

		self.device = adapter.request_device_sync()

		# Create buffers
		self.current_states_buf = self.device.create_buffer_with_data(
			data=self.current_states,
			usage=wgpu.BufferUsage.STORAGE | wgpu.BufferUsage.COPY_SRC | wgpu.BufferUsage.COPY_DST,
		)

		self.start_points_buf = self.device.create_buffer_with_data(
			data=self.start_points,
			usage=wgpu.BufferUsage.STORAGE | wgpu.BufferUsage.COPY_SRC | wgpu.BufferUsage.COPY_DST,
		)

		# DP buffer: pre-filled with random data, also used for output
		dp_buffer_width = num_uint32s * 2
		self.dp_buffer = np.random.randint(0, 2**32, size=(MAX_DPS_PER_CALL, dp_buffer_width), dtype=np.uint32)
		# Set the first bit of each entry to ensure start points are not distinguished
		self.dp_buffer[:, 0] |= 0x80000000
		self.dp_count = np.array([0], dtype=np.uint32)

		self.dp_buffer_buf = self.device.create_buffer_with_data(
			data=self.dp_buffer, usage=wgpu.BufferUsage.STORAGE | wgpu.BufferUsage.COPY_SRC | wgpu.BufferUsage.COPY_DST
		)

		self.dp_count_buf = self.device.create_buffer_with_data(
			data=self.dp_count, usage=wgpu.BufferUsage.STORAGE | wgpu.BufferUsage.COPY_SRC | wgpu.BufferUsage.COPY_DST
		)

		# Uniform buffer for masks
		self.masks_buf = self.device.create_buffer(
			size=8,  # 2 x u32
			usage=wgpu.BufferUsage.UNIFORM | wgpu.BufferUsage.COPY_DST,
		)

		# Create staging buffers for readback
		self.dp_count_staging = self.device.create_buffer(
			size=self.dp_count.nbytes, usage=wgpu.BufferUsage.MAP_READ | wgpu.BufferUsage.COPY_DST
		)

		self.dp_buffer_staging = self.device.create_buffer(
			size=self.dp_buffer.nbytes, usage=wgpu.BufferUsage.MAP_READ | wgpu.BufferUsage.COPY_DST
		)

		self.current_states_staging = self.device.create_buffer(
			size=self.current_states.nbytes, usage=wgpu.BufferUsage.MAP_READ | wgpu.BufferUsage.COPY_DST
		)

		self.start_points_staging = self.device.create_buffer(
			size=self.start_points.nbytes, usage=wgpu.BufferUsage.MAP_READ | wgpu.BufferUsage.COPY_DST
		)

		# Load and preprocess shader
		srcdir = os.path.dirname(os.path.realpath(__file__))
		with open(srcdir + "/sha256.wgsl") as f:
			shader_source = f.read()

		# Replace constants (WGSL doesn't have preprocessor)
		hash_total_bytes = hash_config.total_bytes
		hash_num_uint32s = num_uint32s
		hash_ascii_bytes = hash_total_bytes * 2

		shader_source = shader_source.replace("STEPS_PER_TASK", str(steps_per_task) + "u")
		shader_source = shader_source.replace("MAX_DPS_PER_CALL", str(MAX_DPS_PER_CALL) + "u")
		shader_source = shader_source.replace("HASH_PREFIX_BYTES", str(hash_config.prefix_bytes) + "u")
		shader_source = shader_source.replace("HASH_SUFFIX_BYTES", str(hash_config.suffix_bytes) + "u")
		shader_source = shader_source.replace("HASH_TOTAL_BYTES", str(hash_total_bytes) + "u")
		shader_source = shader_source.replace("HASH_NUM_UINT32S", str(hash_num_uint32s) + "u")
		shader_source = shader_source.replace("HASH_ASCII_BYTES", str(hash_ascii_bytes) + "u")
		shader_source = shader_source.replace("WORKGROUP_SIZE", str(WORKGROUP_SIZE))

		# Create shader module
		shader_module = self.device.create_shader_module(code=shader_source)

		# Create compute pipeline
		self.pipeline = self.device.create_compute_pipeline(
			layout="auto", compute={"module": shader_module, "entry_point": "mine"}
		)

		# Create bind group
		self.bind_group = self.device.create_bind_group(
			layout=self.pipeline.get_bind_group_layout(0),
			entries=[
				{"binding": 0, "resource": {"buffer": self.current_states_buf, "size": self.current_states.nbytes}},
				{"binding": 1, "resource": {"buffer": self.start_points_buf, "size": self.start_points.nbytes}},
				{"binding": 2, "resource": {"buffer": self.dp_buffer_buf, "size": self.dp_buffer.nbytes}},
				{"binding": 3, "resource": {"buffer": self.dp_count_buf, "size": self.dp_count.nbytes}},
				{"binding": 4, "resource": {"buffer": self.masks_buf, "size": 8}},
			],
		)

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

		# Update mask uniform buffer
		masks_data = np.array([mask0, mask1], dtype=np.uint32)
		self.device.queue.write_buffer(self.masks_buf, 0, masks_data)

		# Reset DP counter
		self.dp_count[0] = 0
		self.device.queue.write_buffer(self.dp_count_buf, 0, self.dp_count)

		# Create command encoder and run compute pass
		command_encoder = self.device.create_command_encoder()

		compute_pass = command_encoder.begin_compute_pass()
		compute_pass.set_pipeline(self.pipeline)
		compute_pass.set_bind_group(0, self.bind_group)
		compute_pass.dispatch_workgroups(self.work_size // WORKGROUP_SIZE)
		compute_pass.end()

		# Copy results to staging buffers
		command_encoder.copy_buffer_to_buffer(self.dp_count_buf, 0, self.dp_count_staging, 0, self.dp_count.nbytes)

		# Submit commands
		self.device.queue.submit([command_encoder.finish()])

		# Read back DP count
		self.dp_count_staging.map_sync(mode=wgpu.MapMode.READ)
		dp_count_data = np.frombuffer(self.dp_count_staging.read_mapped(), dtype=np.uint32).copy()
		self.dp_count_staging.unmap()

		num_dps = dp_count_data[0]
		if num_dps > MAX_DPS_PER_CALL:
			print("WARNING: MAX_DPS_PER_CALL exceeded! You should probably increase dp_bits.")
			num_dps = MAX_DPS_PER_CALL

		# Read back DPs if any were found
		results = []
		if num_dps > 0:
			# Need to copy dp_buffer to staging and read it
			command_encoder2 = self.device.create_command_encoder()
			command_encoder2.copy_buffer_to_buffer(
				self.dp_buffer_buf, 0, self.dp_buffer_staging, 0, self.dp_buffer.nbytes
			)
			self.device.queue.submit([command_encoder2.finish()])

			self.dp_buffer_staging.map_sync(mode=wgpu.MapMode.READ)
			dp_buffer_data = np.frombuffer(self.dp_buffer_staging.read_mapped(), dtype=np.uint32).copy()
			self.dp_buffer_staging.unmap()

			dp_buffer_data = dp_buffer_data.reshape(self.dp_buffer.shape)

			# Convert DPs to bytes tuples
			num_uint32s = self.hash_config.num_uint32s
			total_bytes = self.hash_config.total_bytes
			for i in range(num_dps):
				start_point = b"".join(int(x).to_bytes(4, "big") for x in dp_buffer_data[i, :num_uint32s])[:total_bytes]
				dp = b"".join(int(x).to_bytes(4, "big") for x in dp_buffer_data[i, num_uint32s : num_uint32s * 2])[
					:total_bytes
				]
				results.append((start_point, dp))

			# Refill only the used dp_buffer entries with fresh random data for next iteration
			dp_buffer_width = num_uint32s * 2
			self.dp_buffer[:num_dps] = np.random.randint(0, 2**32, size=(num_dps, dp_buffer_width), dtype=np.uint32)
			# Set the first bit of each entry to ensure start points are not distinguished
			self.dp_buffer[:num_dps, 0] |= 0x80000000
			self.device.queue.write_buffer(self.dp_buffer_buf, 0, self.dp_buffer)

		# Update local state for next call (need to read back current states and start points)
		command_encoder3 = self.device.create_command_encoder()
		command_encoder3.copy_buffer_to_buffer(
			self.current_states_buf, 0, self.current_states_staging, 0, self.current_states.nbytes
		)
		command_encoder3.copy_buffer_to_buffer(
			self.start_points_buf, 0, self.start_points_staging, 0, self.start_points.nbytes
		)
		self.device.queue.submit([command_encoder3.finish()])

		self.current_states_staging.map_sync(mode=wgpu.MapMode.READ)
		self.current_states = (
			np.frombuffer(self.current_states_staging.read_mapped(), dtype=np.uint32)
			.copy()
			.reshape(self.current_states.shape)
		)
		self.current_states_staging.unmap()

		self.start_points_staging.map_sync(mode=wgpu.MapMode.READ)
		self.start_points = (
			np.frombuffer(self.start_points_staging.read_mapped(), dtype=np.uint32)
			.copy()
			.reshape(self.start_points.shape)
		)
		self.start_points_staging.unmap()

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
						"""Hash function matching the WGSL implementation: truncated SHA256 with nibble->ASCII encoding"""
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
	parser = argparse.ArgumentParser(description="SHA256 WebGPU miner for Birthday Party collision search")
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
