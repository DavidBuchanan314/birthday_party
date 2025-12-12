import hashlib
# XXX: this is unoptimised, won't work for harder DP_DIFFICULTY

# collision parameters (MUST BE SAME AS SERVER'S!!!)
DP_DIFFICULTY = 16  # bits


def HASH_FN(x):
	return hashlib.md5(x.hex().encode()).digest()[:8]  # half-md5


def IS_DISTINGUISHED(x):
	leading_zeroes = len(x) * 8 - int.from_bytes(x, "big").bit_length()
	return leading_zeroes >= DP_DIFFICULTY


HASH_LENGTH = len(HASH_FN(b""))  # bytes

start_a = bytes.fromhex("e403ca09e4f1082e")
start_b = bytes.fromhex("4be96cf98693b7d1")

seen = [start_a]
while not IS_DISTINGUISHED(start_a):
	start_a = HASH_FN(start_a)
	seen.append(start_a)
seen_set = set(seen)
print(start_a.hex())

while True:
	prev = start_b
	start_b = HASH_FN(start_b)
	if start_b in seen_set:
		print(seen[seen.index(start_b) - 1].hex(), prev.hex())
		exit()
