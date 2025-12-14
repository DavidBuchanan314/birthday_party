import argparse
from birthday_party.ocl_sha256.mine import hash_fn, is_distinguished, bytes_to_ascii, HASH_LENGTH

# XXX: this is unoptimised, won't work for harder DP_DIFFICULTY


def finalize(start_a: bytes, start_b: bytes, dp_bits: int = 24):
	"""
	Given two distinguished points from different chains, find the actual collision.

	Walk chain A until we reach the distinguished point, storing all intermediate values.
	Then walk chain B until we find a point that appears in chain A's path.
	"""
	# Walk chain A to the distinguished point, recording all values
	point_a = start_a
	seen = [point_a]
	while not is_distinguished(point_a, dp_bits):
		point_a = hash_fn(point_a)
		seen.append(point_a)
	seen_set = set(seen)

	print(f"Distinguished point: {point_a.hex()}")

	# Walk chain B until we find a collision with chain A
	point_b = start_b
	while not is_distinguished(point_b, dp_bits):
		prev_b = point_b
		point_b = hash_fn(point_b)
		if point_b in seen_set:
			# Found the collision point
			prev_a = seen[seen.index(point_b) - 1]
			print(f"Collision: {bytes_to_ascii(prev_a)} {bytes_to_ascii(prev_b)} -> {point_b.hex()}")
			return prev_a, prev_b

	raise Exception("chains do not collide")


def main():
	parser = argparse.ArgumentParser(description="Finalize collision search by finding exact collision")
	parser.add_argument("start_a", help="Starting point for chain A (hex)")
	parser.add_argument("start_b", help="Starting point for chain B (hex)")
	parser.add_argument(
		"--dp-bits", type=int, default=24, help="Number of leading zero bits for distinguished points (default: 24)"
	)
	args = parser.parse_args()

	start_a = bytes.fromhex(args.start_a)
	start_b = bytes.fromhex(args.start_b)

	if len(start_a) != HASH_LENGTH or len(start_b) != HASH_LENGTH:
		print(f"Error: Both starting points must be {HASH_LENGTH} bytes ({HASH_LENGTH * 2} hex chars)")
		return

	finalize(start_a, start_b, args.dp_bits)


if __name__ == "__main__":
	main()
