// STEPS_PER_TASK is passed via compile options (-DSTEPS_PER_TASK=...)
#ifndef STEPS_PER_TASK
#define STEPS_PER_TASK 0x100  // default fallback
#endif

// sha256 impl courtesy deepseek (yeah it got the constants right too!)
// (had to be prompted for the w sliding-window logic)

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

void sha256_update(uint32_t state_out[8], const uint32_t state_in[8], uint32_t block[16]) {
	uint a = state_in[0];
	uint b = state_in[1];
	uint c = state_in[2];
	uint d = state_in[3];
	uint e = state_in[4];
	uint f = state_in[5];
	uint g = state_in[6];
	uint h = state_in[7];

	// First 16 rounds - use block directly
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

__kernel void mine(
	__global volatile uint* found_flag,
	__global uint64_t* found_nonce,
	__global uint32_t state_found[8],
	__global const uint32_t state_in[8],
	const uint64_t base,
	const uint32_t prefixlen,
	const uint32_t mask0,
	const uint32_t mask1
)
{
	uint64_t gid = get_global_id(0);
	uint64_t gid_max = get_global_size(0);

	uint32_t state_in_copy[8];
	state_in_copy[0] = state_in[0];
	state_in_copy[1] = state_in[1];
	state_in_copy[2] = state_in[2];
	state_in_copy[3] = state_in[3];
	state_in_copy[4] = state_in[4];
	state_in_copy[5] = state_in[5];
	state_in_copy[6] = state_in[6];
	state_in_copy[7] = state_in[7];

	for (uint64_t i=base+gid; i<base+STEPS_PER_TASK*gid_max; i+=gid_max) {
		uint32_t state_out[8], msg[16];

		msg[0] = 0x31303030 | (((i>>51)&7) << 16) | (((i>>48)&7) << 8) | (((i>>45)&7) << 0);
		msg[1] = 0x30303030 | (((i>>42)&7) << 30) | (((i>>39)&7) << 16) | (((i>>36)&7) << 8) | (((i>>33)&7) << 0);
		msg[2] = 0x30303030 | (((i>>30)&7) << 30) | (((i>>27)&7) << 16) | (((i>>24)&7) << 8) | (((i>>21)&7) << 0);
		msg[3] = 0x30303030 | (((i>>18)&7) << 24) | (((i>>15)&7) << 16) | (((i>>12)&7) << 8) | (((i>>9)&7) << 0);
		msg[4] = 0x30303080 | (((i>>6)&7) << 24) | (((i>>3)&7) << 16) | ((i&7) << 8);
		msg[5] = 0;
		msg[6] = 0;
		msg[7] = 0;
		msg[8] = 0;
		msg[9] = 0;
		msg[10] = 0;
		msg[11] = 0;
		msg[12] = 0;
		msg[13] = 0;
		msg[14] = 0;
		msg[15] = (prefixlen+19)*8;
		sha256_update(state_out, state_in_copy, msg);

		if (((state_out[0] & mask0) == 0) && ((state_out[1] & mask1) == 0)) {
			if (atomic_cmpxchg(found_flag, 0, 1) == 0) {
				// we found it first

				*found_nonce = i;

				state_found[0] = state_out[0];
				state_found[1] = state_out[1];
				state_found[2] = state_out[2];
				state_found[3] = state_out[3];
				state_found[4] = state_out[4];
				state_found[5] = state_out[5];
				state_found[6] = state_out[6];
				state_found[7] = state_out[7];
			}
		}
	}
}
