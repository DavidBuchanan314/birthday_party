#!/usr/bin/env python3
"""
Meta-optimizer for WORK_SIZE and STEPS_PER_TASK parameters.
Tests different parameter combinations to find optimal performance.
"""

import json
from typing import Dict, List, Optional
from .mine import PollardRhoMiner


class ParamOptimizer:
	def __init__(self):
		self.results: List[Dict] = []
		self.best_result: Optional[Dict] = None

	def run_benchmark(
		self,
		work_size: int,
		steps_per_task: int,
		dp_bits: int = 16,
		num_iterations: int = 10,
	) -> Dict:
		"""Run a single benchmark with given parameters."""
		print(f"\nTesting WORK_SIZE={hex(work_size)}, STEPS_PER_TASK={hex(steps_per_task)}")

		try:
			# Create miner with specific parameters
			miner = PollardRhoMiner(work_size=work_size, steps_per_task=steps_per_task)

			# Run multiple iterations to get average performance
			total_rate = 0.0
			total_dps = 0
			for _ in range(num_iterations):
				results, rate = miner.mine(dp_bits=dp_bits)
				total_rate += rate
				total_dps += len(results)

			avg_rate = total_rate / num_iterations
			avg_dps = total_dps / num_iterations

			result = {
				"work_size": work_size,
				"steps_per_task": steps_per_task,
				"hash_rate": avg_rate,
				"avg_dps_per_call": avg_dps,
				"total_iterations": num_iterations,
				"success": True,
			}

			print(f"  → {avg_rate:,.0f} H/s, {avg_dps:.1f} DPs/call")

			return result

		except Exception as e:
			print(f"  → Error: {e}")
			return {
				"work_size": work_size,
				"steps_per_task": steps_per_task,
				"success": False,
				"error": str(e),
			}

	def optimize(
		self,
		work_sizes: Optional[List[int]] = None,
		steps_per_task_values: Optional[List[int]] = None,
		dp_bits: int = 16,
		num_iterations: int = 10,
		output_file: str = "optimization_results.json",
	) -> tuple[List[Dict], Optional[Dict]]:
		"""Run optimization across parameter space."""

		# Default parameter ranges
		if work_sizes is None:
			work_sizes = [
				0x1000,
				0x2000,
				0x4000,
				0x8000,
				0x10000,
				0x20000,
				0x40000,
			]

		if steps_per_task_values is None:
			steps_per_task_values = [
				0x10,
				0x20,
				0x40,
				0x80,
				0x100,
				0x200,
				0x400,
				0x800,
			]

		total_configs = len(work_sizes) * len(steps_per_task_values)
		print(f"Starting optimization with {total_configs} configurations")
		print(f"DP bits: {dp_bits}")
		print(f"Iterations per config: {num_iterations}")
		print(f"WORK_SIZE values: {[hex(x) for x in work_sizes]}")
		print(f"STEPS_PER_TASK values: {[hex(x) for x in steps_per_task_values]}")

		config_num = 0
		for work_size in work_sizes:
			for steps_per_task in steps_per_task_values:
				config_num += 1
				print(f"\n[{config_num}/{total_configs}]", end=" ")

				result = self.run_benchmark(work_size, steps_per_task, dp_bits, num_iterations)
				self.results.append(result)

				if result["success"]:
					if self.best_result is None or result["hash_rate"] > self.best_result["hash_rate"]:
						self.best_result = result
						print(
							f"  ★ NEW BEST: {result['hash_rate']:,} H/s "
							f"(WORK_SIZE={hex(work_size)}, "
							f"STEPS_PER_TASK={hex(steps_per_task)})"
						)

				# Save intermediate results
				self._save_results(output_file)

		self._print_summary()
		return self.results, self.best_result

	def _save_results(self, output_file: str):
		"""Save results to JSON file."""
		with open(output_file, "w") as f:
			json.dump({"results": self.results, "best": self.best_result}, f, indent=2)

	def _print_summary(self):
		"""Print optimization summary."""
		print("\n" + "=" * 70)
		print("OPTIMIZATION COMPLETE")
		print("=" * 70)

		if self.best_result:
			print("\nBest configuration:")
			print(f"  WORK_SIZE = {hex(self.best_result['work_size'])}")
			print(f"  STEPS_PER_TASK = {hex(self.best_result['steps_per_task'])}")
			print(f"  Hash rate: {self.best_result['hash_rate']:,} H/s")

			print("\nTo apply these settings, update mine.py:")
			print(f"  WORK_SIZE = {hex(self.best_result['work_size'])}  " f"(currently: defaults)")
			print(f"  STEPS_PER_TASK = {hex(self.best_result['steps_per_task'])}  " f"(currently: defaults)")

			# Show top 5 configurations
			successful = [r for r in self.results if r["success"]]
			if len(successful) > 1:
				print("\nTop 5 configurations:")
				top5 = sorted(successful, key=lambda x: x["hash_rate"], reverse=True)[:5]
				for i, r in enumerate(top5, 1):
					print(
						f"  {i}. {r['hash_rate']:>12,} H/s  "
						f"WORK_SIZE={hex(r['work_size']):>8}  "
						f"STEPS_PER_TASK={hex(r['steps_per_task']):>6}"
					)
		else:
			print("\nNo successful runs!")

		success_rate = sum(1 for r in self.results if r["success"]) / len(self.results)
		print(f"\nSuccess rate: {success_rate*100:.1f}% ({len(self.results)} total)")


def main():
	import argparse

	parser = argparse.ArgumentParser(description="Optimize WORK_SIZE and STEPS_PER_TASK parameters")
	parser.add_argument(
		"--dp-bits",
		type=int,
		default=24,
		help="Distinguished point difficulty in bits (default: 24)",
	)
	parser.add_argument(
		"--iterations",
		type=int,
		default=10,
		help="Number of iterations per configuration (default: 10)",
	)
	parser.add_argument(
		"--output",
		type=str,
		default="optimization_results.json",
		help="Output file for results (default: optimization_results.json)",
	)
	parser.add_argument("--quick", action="store_true", help="Quick test with fewer parameter combinations")

	args = parser.parse_args()

	optimizer = ParamOptimizer()

	if args.quick:
		# Quick test mode - fewer combinations
		print("Quick test mode - testing subset of parameters\n")
		work_sizes = [0x4000, 0x8000, 0x10000]
		steps_per_task_values = [0x80, 0x100, 0x200, 0x400]
		optimizer.optimize(
			work_sizes=work_sizes,
			steps_per_task_values=steps_per_task_values,
			dp_bits=args.dp_bits,
			num_iterations=args.iterations,
			output_file=args.output,
		)
	else:
		optimizer.optimize(
			dp_bits=args.dp_bits,
			num_iterations=args.iterations,
			output_file=args.output,
		)


if __name__ == "__main__":
	main()
