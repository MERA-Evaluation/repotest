#!/usr/bin/env python3
"""
Script for running RealCode evaluation tests with different configurations.

This script provides a convenient way to run evaluation tests with
various parameters and configurations.
"""

import argparse
import subprocess
import sys
from pathlib import Path


def run_command(cmd, description):
    """Run a command and handle errors."""
    print(f"\n{'='*60}")
    print(f"Running: {description}")
    print(f"Command: {' '.join(cmd)}")
    print(f"{'='*60}")

    try:
        _ = subprocess.run(cmd, check=True, capture_output=False)
        print(f"✅ {description} completed successfully")
        return True
    except subprocess.CalledProcessError as e:
        print(f"❌ {description} failed with exit code {e.returncode}")
        return False


def main():
    parser = argparse.ArgumentParser(
        description="Run RealCode evaluation tests",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python run_tests.py --light                  # Run light test (100 samples)
  python run_tests.py --local                  # Run local mode test (5 samples)
  python run_tests.py --full                   # Run full test (all samples)
  python run_tests.py --unit                   # Run only unit tests
  python run_tests.py --java-light             # Run Java testgen light test (10 samples)
  python run_tests.py --java-full              # Run Java testgen full test (227 samples)
  python run_tests.py --java-unit              # Run Java testgen unit tests
  python run_tests.py --task-manager-light     # Run TaskManager light tests (sequential + parallel)
  python run_tests.py --task-manager-comparison # Run TaskManager comparison test
  python run_tests.py --all                    # Run all tests
  python run_tests.py --light --verbose        # Run with detailed output
        """,
    )

    parser.add_argument(
        "--light", action="store_true", help="Run light integration test (100 samples)"
    )
    parser.add_argument(
        "--local",
        action="store_true",
        help="Run local mode test (5 samples, no Docker)",
    )
    parser.add_argument(
        "--full",
        action="store_true",
        help="Run full integration test (all samples, takes hours)",
    )
    parser.add_argument(
        "--unit", action="store_true", help="Run unit tests for metrics validation"
    )
    parser.add_argument(
        "--java-light",
        action="store_true",
        help="Run light Java testgen integration test (10 samples)",
    )
    parser.add_argument(
        "--java-full",
        action="store_true",
        help="Run full Java testgen integration test (all samples)",
    )
    parser.add_argument(
        "--java-unit",
        action="store_true",
        help="Run unit tests for Java testgen validation",
    )
    parser.add_argument(
        "--task-manager-light",
        action="store_true",
        help="Run TaskManagerJavaTestGen light tests (sequential + parallel)",
    )
    parser.add_argument(
        "--task-manager-comparison",
        action="store_true",
        help="Run TaskManagerJavaTestGen comparison test (sequential vs parallel)",
    )
    parser.add_argument("--all", action="store_true", help="Run all available tests")
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Enable verbose output with progress bars",
    )
    parser.add_argument(
        "--no-capture",
        "-s",
        action="store_true",
        help="Disable output capture (show print statements and progress bars)",
    )
    parser.add_argument(
        "--markers",
        "-m",
        help="Run tests matching specific markers (e.g., 'integration', 'not slow')",
    )

    args = parser.parse_args()

    # Default to light test if no specific test is chosen
    if not any(
        [
            args.light,
            args.local,
            args.full,
            args.unit,
            args.java_light,
            args.java_full,
            args.java_unit,
            args.task_manager_light,
            args.task_manager_comparison,
            args.all,
            args.markers,
        ]
    ):
        args.light = True
        print("No specific test selected, defaulting to --light")

    # Base pytest command
    base_cmd = ["python", "-m", "pytest"]

    # Add verbose flag
    if args.verbose:
        base_cmd.append("-v")

    # Add no-capture flag
    if args.no_capture:
        base_cmd.append("-s")

    # Get the directory containing this script
    script_dir = Path(__file__).parent

    success_count = 0
    total_count = 0

    # Run unit tests
    if args.unit or args.all:
        total_count += 1
        cmd = base_cmd + [str(script_dir / "test_metrics_validation.py")]
        if run_command(cmd, "Unit tests for metrics validation"):
            success_count += 1

    # Run Java testgen unit tests
    if args.java_unit or args.all:
        total_count += 1
        cmd = base_cmd + [str(script_dir / "test_java_testgen_validation.py")]
        if run_command(cmd, "Unit tests for Java testgen validation"):
            success_count += 1

    # Run light test
    if args.light or args.all:
        total_count += 1
        cmd = base_cmd + [
            f"{script_dir}/test_realcode_evaluation.py::test_realcode_evaluation_light"
        ]
        if run_command(cmd, "Light integration test (100 samples)"):
            success_count += 1

    # Run local test
    if args.local or args.all:
        total_count += 1
        cmd = base_cmd + [
            f"{script_dir}/test_realcode_evaluation.py::test_realcode_evaluation_local_mode"
        ]
        if run_command(cmd, "Local mode test (5 samples)"):
            success_count += 1

    # Run Java testgen light test
    if args.java_light or args.all:
        total_count += 1
        cmd = base_cmd + [
            f"{script_dir}/test_java_testgen_evaluation.py::test_java_testgen_evaluation_light"
        ]
        if run_command(cmd, "Java testgen light test (10 samples)"):
            success_count += 1

    # Run TaskManager light tests (sequential and parallel)
    if args.task_manager_light or args.all:
        total_count += 1
        cmd = base_cmd + [
            f"{script_dir}/test_task_manager_java_testgen.py::test_task_manager_java_testgen_sequential"
        ]
        if run_command(cmd, "TaskManager sequential test (5 samples)"):
            success_count += 1

        total_count += 1
        cmd = base_cmd + [
            f"{script_dir}/test_task_manager_java_testgen.py::test_task_manager_java_testgen_parallel"
        ]
        if run_command(cmd, "TaskManager parallel test (8 samples)"):
            success_count += 1

    # Run TaskManager comparison test
    if args.task_manager_comparison or args.all:
        total_count += 1
        cmd = base_cmd + [
            f"{script_dir}/test_task_manager_java_testgen.py::test_task_manager_comparison_sequential_vs_parallel"
        ]
        if run_command(
            cmd, "TaskManager sequential vs parallel comparison (6 samples)"
        ):
            success_count += 1

    # Run full test
    if args.full or args.all:
        total_count += 1
        print("\n⚠️  WARNING: Full test may take 1-3 hours to complete!")
        response = input("Do you want to continue? (y/N): ")
        if response.lower() in ["y", "yes"]:
            cmd = base_cmd + [
                f"{script_dir}/test_realcode_evaluation.py::test_realcode_evaluation_full"
            ]
            if run_command(cmd, "Full integration test (all samples)"):
                success_count += 1
        else:
            print("Skipping full test")

    # Run Java testgen full test
    if args.java_full or args.all:
        total_count += 1
        print(
            "\n⚠️  WARNING: Java testgen full test may take significant time to complete!"
        )
        response = input("Do you want to continue? (y/N): ")
        if response.lower() in ["y", "yes"]:
            cmd = base_cmd + [
                f"{script_dir}/test_java_testgen_evaluation.py::test_java_testgen_evaluation_full"
            ]
            if run_command(cmd, "Java testgen full test (all 227 samples)"):
                success_count += 1
        else:
            print("Skipping Java testgen full test")

    # Run with markers
    if args.markers:
        total_count += 1
        cmd = base_cmd + ["-m", args.markers, str(script_dir)]
        if run_command(cmd, f"Tests matching markers: {args.markers}"):
            success_count += 1

    # Summary
    print(f"\n{'='*60}")
    print("TEST SUMMARY")
    print(f"{'='*60}")
    print(f"Passed: {success_count}/{total_count}")

    if success_count == total_count:
        print("🎉 All tests passed!")
        return 0
    else:
        print(f"❌ {total_count - success_count} test(s) failed")
        return 1


if __name__ == "__main__":
    sys.exit(main())
