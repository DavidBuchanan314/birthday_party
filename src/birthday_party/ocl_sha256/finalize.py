import argparse
from tqdm import tqdm
from birthday_party.ocl_sha256.mine import hash_fn, is_distinguished, bytes_to_ascii
from birthday_party.ocl_sha256.hash_config import HashConfig, DEFAULT_CONFIG

# XXX: this is unoptimised, will be very slow for harder DP_DIFFICULTY
# also there might be some edge-cases when start point a is on b's chain and vice versa


def finalize_inner(start_a: bytes, start_b: bytes, dp_bits: int, hash_config: HashConfig = DEFAULT_CONFIG):
	"""
	Given two distinguished points from different chains, find the actual collision.

	Walk chain A until we reach the distinguished point, storing all intermediate values.
	Then walk chain B until we find a point that appears in chain A's path.

	So as to not run out of memory for large dp_bits, we only store
	"semidistinguished" points along the paths. So, this function must be called
	iteratively with decreasing values of dp_bits, until semidp_bits is 0 and
	we'll find the actual collision point.
	"""
	semidp_bits = max(dp_bits - 8, 0)

	# Walk chain A to the distinguished point, recording all values
	point_a = start_a
	seen = [point_a]
	with tqdm(desc="chain A") as pbar:
		while True:
			point_a = hash_fn(point_a, hash_config)
			if is_distinguished(point_a, semidp_bits):
				seen.append(point_a)
				pbar.update(1)
			if is_distinguished(point_a, dp_bits):
				break
	seen_set = set(seen)

	print(f"Distinguished point: {point_a.hex()}")

	# Walk chain B until we find a collision with chain A
	prev_b = point_b = start_b
	with tqdm(desc="chain B") as pbar:
		while True:
			point_b = hash_fn(point_b, hash_config)
			if is_distinguished(point_b, semidp_bits):
				pbar.update(1)
				if point_b in seen_set:
					# Found the collision point
					prev_a = seen[seen.index(point_b) - 1]
					return prev_a, prev_b
				prev_b = point_b
			if is_distinguished(point_b, dp_bits):
				break

	raise Exception("chains do not collide")


def finalize(start_a: bytes, start_b: bytes, dp_bits: int = 16, hash_config: HashConfig = DEFAULT_CONFIG):
	while dp_bits > 0:
		print("starters", start_a.hex(), start_b.hex())
		start_a, start_b = finalize_inner(
			hash_fn(start_a, hash_config), hash_fn(start_b, hash_config), dp_bits, hash_config
		)
		dp_bits -= 8
	print(f"Collision: {bytes_to_ascii(start_a)} {bytes_to_ascii(start_b)} -> {hash_fn(start_a, hash_config).hex()}")
	return start_a, start_b


def main():
	parser = argparse.ArgumentParser(description="Finalize collision search by finding exact collision")
	parser.add_argument("start_a", help="Starting point for chain A (hex)")
	parser.add_argument("start_b", help="Starting point for chain B (hex)")
	parser.add_argument(
		"--dp-bits", type=int, default=16, help="Number of leading zero bits for distinguished points (default: 16)"
	)
	parser.add_argument(
		"--hash-prefix-bytes",
		type=int,
		default=8,
		help="Number of prefix bytes from SHA256 hash (0-32, default: 8 for backward compatibility)",
	)
	parser.add_argument(
		"--hash-suffix-bytes",
		type=int,
		default=0,
		help="Number of suffix bytes from SHA256 hash (0-32, default: 0). If specified, middle bytes are skipped.",
	)
	args = parser.parse_args()

	hash_config = HashConfig(prefix_bytes=args.hash_prefix_bytes, suffix_bytes=args.hash_suffix_bytes)
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
