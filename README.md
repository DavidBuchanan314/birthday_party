# Birthday Party

Implements distributed hash collision search via [parallel pollard's rho with distinguished points](https://www.cs.csi.cuny.edu/~zhangx/papers/P_2018_LISAT_Weber_Zhang.pdf) (Brian Weber, Xiaowen Zhang, 2018). For background, check out my [blog post](https://www.da.vidbuchanan.co.uk/blog/colliding-secure-hashes.html). My original implementation was too janky to publish, but this version is better (albeit substantially AI-generated - beware misleading in-code comments/strings, AI does not understand the concept well).

A central server tracks work done, detects collisions, and provides stats in a web dashboard (powered by SQLite).

There's an OpenCL client implementation for *truncated* SHA256, which runs at 4.3GH/s on my 6700 XT GPU (for reference, hashcat on the same card gets 5.2GH/s). I vaguely recall my original (blogpost-era) implementation getting 2.6GH/s.

Example result: (96-bit sha256 collision - first and last 48 bits)

```
$ echo -n retr0id_662d970782071aa7a038dce6 | sha256sum
307e0e71a409d2bf67e76c676d81bd0ff87ee228cd8f991714589d0564e6ea9a  -

$ echo -n retr0id_430d19a6c51814d895666635 | sha256sum
307e0e71a4098e7fb7d72c86cd041a006181c6d8e29882b581d69d0564e6ea9a  -
```

(Note: The version of the code in this repo does not support string prefixes - but it's shouldn't be hard to modify it)

## Installation

Clone the repo, then:
```bash
python3 -m pip install -e .
```

## Start the Server

```bash
# first create a user (an API token will be printed)
python3 -m birthday_party.create_user <username>

# start the server itself (see --help for args)
python3 -m birthday_party.server
```

The server listens on `http://localhost:8080` by default.

## Start a Client

This repo has two client implementations. You can run many client instances at once, but all clients must be running under the same configuration (same hash, same length, etc. - also matching the server's configuration)

```bash
python3 -m birthday_party.ocl_sha256.mine <username> <usertoken>
```

If you're planning on doing a lot of computation (many colliding bits), you might want to tune the parameters first. See `birthday_party.ocl_sha256.optimize_params` to help discover ideal parameters for your hardware.

See also `birthday_party.cpu_md5.mine` (if you want to look at the code, this is the simpler of the two to understand)

## "Finalization"

The server does not find collisions directly, it finds what I call "pre-collisions" - two start points that meet in the same distinguished point. Some extra computation is required to discover the actual collision point, which is performed by a finalization script:

```bash
$ python3 -m birthday_party.ocl_sha256.finalize 824e148cdfed768a 953738491b56c865
Distinguished point: 0000e13a1476d5d7
Collision: DHLJJEHPLHFNBDFH KDJDDFKGFFHILMCI -> 61dfdfcf9964fbb2

$ echo -n DHLJJEHPLHFNBDFH | sha256sum
61dfdfcf9964fbb2537f0f337927de369535c2de3e9cf21aa92e2ca4c577d688  -

$ echo -n KDJDDFKGFFHILMCI | sha256sum
61dfdfcf9964fbb2281a149398d09d98a07551ae01428c3e84e89ea16f8f9729  -
```

(Note: finalize config must also match mine config!)

## Development

Install dev dependencies:
```bash
python3 -m pip install -e ".[dev]"
```

Optionally, Set up pre-commit hooks to auto-format on commit:
```bash
pre-commit install
```

Run tests via:
```bash
pytest -v
```

## Future Ideas

The current implementation assumes clients are trusted to report work honestly. With some changes, it should be possible to devise a system that works even with untrusted clients. Rather than submitting distinguished points, clients could submit the *penultimate* point - one that hashes to a distingushed point. The server can cheaply verify this.

A client could still lie about the starting point, but submitting real distinguished points with fake starting points would be equally as hard as just doing the work honestly.

To mitigate dishonest clients more thoroughly, the server could distribute starting points rather than having the client pick them for itself. A small percentage of distributed start points would be ones that the server already knows the solution to, thus allowing it to detect dishonest clients.

One day I'd like to implement this and stand up a public instance. Maybe together we could compute 128-bit collisions. Either full-MD5 or half-SHA256, or maybe something else entirely. Yes, full-MD5 collisions already exist, but the shortest one is a full 64-byte block of random bytes. This technique could produce a shorter collision of either 16 binary bytes, or 32 bytes of ascii hex.

Maybe I could write a WebGPU client, too. I's a lot easier to get thousands of people to visit a webpage than to install and run a python package.

## Examples

96-bit sha256 (first and last 48 bits)

```
$ echo -n IOCDCPMLBAIFPJFOOFGPEDFM | sha256sum
36f4a214ddd22b9fcbd07ee89dc6aef59b1477f4166ce4ddc098dd26b02208d2  -

$ echo -n NCOKOPPPBDDEAJPIEENMOIKL | sha256sum
36f4a214ddd20c9c08f9af75d4768755835a850a640a37986ae3dd26b02208d2  -
```

```
$ echo -n CCOCLKBGOPENFGMOFFKEDJDB | sha256sum
ff22fcfe8709a8a10da40ef79d38ee1440fbbe317af3863a5063f15ae24265d4  -

$ echo -n GLNIEFGCLEKEDFLGAKHILOKH | sha256sum
ff22fcfe8709408a80f9f876a0ecd0607d95cd576463f7cd3726f15ae24265d4  -
```

Both of these were computed in about 10 hours on my 6700XT. I actually got lucky time-wise, my estimate was ~17h for a single collision.
