// sha256 impl is a collab between deepseek (initial impl) and claude (perf optimizations)

// STEPS_PER_TASK, MAX_DPS_PER_CALL, and HASH_PREFIX_BYTES are passed via compile options
#ifndef STEPS_PER_TASK
#define STEPS_PER_TASK 0x100  // default fallback
#endif

#ifndef MAX_DPS_PER_CALL
#define MAX_DPS_PER_CALL 1024  // default fallback
#endif

#ifndef HASH_PREFIX_BYTES
#define HASH_PREFIX_BYTES 8  // default: 8-byte prefix
#endif

#ifndef HASH_SUFFIX_BYTES
#define HASH_SUFFIX_BYTES 0  // default: no suffix
#endif

// Derived constants for hash truncation
#define HASH_TOTAL_BYTES (HASH_PREFIX_BYTES + HASH_SUFFIX_BYTES)
#define HASH_NUM_UINT32S ((HASH_TOTAL_BYTES + 3) / 4)  // round up to whole words
#define HASH_ASCII_BYTES (HASH_TOTAL_BYTES * 2)  // each byte becomes 2 ASCII chars

typedef uchar uint8_t;
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

// Extract truncated hash (prefix + suffix) from full SHA256
void truncate_hash(uint32_t hash_full[8], uint32_t hash_trunc[HASH_NUM_UINT32S]) {
	if (HASH_SUFFIX_BYTES == 0) {
		// Prefix-only (simple case) - just copy first HASH_NUM_UINT32S words
		for (int i = 0; i < HASH_NUM_UINT32S; i++) {
			hash_trunc[i] = hash_full[i];
		}
	} else {
		// Prefix + suffix - need to extract non-contiguous bytes
		// We'll pack them into uint32s, handling partial words carefully

		int trunc_idx = 0;
		uint32_t accum = 0;
		int accum_bytes = 0;

		// Extract prefix bytes
		for (int byte_offset = 0; byte_offset < HASH_PREFIX_BYTES; byte_offset++) {
			int word_idx = byte_offset / 4;
			int byte_in_word = byte_offset % 4;
			uint8_t byte_val = (hash_full[word_idx] >> (24 - byte_in_word * 8)) & 0xFF;

			accum = (accum << 8) | byte_val;
			accum_bytes++;

			if (accum_bytes == 4) {
				hash_trunc[trunc_idx++] = accum;
				accum = 0;
				accum_bytes = 0;
			}
		}

		// Extract suffix bytes
		for (int byte_offset = 0; byte_offset < HASH_SUFFIX_BYTES; byte_offset++) {
			int abs_byte_offset = 32 - HASH_SUFFIX_BYTES + byte_offset;
			int word_idx = abs_byte_offset / 4;
			int byte_in_word = abs_byte_offset % 4;
			uint8_t byte_val = (hash_full[word_idx] >> (24 - byte_in_word * 8)) & 0xFF;

			accum = (accum << 8) | byte_val;
			accum_bytes++;

			if (accum_bytes == 4) {
				hash_trunc[trunc_idx++] = accum;
				accum = 0;
				accum_bytes = 0;
			}
		}

		// Flush any remaining bytes
		if (accum_bytes > 0) {
			accum <<= (4 - accum_bytes) * 8;  // Left-align remaining bytes
			hash_trunc[trunc_idx++] = accum;
		}
	}
}

// Convert truncated hash to ASCII representation with SHA256 padding
// Generic version that works for any HASH_TOTAL_BYTES (1-32)
void hash_to_ascii_message(uint32_t hash[HASH_NUM_UINT32S], uint32_t msg[16]) {
	// Convert each nibble to ASCII by adding 'A' (0x41)
	// Each byte becomes 2 ASCII characters (high nibble, low nibble)
	// Process in 32-bit chunks for performance

	int msg_idx = 0;

	// Process complete 4-byte words
	// Each 4-byte word produces 8 ASCII bytes (2 output words)
	const int complete_words = HASH_TOTAL_BYTES / 4;

	#pragma unroll
	for (int i = 0; i < complete_words; i++) {
		uint32_t val = hash[i];

		// Convert high 2 bytes to first output word (4 ASCII chars)
		msg[msg_idx++] = ((((val >> 28) & 0xF) + 'A') << 24) |
		                 ((((val >> 24) & 0xF) + 'A') << 16) |
		                 ((((val >> 20) & 0xF) + 'A') << 8) |
		                 (((val >> 16) & 0xF) + 'A');

		// Convert low 2 bytes to second output word (4 ASCII chars)
		msg[msg_idx++] = ((((val >> 12) & 0xF) + 'A') << 24) |
		                 ((((val >> 8) & 0xF) + 'A') << 16) |
		                 ((((val >> 4) & 0xF) + 'A') << 8) |
		                 ((val & 0xF) + 'A');
	}

	// Handle partial word (1, 2, or 3 remaining bytes)
	const int remainder_bytes = HASH_TOTAL_BYTES % 4;
	if (remainder_bytes > 0) {
		uint32_t val = hash[complete_words];

		// Process remaining bytes one at a time
		uint32_t ascii_accum = 0;
		int ascii_bytes = 0;

		for (int byte_idx = 0; byte_idx < remainder_bytes; byte_idx++) {
			// Extract byte (big-endian: shift from MSB)
			uint8_t b = (val >> (24 - byte_idx * 8)) & 0xFF;

			// Convert to 2 ASCII characters
			uint8_t high_nibble = (b >> 4) + 'A';
			uint8_t low_nibble = (b & 0xF) + 'A';

			// Accumulate into output word (big-endian)
			ascii_accum = (ascii_accum << 8) | high_nibble;
			ascii_bytes++;
			if (ascii_bytes == 4) {
				msg[msg_idx++] = ascii_accum;
				ascii_accum = 0;
				ascii_bytes = 0;
			}

			ascii_accum = (ascii_accum << 8) | low_nibble;
			ascii_bytes++;
			if (ascii_bytes == 4) {
				msg[msg_idx++] = ascii_accum;
				ascii_accum = 0;
				ascii_bytes = 0;
			}
		}

		// Flush any remaining ASCII bytes with SHA256 padding
		if (ascii_bytes > 0) {
			// Add 0x80 padding byte
			ascii_accum = (ascii_accum << 8) | 0x80;
			ascii_bytes++;

			// Pad to word boundary
			while (ascii_bytes < 4) {
				ascii_accum = ascii_accum << 8;
				ascii_bytes++;
			}
			msg[msg_idx++] = ascii_accum;
		} else {
			// No partial word, add 0x80 as new word
			msg[msg_idx++] = 0x80000000;
		}
	} else {
		// No remainder, add 0x80 padding as new word
		msg[msg_idx++] = 0x80000000;
	}

	// Pad with zeros until length field
	for (int i = msg_idx; i < 14; i++) {
		msg[i] = 0;
	}

	// Add message length in bits (big-endian 64-bit)
	msg[14] = 0;                      // High word
	msg[15] = HASH_ASCII_BYTES * 8;   // Low word (length in bits)
}

// SHA-256 constants for initial state
constant uint32_t INITIAL_H[8] = {
	0x6a09e667, 0xbb67ae85, 0x3c6ef372, 0xa54ff53a,
	0x510e527f, 0x9b05688c, 0x1f83d9ab, 0x5be0cd19
};

__kernel void mine(
	__global uint32_t* current_states,    // [work_size][HASH_NUM_UINT32S] - current state for each thread
	__global uint32_t* start_points,      // [work_size][HASH_NUM_UINT32S] - start point for each thread
	__global uint32_t* dp_buffer,         // [MAX_DPS_PER_CALL][HASH_NUM_UINT32S*2] - output: (start, dp) pairs
	__global volatile uint* dp_count,     // number of DPs found
	const uint32_t mask0,                 // mask for first word of hash
	const uint32_t mask1                  // mask for second word of hash
)
{
	uint gid = get_global_id(0);
	uint thread_offset = gid * HASH_NUM_UINT32S;

	// Load current state and start point for this thread
	uint32_t state[HASH_NUM_UINT32S];
	uint32_t start[HASH_NUM_UINT32S];
	for (int i = 0; i < HASH_NUM_UINT32S; i++) {
		state[i] = current_states[thread_offset + i];
		start[i] = start_points[thread_offset + i];
	}

	// Perform STEPS_PER_TASK iterations
	for (uint step = 0; step < STEPS_PER_TASK; step++) {
		// Convert truncated state to ASCII message (with padding already included)
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

		// Truncate to prefix + suffix bytes
		truncate_hash(hash_full, state);

		// Check if this is a distinguished point
		if (((state[0] & mask0) == 0) && ((state[1] & mask1) == 0)) {
			// Found a DP! Store it if there's room
			uint dp_idx = atomic_inc(dp_count);
			if (dp_idx < MAX_DPS_PER_CALL) {
				uint buf_offset = dp_idx * (HASH_NUM_UINT32S * 2);

				// Read new random start from dp_buffer (before overwriting)
				uint32_t new_start[HASH_NUM_UINT32S];
				for (int i = 0; i < HASH_NUM_UINT32S; i++) {
					new_start[i] = dp_buffer[buf_offset + i];
				}

				// Store start point
				for (int i = 0; i < HASH_NUM_UINT32S; i++) {
					dp_buffer[buf_offset + i] = start[i];
				}
				// Store distinguished point
				for (int i = 0; i < HASH_NUM_UINT32S; i++) {
					dp_buffer[buf_offset + HASH_NUM_UINT32S + i] = state[i];
				}

				// Use the random data we read as the new start
				for (int i = 0; i < HASH_NUM_UINT32S; i++) {
					start[i] = new_start[i];
					state[i] = new_start[i];
				}
			}
		}
	}

	// Save current state and start point for next invocation
	for (int i = 0; i < HASH_NUM_UINT32S; i++) {
		current_states[thread_offset + i] = state[i];
		start_points[thread_offset + i] = start[i];
	}
}
