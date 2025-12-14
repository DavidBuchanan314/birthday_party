// Birthday Party WebGPU Browser Miner

// Configuration constants
const WORK_SIZE = 0x4000;  // 16384
const STEPS_PER_TASK = 0x400;  // 1024
const MAX_DPS_PER_CALL = 1024;
const WORKGROUP_SIZE = 256;

// Hash configuration
class HashConfig {
    constructor(prefixBytes = 8, suffixBytes = 0) {
        this.prefixBytes = prefixBytes;
        this.suffixBytes = suffixBytes;

        if (prefixBytes + suffixBytes < 5 || prefixBytes + suffixBytes > 27) {
            throw new Error('Total bytes must be 5-27');
        }
    }

    get totalBytes() {
        return this.prefixBytes + this.suffixBytes;
    }

    get numUint32s() {
        return Math.ceil(this.totalBytes / 4);
    }

    get asciiBytes() {
        return this.totalBytes * 2;
    }
}

// WGSL Shader generator
function getShaderSource(config, stepsPerTask, maxDPsPerCall, workgroupSize) {
    const hashTotalBytes = config.totalBytes;
    const hashNumUint32s = config.numUint32s;
    const hashAsciiBytes = config.asciiBytes;

    return `
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

const INITIAL_H: array<u32, 8> = array<u32, 8>(
    0x6a09e667u, 0xbb67ae85u, 0x3c6ef372u, 0xa54ff53au,
    0x510e527fu, 0x9b05688cu, 0x1f83d9abu, 0x5be0cd19u
);

@group(0) @binding(0)
var<storage, read_write> current_states: array<u32>;

@group(0) @binding(1)
var<storage, read_write> start_points: array<u32>;

@group(0) @binding(2)
var<storage, read_write> dp_buffer: array<u32>;

@group(0) @binding(3)
var<storage, read_write> dp_count: atomic<u32>;

@group(0) @binding(4)
var<uniform> masks: vec2<u32>;

fn rotr(x: u32, n: u32) -> u32 {
    return (x >> n) | (x << (32u - n));
}

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

fn sha256_update(state_in: ptr<function, array<u32, 8>>, block: ptr<function, array<u32, 16>>) -> array<u32, 8> {
    var a = (*state_in)[0];
    var b = (*state_in)[1];
    var c = (*state_in)[2];
    var d = (*state_in)[3];
    var e = (*state_in)[4];
    var f = (*state_in)[5];
    var g = (*state_in)[6];
    var h = (*state_in)[7];

    for (var i = 0u; i < 16u; i++) {
        let t1 = h + sig1(e) + ch(e, f, g) + K[i] + (*block)[i];
        let t2 = sig0(a) + maj(a, b, c);
        h = g; g = f; f = e; e = d + t1;
        d = c; c = b; b = a; a = t1 + t2;
    }

    for (var i = 16u; i < 64u; i++) {
        (*block)[i & 15u] = sig3((*block)[(i - 2u) & 15u]) + (*block)[(i - 7u) & 15u] +
                            sig2((*block)[(i - 15u) & 15u]) + (*block)[(i - 16u) & 15u];
        let t1 = h + sig1(e) + ch(e, f, g) + K[i] + (*block)[i & 15u];
        let t2 = sig0(a) + maj(a, b, c);
        h = g; g = f; f = e; e = d + t1;
        d = c; c = b; b = a; a = t1 + t2;
    }

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

fn truncate_hash(hash_full: ptr<function, array<u32, 8>>) -> array<u32, ${hashNumUint32s}u> {
    var hash_trunc: array<u32, ${hashNumUint32s}u>;

    if (${config.suffixBytes}u == 0u) {
        for (var i = 0u; i < ${hashNumUint32s}u; i++) {
            hash_trunc[i] = (*hash_full)[i];
        }
    } else {
        var trunc_idx = 0u;
        var accum = 0u;
        var accum_bytes = 0u;

        for (var byte_offset = 0u; byte_offset < ${config.prefixBytes}u; byte_offset++) {
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

        for (var byte_offset = 0u; byte_offset < ${config.suffixBytes}u; byte_offset++) {
            let abs_byte_offset = 32u - ${config.suffixBytes}u + byte_offset;
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

        if (accum_bytes > 0u) {
            accum <<= (4u - accum_bytes) * 8u;
            hash_trunc[trunc_idx] = accum;
        }
    }

    return hash_trunc;
}

fn hash_to_ascii_message(hash: ptr<function, array<u32, ${hashNumUint32s}u>>) -> array<u32, 16> {
    var msg: array<u32, 16>;
    var msg_idx = 0u;

    let complete_words = ${hashTotalBytes}u / 4u;

    for (var i = 0u; i < complete_words; i++) {
        let val = (*hash)[i];
        msg[msg_idx] = ((((val >> 28u) & 0xFu) + 0x41u) << 24u) |
                       ((((val >> 24u) & 0xFu) + 0x41u) << 16u) |
                       ((((val >> 20u) & 0xFu) + 0x41u) << 8u) |
                       (((val >> 16u) & 0xFu) + 0x41u);
        msg_idx++;
        msg[msg_idx] = ((((val >> 12u) & 0xFu) + 0x41u) << 24u) |
                       ((((val >> 8u) & 0xFu) + 0x41u) << 16u) |
                       ((((val >> 4u) & 0xFu) + 0x41u) << 8u) |
                       ((val & 0xFu) + 0x41u);
        msg_idx++;
    }

    let remainder_bytes = ${hashTotalBytes}u % 4u;
    if (remainder_bytes > 0u) {
        let safe_idx = min(complete_words, ${hashNumUint32s}u - 1u);
        let val = (*hash)[safe_idx];
        var ascii_accum = 0u;
        var ascii_bytes = 0u;

        for (var byte_idx = 0u; byte_idx < remainder_bytes; byte_idx++) {
            let b = (val >> (24u - byte_idx * 8u)) & 0xFFu;
            let high_nibble = (b >> 4u) + 0x41u;
            let low_nibble = (b & 0xFu) + 0x41u;

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

        if (ascii_bytes > 0u) {
            ascii_accum = (ascii_accum << 8u) | 0x80u;
            ascii_bytes++;
            while (ascii_bytes < 4u) {
                ascii_accum = ascii_accum << 8u;
                ascii_bytes++;
            }
            msg[msg_idx] = ascii_accum;
            msg_idx++;
        } else {
            msg[msg_idx] = 0x80000000u;
            msg_idx++;
        }
    } else {
        msg[msg_idx] = 0x80000000u;
        msg_idx++;
    }

    for (var i = msg_idx; i < 14u; i++) {
        msg[i] = 0u;
    }

    msg[14] = 0u;
    msg[15] = ${hashAsciiBytes}u * 8u;

    return msg;
}

@compute @workgroup_size(${workgroupSize})
fn mine(@builtin(global_invocation_id) global_id: vec3<u32>) {
    let gid = global_id.x;
    let thread_offset = gid * ${hashNumUint32s}u;

    var state: array<u32, ${hashNumUint32s}u>;
    var start: array<u32, ${hashNumUint32s}u>;
    for (var i = 0u; i < ${hashNumUint32s}u; i++) {
        state[i] = current_states[thread_offset + i];
        start[i] = start_points[thread_offset + i];
    }

    for (var step = 0u; step < ${stepsPerTask}u; step++) {
        var msg = hash_to_ascii_message(&state);
        var initial_h_local = INITIAL_H;
        var hash_full = sha256_update(&initial_h_local, &msg);
        state = truncate_hash(&hash_full);

        if (((state[0] & masks[0]) == 0u) && ((state[1] & masks[1]) == 0u)) {
            let dp_idx = atomicAdd(&dp_count, 1u);
            if (dp_idx < ${maxDPsPerCall}u) {
                let buf_offset = dp_idx * (${hashNumUint32s}u * 2u);

                var new_start: array<u32, ${hashNumUint32s}u>;
                for (var i = 0u; i < ${hashNumUint32s}u; i++) {
                    new_start[i] = dp_buffer[buf_offset + i];
                }

                for (var i = 0u; i < ${hashNumUint32s}u; i++) {
                    dp_buffer[buf_offset + i] = start[i];
                }
                for (var i = 0u; i < ${hashNumUint32s}u; i++) {
                    dp_buffer[buf_offset + ${hashNumUint32s}u + i] = state[i];
                }

                for (var i = 0u; i < ${hashNumUint32s}u; i++) {
                    start[i] = new_start[i];
                    state[i] = new_start[i];
                }
            }
        }
    }

    for (var i = 0u; i < ${hashNumUint32s}u; i++) {
        current_states[thread_offset + i] = state[i];
        start_points[thread_offset + i] = start[i];
    }
}
`;
}

// Pollard Rho Miner class
class PollardRhoMiner {
    constructor(workSize = WORK_SIZE, stepsPerTask = STEPS_PER_TASK, hashConfig = new HashConfig()) {
        this.workSize = workSize;
        this.stepsPerTask = stepsPerTask;
        this.hashConfig = hashConfig;
        this.device = null;
        this.pipeline = null;
        this.bindGroup = null;
    }

    async initialize() {
        console.log('Initializing WebGPU miner...');

        // Check WebGPU support
        if (!navigator.gpu) {
            throw new Error('WebGPU not supported in this browser');
        }

        // Request adapter
        const adapter = await navigator.gpu.requestAdapter();
        if (!adapter) {
            throw new Error('No WebGPU adapter found');
        }

        console.log('GPU Adapter:', adapter);

        // Request device
        this.device = await adapter.requestDevice();
        console.log('GPU Device obtained');

        const numUint32s = this.hashConfig.numUint32s;

        // Initialize random states
        this.currentStates = new Uint32Array(this.workSize * numUint32s);
        this.startPoints = new Uint32Array(this.workSize * numUint32s);

        // Fill with random data
        for (let i = 0; i < this.currentStates.length; i++) {
            this.currentStates[i] = Math.floor(Math.random() * 0xFFFFFFFF);
            this.startPoints[i] = this.currentStates[i];
        }

        // DP buffer
        const dpBufferWidth = numUint32s * 2;
        this.dpBuffer = new Uint32Array(MAX_DPS_PER_CALL * dpBufferWidth);
        for (let i = 0; i < this.dpBuffer.length; i++) {
            this.dpBuffer[i] = Math.floor(Math.random() * 0xFFFFFFFF);
        }
        // Set first bit to ensure not distinguished
        for (let i = 0; i < MAX_DPS_PER_CALL; i++) {
            this.dpBuffer[i * dpBufferWidth] |= 0x80000000;
        }

        this.dpCount = new Uint32Array([0]);

        // Create GPU buffers
        this.currentStatesBuffer = this.device.createBuffer({
            size: this.currentStates.byteLength,
            usage: GPUBufferUsage.STORAGE | GPUBufferUsage.COPY_SRC | GPUBufferUsage.COPY_DST,
            mappedAtCreation: true
        });
        new Uint32Array(this.currentStatesBuffer.getMappedRange()).set(this.currentStates);
        this.currentStatesBuffer.unmap();

        this.startPointsBuffer = this.device.createBuffer({
            size: this.startPoints.byteLength,
            usage: GPUBufferUsage.STORAGE | GPUBufferUsage.COPY_SRC | GPUBufferUsage.COPY_DST,
            mappedAtCreation: true
        });
        new Uint32Array(this.startPointsBuffer.getMappedRange()).set(this.startPoints);
        this.startPointsBuffer.unmap();

        this.dpBufferGPU = this.device.createBuffer({
            size: this.dpBuffer.byteLength,
            usage: GPUBufferUsage.STORAGE | GPUBufferUsage.COPY_SRC | GPUBufferUsage.COPY_DST,
            mappedAtCreation: true
        });
        new Uint32Array(this.dpBufferGPU.getMappedRange()).set(this.dpBuffer);
        this.dpBufferGPU.unmap();

        this.dpCountBuffer = this.device.createBuffer({
            size: 4,
            usage: GPUBufferUsage.STORAGE | GPUBufferUsage.COPY_SRC | GPUBufferUsage.COPY_DST
        });

        this.masksBuffer = this.device.createBuffer({
            size: 8,
            usage: GPUBufferUsage.UNIFORM | GPUBufferUsage.COPY_DST
        });

        // Staging buffers
        this.dpCountStaging = this.device.createBuffer({
            size: 4,
            usage: GPUBufferUsage.MAP_READ | GPUBufferUsage.COPY_DST
        });

        this.dpBufferStaging = this.device.createBuffer({
            size: this.dpBuffer.byteLength,
            usage: GPUBufferUsage.MAP_READ | GPUBufferUsage.COPY_DST
        });

        this.currentStatesStaging = this.device.createBuffer({
            size: this.currentStates.byteLength,
            usage: GPUBufferUsage.MAP_READ | GPUBufferUsage.COPY_DST
        });

        this.startPointsStaging = this.device.createBuffer({
            size: this.startPoints.byteLength,
            usage: GPUBufferUsage.MAP_READ | GPUBufferUsage.COPY_DST
        });

        // Create shader module
        const shaderSource = getShaderSource(this.hashConfig, this.stepsPerTask, MAX_DPS_PER_CALL, WORKGROUP_SIZE);
        const shaderModule = this.device.createShaderModule({
            code: shaderSource
        });

        // Create compute pipeline
        this.pipeline = this.device.createComputePipeline({
            layout: 'auto',
            compute: {
                module: shaderModule,
                entryPoint: 'mine'
            }
        });

        // Create bind group
        this.bindGroup = this.device.createBindGroup({
            layout: this.pipeline.getBindGroupLayout(0),
            entries: [
                { binding: 0, resource: { buffer: this.currentStatesBuffer } },
                { binding: 1, resource: { buffer: this.startPointsBuffer } },
                { binding: 2, resource: { buffer: this.dpBufferGPU } },
                { binding: 3, resource: { buffer: this.dpCountBuffer } },
                { binding: 4, resource: { buffer: this.masksBuffer } }
            ]
        });

        console.log('Miner initialized successfully!');
    }

    async mine(dpBits = 16) {
        const startTime = performance.now();

        // Compute masks
        let mask0, mask1;
        if (dpBits <= 32) {
            mask0 = (0xFFFFFFFF << (32 - dpBits)) >>> 0;
            mask1 = 0;
        } else {
            mask0 = 0xFFFFFFFF;
            mask1 = (0xFFFFFFFF << (64 - dpBits)) >>> 0;
        }

        // Update masks
        const masksData = new Uint32Array([mask0, mask1]);
        this.device.queue.writeBuffer(this.masksBuffer, 0, masksData);

        // Reset DP counter
        this.device.queue.writeBuffer(this.dpCountBuffer, 0, new Uint32Array([0]));

        // Run compute shader
        const commandEncoder = this.device.createCommandEncoder();
        const passEncoder = commandEncoder.beginComputePass();
        passEncoder.setPipeline(this.pipeline);
        passEncoder.setBindGroup(0, this.bindGroup);
        passEncoder.dispatchWorkgroups(this.workSize / WORKGROUP_SIZE);
        passEncoder.end();

        // Copy results to staging
        commandEncoder.copyBufferToBuffer(this.dpCountBuffer, 0, this.dpCountStaging, 0, 4);

        this.device.queue.submit([commandEncoder.finish()]);

        // Read back DP count
        await this.dpCountStaging.mapAsync(GPUMapMode.READ);
        const dpCountData = new Uint32Array(this.dpCountStaging.getMappedRange().slice(0));
        this.dpCountStaging.unmap();

        let numDPs = dpCountData[0];
        if (numDPs > MAX_DPS_PER_CALL) {
            console.warn('MAX_DPS_PER_CALL exceeded! Increase dp_bits');
            numDPs = MAX_DPS_PER_CALL;
        }

        const results = [];

        // Read back DPs if any found
        if (numDPs > 0) {
            const encoder2 = this.device.createCommandEncoder();
            encoder2.copyBufferToBuffer(this.dpBufferGPU, 0, this.dpBufferStaging, 0, this.dpBuffer.byteLength);
            this.device.queue.submit([encoder2.finish()]);

            await this.dpBufferStaging.mapAsync(GPUMapMode.READ);
            const dpBufferData = new Uint32Array(this.dpBufferStaging.getMappedRange().slice(0));
            this.dpBufferStaging.unmap();

            const numUint32s = this.hashConfig.numUint32s;
            const totalBytes = this.hashConfig.totalBytes;

            for (let i = 0; i < numDPs; i++) {
                const offset = i * numUint32s * 2;
                const startPoint = new Uint8Array(totalBytes);
                const dp = new Uint8Array(totalBytes);

                // Convert uint32s to bytes
                for (let j = 0; j < numUint32s; j++) {
                    const val = dpBufferData[offset + j];
                    const bytes = [(val >> 24) & 0xFF, (val >> 16) & 0xFF, (val >> 8) & 0xFF, val & 0xFF];
                    for (let k = 0; k < 4 && j * 4 + k < totalBytes; k++) {
                        startPoint[j * 4 + k] = bytes[k];
                    }
                }

                for (let j = 0; j < numUint32s; j++) {
                    const val = dpBufferData[offset + numUint32s + j];
                    const bytes = [(val >> 24) & 0xFF, (val >> 16) & 0xFF, (val >> 8) & 0xFF, val & 0xFF];
                    for (let k = 0; k < 4 && j * 4 + k < totalBytes; k++) {
                        dp[j * 4 + k] = bytes[k];
                    }
                }

                results.push({ startPoint, dp });
            }

            // Refill DP buffer
            const dpBufferWidth = numUint32s * 2;
            for (let i = 0; i < numDPs; i++) {
                for (let j = 0; j < dpBufferWidth; j++) {
                    this.dpBuffer[i * dpBufferWidth + j] = Math.floor(Math.random() * 0xFFFFFFFF);
                }
                this.dpBuffer[i * dpBufferWidth] |= 0x80000000;
            }
            this.device.queue.writeBuffer(this.dpBufferGPU, 0, this.dpBuffer);
        }

        // Read back states
        const encoder3 = this.device.createCommandEncoder();
        encoder3.copyBufferToBuffer(this.currentStatesBuffer, 0, this.currentStatesStaging, 0, this.currentStates.byteLength);
        encoder3.copyBufferToBuffer(this.startPointsBuffer, 0, this.startPointsStaging, 0, this.startPoints.byteLength);
        this.device.queue.submit([encoder3.finish()]);

        await this.currentStatesStaging.mapAsync(GPUMapMode.READ);
        this.currentStates = new Uint32Array(this.currentStatesStaging.getMappedRange().slice(0));
        this.currentStatesStaging.unmap();

        await this.startPointsStaging.mapAsync(GPUMapMode.READ);
        this.startPoints = new Uint32Array(this.startPointsStaging.getMappedRange().slice(0));
        this.startPointsStaging.unmap();

        const duration = (performance.now() - startTime) / 1000;
        const numHashes = this.workSize * this.stepsPerTask;
        const rate = numHashes / duration;

        return { results, rate, numHashes };
    }
}

// Utility functions
function bytesToHex(bytes) {
    return Array.from(bytes).map(b => b.toString(16).padStart(2, '0')).join('');
}

// Main execution
async function main() {
    console.log('='.repeat(70));
    console.log('Birthday Party WebGPU Browser Miner');
    console.log('='.repeat(70));

    try {
        const miner = new PollardRhoMiner();
        await miner.initialize();

        console.log('\nStarting mining loop (dp_bits=16)...');
        console.log('Press Ctrl+C (or close tab) to stop\n');

        let totalDPs = 0;
        let totalHashes = 0;
        const startTime = performance.now();

        // Mine continuously
        for (let iter = 0; iter < 10; iter++) {  // Just 10 iterations for demo
            const { results, rate, numHashes } = await miner.mine(16);
            totalHashes += numHashes;

            if (results.length > 0) {
                totalDPs += results.length;
                const elapsed = (performance.now() - startTime) / 1000;
                console.log(`Found ${results.length} DPs! Total: ${totalDPs} DPs in ${elapsed.toFixed(1)}s (${(totalHashes/elapsed).toFixed(0)} H/s, ${(totalDPs/elapsed).toFixed(2)} DP/s)`);

                for (const { startPoint, dp } of results) {
                    console.log({
                        start: bytesToHex(startPoint),
                        dp: bytesToHex(dp)
                    });
                }
            }

            // Show progress every iteration
            if (iter % 1 === 0) {
                const elapsed = (performance.now() - startTime) / 1000;
                console.log(`Iteration ${iter + 1}: ${rate.toFixed(0)} H/s (${totalDPs} DPs total)`);
            }
        }

        const finalElapsed = (performance.now() - startTime) / 1000;
        console.log(`\nMining complete!`);
        console.log(`Total: ${totalDPs} DPs, ${totalHashes.toLocaleString()} hashes in ${finalElapsed.toFixed(1)}s`);
        console.log(`Average: ${(totalHashes/finalElapsed).toFixed(0)} H/s, ${(totalDPs/finalElapsed).toFixed(2)} DP/s`);

    } catch (error) {
        console.error('Error:', error);
        console.error(error.stack);
    }
}

// Export for use in HTML
if (typeof window !== 'undefined') {
    window.PollardRhoMiner = PollardRhoMiner;
    window.HashConfig = HashConfig;
    window.startMiner = main;
}
