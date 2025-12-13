// sha256 impl is a collab between deepseek (initial impl) and claude (perf optimizations)

// STEPS_PER_TASK is passed via compile options (-DSTEPS_PER_TASK=...)
#ifndef STEPS_PER_TASK
#define STEPS_PER_TASK 0x100  // default fallback
#endif

typedef uint uint32_t;
typedef ulong uint64_t;

// SHA-256 constants
constant uint K[64] = {
	0x428a2f98, 0x71374491, 0xb5c0fbcf, 0xe9b5dba5,
	0x3956c25b, 0x59f111f1, 0x923f82a4, 0xab1c5ed5,
	0xd807aa98, 0x12835b01, 0x243185be, 0x550c7dc3,
	0x72be5d74, 0x80deb1fe, 0x9bdc06a7, 0xc19bf174,
	0xe49b69c1, 0xefbe4786, 0x0fc19dc6, 0x240ca1cc,
	0x2de92c6f, 0x4a7484aa, 0x5cb0a9dc, 0x76f988da,
	0x983e5152, 0xa831c66d, 0xb00327c8, 0xbf597fc7,
	0xc6e00bf3, 0xd5a79147, 0x06ca6351, 0x14292967,
	0x27b70a85, 0x2e1b2138, 0x4d2c6dfc, 0x53380d13,
	0x650a7354, 0x766a0abb, 0x81c2c92e, 0x92722c85,
	0xa2bfe8a1, 0xa81a664b, 0xc24b8b70, 0xc76c51a3,
	0xd192e819, 0xd6990624, 0xf40e3585, 0x106aa070,
	0x19a4c116, 0x1e376c08, 0x2748774c, 0x34b0bcb5,
	0x391c0cb3, 0x4ed8aa4a, 0x5b9cca4f, 0x682e6ff3,
	0x748f82ee, 0x78a5636f, 0x84c87814, 0x8cc70208,
	0x90befffa, 0xa4506ceb, 0xbef9a3f7, 0xc67178f2
};

// SHA-256 helper functions
#define ROTR(x, n) rotate(x, (uint)(32 - n))
#define SHR(x, n) ((x) >> n)

#define CH(x, y, z) (z ^ (x & (y ^ z)))
#define MAJ(x, y, z) ((x & y) | (z & (x | y)))

#define SIG0(x) (ROTR(x, 2) ^ ROTR(x, 13) ^ ROTR(x, 22))
#define SIG1(x) (ROTR(x, 6) ^ ROTR(x, 11) ^ ROTR(x, 25))
#define SIG2(x) (ROTR(x, 7) ^ ROTR(x, 18) ^ SHR(x, 3))
#define SIG3(x) (ROTR(x, 17) ^ ROTR(x, 19) ^ SHR(x, 10))

void sha256_update(uint32_t state_out[8], uint32_t state_in[8], uint32_t block[16]) {
	uint a = state_in[0];
	uint b = state_in[1];
	uint c = state_in[2];
	uint d = state_in[3];
	uint e = state_in[4];
	uint f = state_in[5];
	uint g = state_in[6];
	uint h = state_in[7];

	// First 16 rounds - use block directly
	#pragma unroll
	for (int i = 0; i < 16; i++) {
		uint t1 = h + SIG1(e) + CH(e, f, g) + K[i] + block[i];
		uint t2 = SIG0(a) + MAJ(a, b, c);

		h = g;
		g = f;
		f = e;
		e = d + t1;
		d = c;
		c = b;
		b = a;
		a = t1 + t2;
	}

	// Remaining 48 rounds - compute extended message schedule in-place
	#pragma unroll
	for (int i = 16; i < 64; i++) {
		block[i & 15] = SIG3(block[(i - 2) & 15]) + block[(i - 7) & 15] +
		                SIG2(block[(i - 15) & 15]) + block[(i - 16) & 15];

		uint t1 = h + SIG1(e) + CH(e, f, g) + K[i] + block[i & 15];
		uint t2 = SIG0(a) + MAJ(a, b, c);

		h = g;
		g = f;
		f = e;
		e = d + t1;
		d = c;
		c = b;
		b = a;
		a = t1 + t2;
	}

	// Write final state directly
	state_out[0] = state_in[0] + a;
	state_out[1] = state_in[1] + b;
	state_out[2] = state_in[2] + c;
	state_out[3] = state_in[3] + d;
	state_out[4] = state_in[4] + e;
	state_out[5] = state_in[5] + f;
	state_out[6] = state_in[6] + g;
	state_out[7] = state_in[7] + h;
}

// Convert 8-byte truncated hash (2 uint32s) to 16-byte ASCII representation
void hash_to_ascii_message(uint32_t hash[2], uint32_t msg[16]) {
	// Convert each nibble to ASCII by adding 'A' (0x41)
	// Using word-level bit operations to avoid byte indexing

	// Each uint32 input produces 2 uint32s of output (8 nibbles -> 8 ASCII bytes)
	uint32_t val0 = hash[0];
	msg[0] = ((((val0 >> 28) & 0xF) + 'A') << 24) |
	         ((((val0 >> 24) & 0xF) + 'A') << 16) |
	         ((((val0 >> 20) & 0xF) + 'A') << 8) |
	         (((val0 >> 16) & 0xF) + 'A');
	msg[1] = ((((val0 >> 12) & 0xF) + 'A') << 24) |
	         ((((val0 >> 8) & 0xF) + 'A') << 16) |
	         ((((val0 >> 4) & 0xF) + 'A') << 8) |
	         ((val0 & 0xF) + 'A');

	uint32_t val1 = hash[1];
	msg[2] = ((((val1 >> 28) & 0xF) + 'A') << 24) |
	         ((((val1 >> 24) & 0xF) + 'A') << 16) |
	         ((((val1 >> 20) & 0xF) + 'A') << 8) |
	         (((val1 >> 16) & 0xF) + 'A');
	msg[3] = ((((val1 >> 12) & 0xF) + 'A') << 24) |
	         ((((val1 >> 8) & 0xF) + 'A') << 16) |
	         ((((val1 >> 4) & 0xF) + 'A') << 8) |
	         ((val1 & 0xF) + 'A');

	// Padding: 0x80 followed by zeros, then length (16 bytes = 128 bits)
	msg[4] = 0x80000000;
	for (int i = 5; i < 14; i++) {
		msg[i] = 0;
	}
	msg[14] = 0;    // Length high word
	msg[15] = 128;  // Length low word (in bits)
}

// SHA-256 constants for initial state
constant uint32_t INITIAL_H[8] = {
	0x6a09e667, 0xbb67ae85, 0x3c6ef372, 0xa54ff53a,
	0x510e527f, 0x9b05688c, 0x1f83d9ab, 0x5be0cd19
};

__kernel void mine(
	__global uint32_t* current_states,    // [work_size][2] - current state for each thread (truncated to 8 bytes)
	__global uint32_t* start_points,      // [work_size][2] - start point for each thread (truncated to 8 bytes)
	__global uint32_t* dp_buffer,         // [max_dps][4] - pre-filled with random data, then output: (start, dp) pairs
	__global volatile uint* dp_count,     // number of DPs found
	const uint32_t mask0,                 // mask for first word of hash
	const uint32_t mask1,                 // mask for second word of hash
	const uint max_dps                    // maximum DPs to collect
)
{
	uint gid = get_global_id(0);
	uint thread_offset = gid * 2;

	// Load current state and start point for this thread
	uint32_t state[2];
	uint32_t start[2];
	for (int i = 0; i < 2; i++) {
		state[i] = current_states[thread_offset + i];
		start[i] = start_points[thread_offset + i];
	}

	// Perform STEPS_PER_TASK iterations
	for (uint step = 0; step < STEPS_PER_TASK; step++) {
		// Convert 8-byte state to 16-byte ASCII message (with padding already included)
		uint32_t msg[16];
		hash_to_ascii_message(state, msg);

		// Compute SHA256(hex(state)) - message fits in single block with padding
		uint32_t initial_h_local[8];
		uint32_t hash_full[8];

		// Copy initial hash state
		for (int i = 0; i < 8; i++) {
			initial_h_local[i] = INITIAL_H[i];
		}

		// Compute full SHA256
		sha256_update(hash_full, initial_h_local, msg);

		// Truncate to first 8 bytes (2 words)
		state[0] = hash_full[0];
		state[1] = hash_full[1];

		// Check if this is a distinguished point
		if (((state[0] & mask0) == 0) && ((state[1] & mask1) == 0)) {
			// Found a DP! Store it if there's room
			uint dp_idx = atomic_inc(dp_count);
			if (dp_idx < max_dps) {
				uint buf_offset = dp_idx * 4;

				// Read new random start from dp_buffer (before overwriting)
				uint32_t new_start[2];
				for (int i = 0; i < 2; i++) {
					new_start[i] = dp_buffer[buf_offset + i];
				}

				// Store start point
				for (int i = 0; i < 2; i++) {
					dp_buffer[buf_offset + i] = start[i];
				}
				// Store distinguished point
				for (int i = 0; i < 2; i++) {
					dp_buffer[buf_offset + 2 + i] = state[i];
				}

				// Use the random data we read as the new start
				for (int i = 0; i < 2; i++) {
					start[i] = new_start[i];
					state[i] = new_start[i];
				}
			}
		}
	}

	// Save current state and start point for next invocation
	for (int i = 0; i < 2; i++) {
		current_states[thread_offset + i] = state[i];
		start_points[thread_offset + i] = start[i];
	}
}
