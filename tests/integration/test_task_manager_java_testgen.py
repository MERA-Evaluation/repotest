"""
Integration tests for TaskManagerJavaTestGen.

This module provides tests for the TaskManagerJavaTestGen class, validating
both sequential and parallel execution modes for Java test generation.
"""

import json
import os
import time
from pathlib import Path
from typing import Any, Dict, List

import pandas as pd
import pytest
from repotest.constants import disable_stdout_logs, enable_stdout_logs
from repotest.manager.java_testgen_task_manager import TaskManagerJavaTestGen
from tqdm import tqdm


class ExtractFromTagJava:
    """Utility class for extracting Java code from text responses."""

    @staticmethod
    def _extract_java(text: str) -> str:
        """
        Extract Java code from text, handling markdown code blocks.

        Parameters
        ----------
        text : str
            Text potentially containing Java code in markdown blocks

        Returns
        -------
        str
            Cleaned Java code
        """
        if "```java" in text:
            text = text.split("```java")[1]
            if "```" in text:
                text = text.split("```")[0]
        elif "```" in text:
            # Handle generic code blocks
            parts = text.split("```")
            if len(parts) >= 3:  # text before, code, text after
                text = parts[1]
        return text.strip()


def prepare_tasks_from_dataframe(df: pd.DataFrame) -> List[Dict[str, Any]]:
    """
    Prepare task records from dataframe for TaskManagerJavaTestGen.

    Parameters
    ----------
    df : pd.DataFrame
        Input dataframe with Java testgen data

    Returns
    -------
    List[Dict[str, Any]]
        List of prepared task records with extracted code
    """
    tasks = []
    for _, row in tqdm(df.iterrows(), total=len(df), desc="Preparing tasks"):
        doc = row["doc"]
        meta = doc["meta"]

        # Extract generated code using proper extraction
        code = ""
        if "resps" in row and row["resps"] and row["resps"][0]:
            code = row["resps"][0][0]
            code = ExtractFromTagJava._extract_java(code)

        task = {
            "doc_id": row.get("doc_id"),
            "instance_id": meta.get("instance_id"),
            "repo": meta["repo"],
            "base_commit": meta["base_commit"],
            "image_name": meta["image_name"],
            "test_command": meta["test_command"],
            "fn_test": meta["fn_test"],
            "source_code": meta["source_code"],
            "generated_code": code,  # Pre-extracted and cleaned code
            # Store original metrics for comparison
            "original_pass@1": row.get("pass@1", 0),
            "original_compile@1": row.get("compilation_rate", 0),
        }
        tasks.append(task)

    return tasks


def validate_task_results(tasks: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Validate and summarize task results.

    Parameters
    ----------
    tasks : List[Dict[str, Any]]
        List of completed task records

    Returns
    -------
    Dict[str, Any]
        Summary statistics and validation results
    """
    total_tasks = len(tasks)
    if total_tasks == 0:
        return {"error": "No tasks to validate"}

    # Count successful tasks
    successful_tasks = sum(1 for task in tasks if task.get("status", 0) == 1)

    # Calculate metrics
    pass_at_1_values = [task.get("pass@1", 0) for task in tasks]
    compile_at_1_values = [task.get("compile@1", 0) for task in tasks]

    avg_pass = sum(pass_at_1_values) / total_tasks
    avg_compile = sum(compile_at_1_values) / total_tasks

    # Original metrics for comparison
    original_pass_values = [task.get("original_pass@1", 0) for task in tasks]
    original_compile_values = [task.get("original_compile@1", 0) for task in tasks]

    orig_avg_pass = sum(original_pass_values) / total_tasks
    orig_avg_compile = sum(original_compile_values) / total_tasks

    # Calculate differences
    pass_diff = abs(avg_pass - orig_avg_pass)
    compile_diff = abs(avg_compile - orig_avg_compile)

    return {
        "total_tasks": total_tasks,
        "successful_tasks": successful_tasks,
        "success_rate": successful_tasks / total_tasks,
        "avg_pass@1": avg_pass,
        "avg_compile@1": avg_compile,
        "original_avg_pass@1": orig_avg_pass,
        "original_avg_compile@1": orig_avg_compile,
        "pass@1_difference": pass_diff,
        "compile@1_difference": compile_diff,
        "errors": [task.get("error", "") for task in tasks if task.get("error")],
    }


@pytest.mark.integration
def test_task_manager_java_testgen_sequential():
    """
    Test TaskManagerJavaTestGen with sequential execution.

    This test validates the basic functionality of TaskManagerJavaTestGen
    using sequential (single-threaded) execution.
    """
    # Use relative path to test data file
    script_dir = Path(__file__).parent
    input_jsonl = script_dir / "data" / "samples_java_testgen.jsonl"

    # Check if input file exists
    if not input_jsonl.exists():
        pytest.skip(f"Input file not found: {input_jsonl}")

    df = pd.read_json(input_jsonl, lines=True)

    # Use first 8 samples for quick sequential test
    df_subset = df.head(8)
    tasks = prepare_tasks_from_dataframe(df_subset)

    # Get actual number of prepared tasks
    expected_tasks = len(tasks)

    # Create TaskManager with sequential execution
    task_manager = TaskManagerJavaTestGen(
        mode="docker",
        n_jobs=1,  # Sequential execution
        raise_exception=True,
        timeout=300,
    )

    enable_stdout_logs()

    # Run evaluation with time measurement
    start_time = time.time()
    task_manager.eval_task_list(tasks)
    end_time = time.time()
    execution_time = end_time - start_time

    # Validate results
    results = validate_task_results(tasks)

    print("Sequential test results:")
    print(f"Execution time: {execution_time:.2f} seconds")
    print(f"Total tasks: {results['total_tasks']}")
    print(f"Successful tasks: {results['successful_tasks']}")
    print(f"Success rate: {results['success_rate']:.2%}")
    print(f"Average pass@1: {results['avg_pass@1']:.3f}")
    print(f"Average compile@1: {results['avg_compile@1']:.3f}")
    print(f"Original pass@1: {results['original_avg_pass@1']:.3f}")
    print(f"Original compile@1: {results['original_avg_compile@1']:.3f}")
    print(f"Pass@1 difference: {results['pass@1_difference']:.3f}")
    print(f"Compile@1 difference: {results['compile@1_difference']:.3f}")

    # Assertions
    assert (
        results["total_tasks"] == expected_tasks
    ), f"Should process {expected_tasks} tasks"
    assert results["success_rate"] > 0, "Should have some successful tasks"

    # Check that all tasks have required fields
    for task in tasks:
        assert "status" in task, "Task should have status field"
        assert "pass@1" in task, "Task should have pass@1 field"
        assert "compile@1" in task, "Task should have compile@1 field"

    print(results["pass@1_difference"])
    print(results["compile@1_difference"])
    # Check metrics consistency (allow some tolerance for code extraction differences)
    assert (
        results["pass@1_difference"] <= 0.01
    ), f"Pass@1 difference too large: {results['pass@1_difference']:.3f}"
    assert (
        results["compile@1_difference"] <= 0.01
    ), f"Compile@1 difference too large: {results['compile@1_difference']:.3f}"


@pytest.mark.integration
def test_task_manager_java_testgen_parallel():
    """
    Test TaskManagerJavaTestGen with parallel execution.

    This test validates the parallel execution functionality and ensures
    thread-safety when multiple workers are processing tasks simultaneously.
    """
    # Use relative path to test data file
    script_dir = Path(__file__).parent
    input_jsonl = script_dir / "data" / "samples_java_testgen.jsonl"

    # Check if input file exists
    if not input_jsonl.exists():
        pytest.skip(f"Input file not found: {input_jsonl}")

    df = pd.read_json(input_jsonl, lines=True)

    # Use first 8 samples for parallel test
    df_subset = df.head(8)
    tasks = prepare_tasks_from_dataframe(df_subset)

    # Create TaskManager with parallel execution
    task_manager = TaskManagerJavaTestGen(
        mode="docker",
        n_jobs=3,  # Parallel execution for evaluation
        raise_exception=True,
        timeout=300,
    )

    # enable_stdout_logs()
    # ToDo: remove this
    disable_stdout_logs()

    # Run evaluation with time measurement
    start_time = time.time()
    task_manager.eval_task_list(tasks)
    end_time = time.time()
    execution_time = end_time - start_time

    # Validate results
    results = validate_task_results(tasks)

    print("Parallel test results:")
    print(f"Execution time: {execution_time:.2f} seconds")
    print(f"Total tasks: {results['total_tasks']}")
    print(f"Successful tasks: {results['successful_tasks']}")
    print(f"Success rate: {results['success_rate']:.2%}")
    print(f"Average pass@1: {results['avg_pass@1']:.3f}")
    print(f"Average compile@1: {results['avg_compile@1']:.3f}")
    print(f"Original pass@1: {results['original_avg_pass@1']:.3f}")
    print(f"Original compile@1: {results['original_avg_compile@1']:.3f}")
    print(f"Pass@1 difference: {results['pass@1_difference']:.3f}")
    print(f"Compile@1 difference: {results['compile@1_difference']:.3f}")

    # Assertions
    assert results["total_tasks"] == 8, "Should process 8 tasks"
    assert results["success_rate"] > 0, "Should have some successful tasks"

    # Check that all tasks have required fields
    for task in tasks:
        assert "status" in task, "Task should have status field"
        assert "pass@1" in task, "Task should have pass@1 field"
        assert "compile@1" in task, "Task should have compile@1 field"

    # Check metrics consistency (allow some tolerance for code extraction differences)
    assert (
        results["pass@1_difference"] <= 0.01
    ), f"Pass@1 difference too large: {results['pass@1_difference']:.3f}"
    assert (
        results["compile@1_difference"] <= 0.01
    ), f"Compile@1 difference too large: {results['compile@1_difference']:.3f}"

    # Additional parallel-specific checks
    # Verify that no tasks have conflicting results that would indicate race conditions
    task_ids = [task.get("doc_id") for task in tasks]
    assert len(set(task_ids)) == len(task_ids), "All task IDs should be unique"


@pytest.mark.integration
def test_task_manager_comparison_sequential_vs_parallel():
    """
    Compare results between sequential and parallel execution.

    This test ensures that parallel execution produces the same results
    as sequential execution, validating thread-safety.
    """
    # Use relative path to test data file
    script_dir = Path(__file__).parent
    input_jsonl = script_dir / "data" / "samples_java_testgen.jsonl"

    # Check if input file exists
    if not input_jsonl.exists():
        pytest.skip(f"Input file not found: {input_jsonl}")

    df = pd.read_json(input_jsonl, lines=True)

    # Use first 6 samples for comparison
    df_subset = df.head(6)

    # Sequential execution
    tasks_sequential = prepare_tasks_from_dataframe(df_subset)
    task_manager_seq = TaskManagerJavaTestGen(
        mode="docker", n_jobs=1, raise_exception=True, timeout=300
    )

    enable_stdout_logs()
    print("Running sequential execution...")
    start_time_seq = time.time()
    task_manager_seq.eval_task_list(tasks_sequential)
    end_time_seq = time.time()
    execution_time_seq = end_time_seq - start_time_seq
    results_seq = validate_task_results(tasks_sequential)

    # Parallel execution
    tasks_parallel = prepare_tasks_from_dataframe(df_subset)
    task_manager_par = TaskManagerJavaTestGen(
        mode="docker", n_jobs=2, raise_exception=True, timeout=300
    )

    print("Running parallel execution...")
    start_time_par = time.time()
    task_manager_par.eval_task_list(tasks_parallel)
    end_time_par = time.time()
    execution_time_par = end_time_par - start_time_par
    results_par = validate_task_results(tasks_parallel)

    # Compare results
    print("Comparison results:")
    print(
        f"Sequential - Time: {execution_time_seq:.2f}s, Success rate: {results_seq['success_rate']:.2%}, Pass@1: {results_seq['avg_pass@1']:.3f}, Compile@1: {results_seq['avg_compile@1']:.3f}"
    )
    print(
        f"Parallel   - Time: {execution_time_par:.2f}s, Success rate: {results_par['success_rate']:.2%}, Pass@1: {results_par['avg_pass@1']:.3f}, Compile@1: {results_par['avg_compile@1']:.3f}"
    )
    print(f"Speedup: {execution_time_seq / execution_time_par:.2f}x")

    # Assertions - results should be identical or very close
    success_rate_diff = abs(results_seq["success_rate"] - results_par["success_rate"])
    pass_diff = abs(results_seq["avg_pass@1"] - results_par["avg_pass@1"])
    compile_diff = abs(results_seq["avg_compile@1"] - results_par["avg_compile@1"])

    print(
        f"Differences - Success rate: {success_rate_diff:.3f}, Pass@1: {pass_diff:.3f}, Compile@1: {compile_diff:.3f}"
    )

    # Allow small differences due to potential timing variations
    assert (
        success_rate_diff <= 0.01
    ), f"Success rate difference too large: {success_rate_diff:.3f}"
    assert pass_diff <= 0.01, f"Pass@1 difference too large: {pass_diff:.3f}"
    assert compile_diff <= 0.01, f"Compile@1 difference too large: {compile_diff:.3f}"

    # Both should process the same number of tasks
    assert (
        results_seq["total_tasks"] == results_par["total_tasks"]
    ), "Should process same number of tasks"


@pytest.mark.integration
@pytest.mark.slow
def test_task_manager_java_testgen_full():
    """
    Light version of full test using TaskManagerJavaTestGen.

    This test runs the TaskManager with a larger subset to validate
    performance and stability with more tasks.
    """
    # Use relative path to test data file
    script_dir = Path(__file__).parent
    input_jsonl = script_dir / "data" / "samples_java_testgen.jsonl"

    # Check if input file exists
    if not input_jsonl.exists():
        pytest.skip(f"Input file not found: {input_jsonl}")

    df = pd.read_json(input_jsonl, lines=True)

    # Use all available samples for light full test
    tasks = prepare_tasks_from_dataframe(df)
    actual_tasks_num = len(tasks)

    # Create TaskManager with moderate parallelization
    task_manager = TaskManagerJavaTestGen(
        mode="docker",
        n_jobs=15,  # Moderate parallelization
        raise_exception=True,
        timeout=300,
    )

    enable_stdout_logs()

    # Run evaluation with time measurement
    start_time = time.time()
    task_manager.eval_task_list(tasks)
    end_time = time.time()
    execution_time = end_time - start_time

    # Validate results
    results = validate_task_results(tasks)

    print("Light full test results:")
    print(
        f"Execution time: {execution_time:.2f} seconds ({execution_time/60:.1f} minutes)"
    )
    print(f"Total tasks: {results['total_tasks']}")
    print(f"Successful tasks: {results['successful_tasks']}")
    print(f"Success rate: {results['success_rate']:.2%}")
    print(f"Average pass@1: {results['avg_pass@1']:.3f}")
    print(f"Average compile@1: {results['avg_compile@1']:.3f}")
    print(f"Original pass@1: {results['original_avg_pass@1']:.3f}")
    print(f"Original compile@1: {results['original_avg_compile@1']:.3f}")
    print(f"Pass@1 difference: {results['pass@1_difference']:.3f}")
    print(f"Compile@1 difference: {results['compile@1_difference']:.3f}")

    # Assertions
    assert (
        results["total_tasks"] == actual_tasks_num
    ), f"Should process {actual_tasks_num} tasks"
    assert results["success_rate"] > 0, "Should have some successful tasks"

    # Check metrics consistency with a bit more tolerance for larger dataset
    assert (
        results["pass@1_difference"] <= 0.01
    ), f"Pass@1 difference too large: {results['pass@1_difference']:.3f}"
    assert (
        results["compile@1_difference"] <= 0.01
    ), f"Compile@1 difference too large: {results['compile@1_difference']:.3f}"

    # Performance check - should complete within reasonable time
    # (This is implicitly tested by the test not timing out)

    # Save results for inspection
    output_dir = "outputs/task_manager_java_testgen_light_full"
    os.makedirs(output_dir, exist_ok=True)

    with open(os.path.join(output_dir, "task_results.json"), "w") as f:
        json.dump(tasks, f, indent=2)

    with open(os.path.join(output_dir, "summary.json"), "w") as f:
        json.dump(results, f, indent=2)


if __name__ == "__main__":
    # Allow running tests directly
    test_task_manager_java_testgen_full()
