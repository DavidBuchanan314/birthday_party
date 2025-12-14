"""Configuration for hash truncation in OCL SHA256 miner."""


class HashConfig:
	"""Configuration for hash truncation scheme (prefix-only for now)."""

	def __init__(self, prefix_bytes: int):
		"""
		Initialize hash configuration.

		Args:
			prefix_bytes: Number of bytes to take from the start of SHA256 hash (1-32)
		"""
		self.prefix_bytes = prefix_bytes
		self.suffix_bytes = 0  # Reserved for future prefix+suffix support

		# Validation
		if not (1 <= prefix_bytes <= 32):
			raise ValueError(f"prefix_bytes must be 1-32, got {prefix_bytes}")

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
			Truncated hash (prefix_bytes long)
		"""
		if len(full_hash) != 32:
			raise ValueError(f"Expected 32-byte hash, got {len(full_hash)} bytes")

		# Prefix-only for now
		return full_hash[: self.prefix_bytes]

	def get_opencl_defines(self) -> str:
		"""Generate OpenCL compiler flags for this config."""
		return f"-DHASH_PREFIX_BYTES={self.prefix_bytes}"

	def __repr__(self):
		return f"HashConfig(prefix={self.prefix_bytes}B)"

	def __eq__(self, other):
		if not isinstance(other, HashConfig):
			return False
		return self.prefix_bytes == other.prefix_bytes


# Default configuration (backward compatible with original 8-byte truncation)
DEFAULT_CONFIG = HashConfig(prefix_bytes=8)
