// WebGPU SHA256 implementation for Birthday Party collision search
// Ported from OpenCL implementation

// These constants will be injected by Python code via string replacement
// STEPS_PER_TASK: Number of iterations per kernel invocation
// MAX_DPS_PER_CALL: Maximum distinguished points to collect
// HASH_PREFIX_BYTES: Number of prefix bytes from SHA256
// HASH_SUFFIX_BYTES: Number of suffix bytes from SHA256
// HASH_TOTAL_BYTES: HASH_PREFIX_BYTES + HASH_SUFFIX_BYTES
// HASH_NUM_UINT32S: (HASH_TOTAL_BYTES + 3) / 4
// HASH_ASCII_BYTES: HASH_TOTAL_BYTES * 2
// WORKGROUP_SIZE: Workgroup size for compute shader

// SHA-256 K constants
const K: array<u32, 64> = array<u32, 64>(
    0x428a2f98u, 0x71374491u, 0xb5c0fbcfu, 0xe9b5dba5u,
    0x3956c25bu, 0x59f111f1u, 0x923f82a4u, 0xab1c5ed5u,
    0xd807aa98u, 0x12835b01u, 0x243185beu, 0x550c7dc3u,
    0x72be5d74u, 0x80deb1feu, 0x9bdc06a7u, 0xc19bf174u,
    0xe49b69c1u, 0xefbe4786u, 0x0fc19dc6u, 0x240ca1ccu,
    0x2de92c6fu, 0x4a7484aau, 0x5cb0a9dcu, 0x76f988dau,
    0x983e5152u, 0xa831c66du, 0xb00327c8u, 0xbf597fc7u,
    0xc6e00bf3u, 0xd5a79147u, 0x06ca6351u, 0x14292967u,
    0x27b70a85u, 0x2e1b2138u, 0x4d2c6dfcu, 0x53380d13u,
    0x650a7354u, 0x766a0abbu, 0x81c2c92eu, 0x92722c85u,
    0xa2bfe8a1u, 0xa81a664bu, 0xc24b8b70u, 0xc76c51a3u,
    0xd192e819u, 0xd6990624u, 0xf40e3585u, 0x106aa070u,
    0x19a4c116u, 0x1e376c08u, 0x2748774cu, 0x34b0bcb5u,
    0x391c0cb3u, 0x4ed8aa4au, 0x5b9cca4fu, 0x682e6ff3u,
    0x748f82eeu, 0x78a5636fu, 0x84c87814u, 0x8cc70208u,
    0x90befffau, 0xa4506cebu, 0xbef9a3f7u, 0xc67178f2u
);

// SHA-256 initial hash values
const INITIAL_H: array<u32, 8> = array<u32, 8>(
    0x6a09e667u, 0xbb67ae85u, 0x3c6ef372u, 0xa54ff53au,
    0x510e527fu, 0x9b05688cu, 0x1f83d9abu, 0x5be0cd19u
);

// Buffer bindings
@group(0) @binding(0)
var<storage, read_write> current_states: array<u32>;  // [work_size][HASH_NUM_UINT32S]

@group(0) @binding(1)
var<storage, read_write> start_points: array<u32>;    // [work_size][HASH_NUM_UINT32S]

@group(0) @binding(2)
var<storage, read_write> dp_buffer: array<u32>;       // [MAX_DPS_PER_CALL][HASH_NUM_UINT32S*2]

@group(0) @binding(3)
var<storage, read_write> dp_count: atomic<u32>;       // number of DPs found

@group(0) @binding(4)
var<uniform> masks: vec2<u32>;                         // mask0, mask1 for DP check


// Helper functions

// Rotate right (WGSL doesn't have rotate built-in for u32)
fn rotr(x: u32, n: u32) -> u32 {
    return (x >> n) | (x << (32u - n));
}

// SHA-256 helper macros as functions
fn ch(x: u32, y: u32, z: u32) -> u32 {
    return z ^ (x & (y ^ z));
}

fn maj(x: u32, y: u32, z: u32) -> u32 {
    return (x & y) | (z & (x | y));
}

fn sig0(x: u32) -> u32 {
    return rotr(x, 2u) ^ rotr(x, 13u) ^ rotr(x, 22u);
}

fn sig1(x: u32) -> u32 {
    return rotr(x, 6u) ^ rotr(x, 11u) ^ rotr(x, 25u);
}

fn sig2(x: u32) -> u32 {
    return rotr(x, 7u) ^ rotr(x, 18u) ^ (x >> 3u);
}

fn sig3(x: u32) -> u32 {
    return rotr(x, 17u) ^ rotr(x, 19u) ^ (x >> 10u);
}


// SHA-256 compression function
fn sha256_update(state_in: ptr<function, array<u32, 8>>, block: ptr<function, array<u32, 16>>) -> array<u32, 8> {
    var a = (*state_in)[0];
    var b = (*state_in)[1];
    var c = (*state_in)[2];
    var d = (*state_in)[3];
    var e = (*state_in)[4];
    var f = (*state_in)[5];
    var g = (*state_in)[6];
    var h = (*state_in)[7];

    // First 16 rounds - use block directly
    for (var i = 0u; i < 16u; i++) {
        let t1 = h + sig1(e) + ch(e, f, g) + K[i] + (*block)[i];
        let t2 = sig0(a) + maj(a, b, c);

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
    for (var i = 16u; i < 64u; i++) {
        (*block)[i & 15u] = sig3((*block)[(i - 2u) & 15u]) + (*block)[(i - 7u) & 15u] +
                            sig2((*block)[(i - 15u) & 15u]) + (*block)[(i - 16u) & 15u];

        let t1 = h + sig1(e) + ch(e, f, g) + K[i] + (*block)[i & 15u];
        let t2 = sig0(a) + maj(a, b, c);

        h = g;
        g = f;
        f = e;
        e = d + t1;
        d = c;
        c = b;
        b = a;
        a = t1 + t2;
    }

    // Return final state
    var state_out: array<u32, 8>;
    state_out[0] = (*state_in)[0] + a;
    state_out[1] = (*state_in)[1] + b;
    state_out[2] = (*state_in)[2] + c;
    state_out[3] = (*state_in)[3] + d;
    state_out[4] = (*state_in)[4] + e;
    state_out[5] = (*state_in)[5] + f;
    state_out[6] = (*state_in)[6] + g;
    state_out[7] = (*state_in)[7] + h;

    return state_out;
}


// Extract truncated hash (prefix + suffix) from full SHA256
fn truncate_hash(hash_full: ptr<function, array<u32, 8>>) -> array<u32, HASH_NUM_UINT32S> {
    var hash_trunc: array<u32, HASH_NUM_UINT32S>;

    if (HASH_SUFFIX_BYTES == 0u) {
        // Prefix-only (simple case) - just copy first HASH_NUM_UINT32S words
        for (var i = 0u; i < HASH_NUM_UINT32S; i++) {
            hash_trunc[i] = (*hash_full)[i];
        }
    } else {
        // Prefix + suffix - need to extract non-contiguous bytes
        var trunc_idx = 0u;
        var accum = 0u;
        var accum_bytes = 0u;

        // Extract prefix bytes
        for (var byte_offset = 0u; byte_offset < HASH_PREFIX_BYTES; byte_offset++) {
            let word_idx = byte_offset / 4u;
            let byte_in_word = byte_offset % 4u;
            let byte_val = ((*hash_full)[word_idx] >> (24u - byte_in_word * 8u)) & 0xFFu;

            accum = (accum << 8u) | byte_val;
            accum_bytes++;

            if (accum_bytes == 4u) {
                hash_trunc[trunc_idx] = accum;
                trunc_idx++;
                accum = 0u;
                accum_bytes = 0u;
            }
        }

        // Extract suffix bytes
        for (var byte_offset = 0u; byte_offset < HASH_SUFFIX_BYTES; byte_offset++) {
            let abs_byte_offset = 32u - HASH_SUFFIX_BYTES + byte_offset;
            let word_idx = abs_byte_offset / 4u;
            let byte_in_word = abs_byte_offset % 4u;
            let byte_val = ((*hash_full)[word_idx] >> (24u - byte_in_word * 8u)) & 0xFFu;

            accum = (accum << 8u) | byte_val;
            accum_bytes++;

            if (accum_bytes == 4u) {
                hash_trunc[trunc_idx] = accum;
                trunc_idx++;
                accum = 0u;
                accum_bytes = 0u;
            }
        }

        // Flush any remaining bytes
        if (accum_bytes > 0u) {
            accum <<= (4u - accum_bytes) * 8u;  // Left-align remaining bytes
            hash_trunc[trunc_idx] = accum;
        }
    }

    return hash_trunc;
}


// Convert truncated hash to ASCII representation with SHA256 padding
fn hash_to_ascii_message(hash: ptr<function, array<u32, HASH_NUM_UINT32S>>) -> array<u32, 16> {
    var msg: array<u32, 16>;
    var msg_idx = 0u;

    // Process complete 4-byte words
    let complete_words = HASH_TOTAL_BYTES / 4u;

    for (var i = 0u; i < complete_words; i++) {
        let val = (*hash)[i];

        // Convert high 2 bytes to first output word (4 ASCII chars)
        msg[msg_idx] = ((((val >> 28u) & 0xFu) + 0x41u) << 24u) |
                       ((((val >> 24u) & 0xFu) + 0x41u) << 16u) |
                       ((((val >> 20u) & 0xFu) + 0x41u) << 8u) |
                       (((val >> 16u) & 0xFu) + 0x41u);
        msg_idx++;

        // Convert low 2 bytes to second output word (4 ASCII chars)
        msg[msg_idx] = ((((val >> 12u) & 0xFu) + 0x41u) << 24u) |
                       ((((val >> 8u) & 0xFu) + 0x41u) << 16u) |
                       ((((val >> 4u) & 0xFu) + 0x41u) << 8u) |
                       ((val & 0xFu) + 0x41u);
        msg_idx++;
    }

    // Handle partial word (1, 2, or 3 remaining bytes)
    let remainder_bytes = HASH_TOTAL_BYTES % 4u;
    if (remainder_bytes > 0u) {
        // Safe index: use min to ensure we never go out of bounds
        let safe_idx = min(complete_words, HASH_NUM_UINT32S - 1u);
        let val = (*hash)[safe_idx];

        var ascii_accum = 0u;
        var ascii_bytes = 0u;

        for (var byte_idx = 0u; byte_idx < remainder_bytes; byte_idx++) {
            // Extract byte (big-endian: shift from MSB)
            let b = (val >> (24u - byte_idx * 8u)) & 0xFFu;

            // Convert to 2 ASCII characters
            let high_nibble = (b >> 4u) + 0x41u;
            let low_nibble = (b & 0xFu) + 0x41u;

            // Accumulate into output word (big-endian)
            ascii_accum = (ascii_accum << 8u) | high_nibble;
            ascii_bytes++;
            if (ascii_bytes == 4u) {
                msg[msg_idx] = ascii_accum;
                msg_idx++;
                ascii_accum = 0u;
                ascii_bytes = 0u;
            }

            ascii_accum = (ascii_accum << 8u) | low_nibble;
            ascii_bytes++;
            if (ascii_bytes == 4u) {
                msg[msg_idx] = ascii_accum;
                msg_idx++;
                ascii_accum = 0u;
                ascii_bytes = 0u;
            }
        }

        // Flush any remaining ASCII bytes with SHA256 padding
        if (ascii_bytes > 0u) {
            // Add 0x80 padding byte
            ascii_accum = (ascii_accum << 8u) | 0x80u;
            ascii_bytes++;

            // Pad to word boundary
            while (ascii_bytes < 4u) {
                ascii_accum = ascii_accum << 8u;
                ascii_bytes++;
            }
            msg[msg_idx] = ascii_accum;
            msg_idx++;
        } else {
            // No partial word, add 0x80 as new word
            msg[msg_idx] = 0x80000000u;
            msg_idx++;
        }
    } else {
        // No remainder, add 0x80 padding as new word
        msg[msg_idx] = 0x80000000u;
        msg_idx++;
    }

    // Pad with zeros until length field
    for (var i = msg_idx; i < 14u; i++) {
        msg[i] = 0u;
    }

    // Add message length in bits (big-endian 64-bit)
    msg[14] = 0u;                      // High word
    msg[15] = HASH_ASCII_BYTES * 8u;   // Low word (length in bits)

    return msg;
}


// Main compute kernel
@compute @workgroup_size(WORKGROUP_SIZE)
fn mine(@builtin(global_invocation_id) global_id: vec3<u32>) {
    let gid = global_id.x;
    let thread_offset = gid * HASH_NUM_UINT32S;

    // Load current state and start point for this thread
    var state: array<u32, HASH_NUM_UINT32S>;
    var start: array<u32, HASH_NUM_UINT32S>;
    for (var i = 0u; i < HASH_NUM_UINT32S; i++) {
        state[i] = current_states[thread_offset + i];
        start[i] = start_points[thread_offset + i];
    }

    // Perform STEPS_PER_TASK iterations
    for (var step = 0u; step < STEPS_PER_TASK; step++) {
        // Convert truncated state to ASCII message (with padding already included)
        var msg = hash_to_ascii_message(&state);

        // Compute SHA256(hex(state))
        var initial_h_local = INITIAL_H;
        var hash_full = sha256_update(&initial_h_local, &msg);

        // Truncate to prefix + suffix bytes
        state = truncate_hash(&hash_full);

        // Check if this is a distinguished point
        if (((state[0] & masks[0]) == 0u) && ((state[1] & masks[1]) == 0u)) {
            // Found a DP! Store it if there's room
            let dp_idx = atomicAdd(&dp_count, 1u);
            if (dp_idx < MAX_DPS_PER_CALL) {
                let buf_offset = dp_idx * (HASH_NUM_UINT32S * 2u);

                // Read new random start from dp_buffer (before overwriting)
                var new_start: array<u32, HASH_NUM_UINT32S>;
                for (var i = 0u; i < HASH_NUM_UINT32S; i++) {
                    new_start[i] = dp_buffer[buf_offset + i];
                }

                // Store start point
                for (var i = 0u; i < HASH_NUM_UINT32S; i++) {
                    dp_buffer[buf_offset + i] = start[i];
                }
                // Store distinguished point
                for (var i = 0u; i < HASH_NUM_UINT32S; i++) {
                    dp_buffer[buf_offset + HASH_NUM_UINT32S + i] = state[i];
                }

                // Use the random data we read as the new start
                for (var i = 0u; i < HASH_NUM_UINT32S; i++) {
                    start[i] = new_start[i];
                    state[i] = new_start[i];
                }
            }
        }
    }

    // Save current state and start point for next invocation
    for (var i = 0u; i < HASH_NUM_UINT32S; i++) {
        current_states[thread_offset + i] = state[i];
        start_points[thread_offset + i] = start[i];
    }
}
