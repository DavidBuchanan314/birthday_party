import argparse
from birthday_party.ocl_sha256.mine import hash_fn, is_distinguished, bytes_to_ascii
from birthday_party.ocl_sha256.hash_config import HashConfig, DEFAULT_CONFIG

# XXX: this is unoptimised, won't work for harder DP_DIFFICULTY


def finalize(start_a: bytes, start_b: bytes, dp_bits: int = 24, hash_config: HashConfig = DEFAULT_CONFIG):
	"""
	Given two distinguished points from different chains, find the actual collision.

	Walk chain A until we reach the distinguished point, storing all intermediate values.
	Then walk chain B until we find a point that appears in chain A's path.
	"""
	# Walk chain A to the distinguished point, recording all values
	point_a = start_a
	seen = [point_a]
	while not is_distinguished(point_a, dp_bits):
		point_a = hash_fn(point_a, hash_config)
		seen.append(point_a)
	seen_set = set(seen)

	print(f"Distinguished point: {point_a.hex()}")

	# Walk chain B until we find a collision with chain A
	point_b = start_b
	while not is_distinguished(point_b, dp_bits):
		prev_b = point_b
		point_b = hash_fn(point_b, hash_config)
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
	parser.add_argument(
		"--hash-bytes",
		type=int,
		default=8,
		help="Number of prefix bytes from SHA256 hash (1-32, default: 8 for backward compatibility)",
	)
	args = parser.parse_args()

	hash_config = HashConfig(prefix_bytes=args.hash_bytes)
	start_a = bytes.fromhex(args.start_a)
	start_b = bytes.fromhex(args.start_b)

	if len(start_a) != hash_config.total_bytes or len(start_b) != hash_config.total_bytes:
		print(
			f"Error: Both starting points must be {hash_config.total_bytes} bytes ({hash_config.total_bytes * 2} hex chars)"
		)
		return

	finalize(start_a, start_b, args.dp_bits, hash_config)


if __name__ == "__main__":
	main()
