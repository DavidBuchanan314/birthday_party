"""Configuration for hash truncation in OCL SHA256 miner."""


class HashConfig:
	"""Configuration for hash truncation scheme with prefix and optional suffix support."""

	def __init__(self, prefix_bytes: int, suffix_bytes: int = 0):
		"""
		Initialize hash configuration.

		Args:
			prefix_bytes: Number of bytes to take from the start of SHA256 hash (0-27)
			suffix_bytes: Number of bytes to take from the end of SHA256 hash (0-27)
				If both are specified, the middle bytes are skipped.
				
		Note:
			Total bytes (prefix_bytes + suffix_bytes) is limited to 27 to ensure the
			ASCII representation (54 chars = 13.5 words) plus SHA256 padding fits
			within a single 64-byte (16-word) SHA256 block.
		"""
		self.prefix_bytes = prefix_bytes
		self.suffix_bytes = suffix_bytes

		# Validation
		if not (0 <= prefix_bytes <= 32):
			raise ValueError(f"prefix_bytes must be 0-32, got {prefix_bytes}")
		if not (0 <= suffix_bytes <= 32):
			raise ValueError(f"suffix_bytes must be 0-32, got {suffix_bytes}")
		if prefix_bytes + suffix_bytes < 1:
			raise ValueError("Must have at least 1 byte total (prefix + suffix)")
		if prefix_bytes + suffix_bytes > 27:
			raise ValueError(
				f"Total bytes ({prefix_bytes} + {suffix_bytes}) cannot exceed 27. "
				"This limit ensures the ASCII representation plus SHA256 padding fits in a single block."
			)
		if suffix_bytes > 0 and prefix_bytes + suffix_bytes >= 32:
			raise ValueError("When using suffix, prefix + suffix must be < 32 (must skip at least 1 byte)")

	@property
	def total_bytes(self) -> int:
		"""Total number of bytes in truncated hash."""
		return self.prefix_bytes + self.suffix_bytes

	@property
	def num_uint32s(self) -> int:
		"""Number of uint32s needed to store truncated hash (rounded up)."""
		return (self.total_bytes + 3) // 4

	def truncate_hash(self, full_hash: bytes) -> bytes:
		"""
		Truncate a full SHA256 hash according to this config.

		Args:
			full_hash: Full 32-byte SHA256 hash

		Returns:
			Truncated hash (prefix_bytes + suffix_bytes long)
		"""
		if len(full_hash) != 32:
			raise ValueError(f"Expected 32-byte hash, got {len(full_hash)} bytes")

		if self.suffix_bytes == 0:
			# Prefix-only (simple case)
			return full_hash[: self.prefix_bytes]
		else:
			# Prefix + suffix (skip middle)
			return full_hash[: self.prefix_bytes] + full_hash[-self.suffix_bytes :]

	def get_opencl_defines(self) -> str:
		"""Generate OpenCL compiler flags for this config."""
		return f"-DHASH_PREFIX_BYTES={self.prefix_bytes} -DHASH_SUFFIX_BYTES={self.suffix_bytes}"

	def __repr__(self):
		if self.suffix_bytes == 0:
			return f"HashConfig(prefix={self.prefix_bytes}B)"
		else:
			return f"HashConfig(prefix={self.prefix_bytes}B, suffix={self.suffix_bytes}B)"

	def __eq__(self, other):
		if not isinstance(other, HashConfig):
			return False
		return self.prefix_bytes == other.prefix_bytes and self.suffix_bytes == other.suffix_bytes


# Default configuration (backward compatible with original 8-byte truncation)
DEFAULT_CONFIG = HashConfig(prefix_bytes=8)
