"""Finalize distinguished point collisions.

This module reuses the finalize implementation from ocl_sha256 since the logic
is identical - it doesn't matter whether the DPs were found with OpenCL or WebGPU.
"""

from ..ocl_sha256.finalize import main

if __name__ == "__main__":
	main()
