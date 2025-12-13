import os
import time
import pyopencl as cl
import numpy as np
import hashlib

WORK_SIZE = 0x4000
STEPS_PER_TASK = 0x400
MAX_DPS_PER_CALL = 1024  # Maximum DPs to collect per mine() call


class PollardRhoMiner:
	def __init__(self, work_size: int = WORK_SIZE, steps_per_task: int = STEPS_PER_TASK) -> None:
		self.work_size = work_size
		self.steps_per_task = steps_per_task

		# Initialize random states for each thread
		self.current_states = np.random.randint(0, 2**32, size=(work_size, 8), dtype=np.uint32)
		self.start_points = self.current_states.copy()

		ctx = cl.create_some_context()
		self.ctx = ctx
		self.queue = cl.CommandQueue(ctx)

		# Create buffers
		self.current_states_buf = cl.Buffer(ctx, cl.mem_flags.READ_WRITE, size=self.current_states.nbytes)
		self.start_points_buf = cl.Buffer(ctx, cl.mem_flags.READ_WRITE, size=self.start_points.nbytes)

		# DP buffer: pre-filled with random data, also used for output
		self.dp_buffer = np.random.randint(0, 2**32, size=(MAX_DPS_PER_CALL, 16), dtype=np.uint32)
		self.dp_count = np.array([0], dtype=np.uint32)

		self.dp_buffer_buf = cl.Buffer(ctx, cl.mem_flags.READ_WRITE, size=self.dp_buffer.nbytes)
		self.dp_count_buf = cl.Buffer(ctx, cl.mem_flags.READ_WRITE, size=self.dp_count.nbytes)

		# Copy initial states to device
		cl.enqueue_copy(self.queue, self.current_states_buf, self.current_states)
		cl.enqueue_copy(self.queue, self.start_points_buf, self.start_points)
		cl.enqueue_copy(self.queue, self.dp_buffer_buf, self.dp_buffer)

		# Build kernel
		srcdir = os.path.dirname(os.path.realpath(__file__))
		build_options = f"-DSTEPS_PER_TASK={self.steps_per_task}"
		prg = cl.Program(ctx, open(srcdir + "/sha256.cl").read()).build(options=build_options)
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
			np.uint32(MAX_DPS_PER_CALL),
		)

		# Read back results
		cl.enqueue_copy(self.queue, self.dp_count, self.dp_count_buf)
		num_dps = min(self.dp_count[0], MAX_DPS_PER_CALL)

		if num_dps > 0:
			cl.enqueue_copy(self.queue, self.dp_buffer, self.dp_buffer_buf)

		# Update local state for next call
		cl.enqueue_copy(self.queue, self.current_states, self.current_states_buf)
		cl.enqueue_copy(self.queue, self.start_points, self.start_points_buf)

		# Convert DPs to bytes tuples
		results = []
		for i in range(num_dps):
			start_point = b"".join(int(x).to_bytes(4, "big") for x in self.dp_buffer[i, :8])
			dp = b"".join(int(x).to_bytes(4, "big") for x in self.dp_buffer[i, 8:])
			results.append((start_point, dp))

		# Refill dp_buffer with fresh random data for next iteration
		self.dp_buffer = np.random.randint(0, 2**32, size=(MAX_DPS_PER_CALL, 16), dtype=np.uint32)
		cl.enqueue_copy(self.queue, self.dp_buffer_buf, self.dp_buffer)

		duration = time.time() - start
		num_hashes = self.work_size * self.steps_per_task
		rate = num_hashes / duration

		return results, rate


if __name__ == "__main__":
	import time

	def hash_fn(x: bytes):
		"""Hash function matching the OpenCL implementation"""
		return hashlib.sha256(x.hex().encode()).digest()

	def is_distinguished(x: bytes, dp_bits: int):
		"""Check if a hash is a distinguished point"""
		leading_zeroes = len(x) * 8 - int.from_bytes(x, "big").bit_length()
		return leading_zeroes >= dp_bits

	print("Initializing Pollard Rho miner...")
	miner = PollardRhoMiner()

	print("Running continuous mining loop (Ctrl+C to stop)...")
	dp_bits = 24
	total_dps = 0
	total_hashes = 0
	start_time = time.time()

	try:
		while True:
			results, rate = miner.mine(dp_bits=dp_bits)
			print(f"rate: {int(rate):,}H/s")
			total_hashes += miner.work_size * miner.steps_per_task

			if results:
				total_dps += len(results)
				elapsed = time.time() - start_time
				print(
					f"Found {len(results)} DPs! Total: {total_dps} DPs in {elapsed:.1f}s ({total_hashes/elapsed:,.0f} H/s, {total_dps/elapsed:.2f} DP/s)"
				)

				if 1:
					# Verify first DP
					start_point, dp = results[0]
					print(f"  Start: {start_point.hex()}")
					print(f"  DP:    {dp.hex()}")

					# Trace the chain to verify
					point = start_point
					iterations = 0
					while point != dp and iterations < 1000000:
						point = hash_fn(point)
						iterations += 1

					if point == dp:
						print(f"  ✓ Verified! Chain length: {iterations}")
						if is_distinguished(dp, dp_bits):
							print(f"  ✓ DP has {dp_bits}+ leading zero bits")
						else:
							print(f"  ✗ ERROR: DP does not have {dp_bits} leading zero bits!")
					else:
						print(f"  ✗ ERROR: Could not verify chain (gave up after {iterations} iterations)")

			break  # just for testing

	except KeyboardInterrupt:
		elapsed = time.time() - start_time
		print(f"\nStopped. Total: {total_dps} DPs, {total_hashes:,} hashes in {elapsed:.1f}s")
		print(f"Average: {total_hashes/elapsed:,.0f} H/s, {total_dps/elapsed:.2f} DP/s")
