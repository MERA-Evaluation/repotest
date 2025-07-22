"""
Integration tests for Java test generation evaluation pipeline.

This module provides tests for evaluating Java test generation using the
TaskManagerRealcode-like approach but adapted for Java test generation tasks.
"""

import json
import os
from pathlib import Path
from typing import Any, Dict, List

import pandas as pd
import pytest
from repotest.constants import enable_stdout_logs
from repotest.core.docker.java import JavaDockerRepo
from repotest.utils.git.git_diff_wrapper import GitDiffWrapper
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


def evaluate_java_test(
    repo: str,
    base_commit: str,
    image_name: str,
    test_command: str,
    fn_test: str,
    source_code: str,
    code: str,
    timeout: int = 300,
) -> Dict[str, Any]:
    """
    Evaluate a single Java test generation task.

    Parameters
    ----------
    repo : str
        Repository name
    base_commit : str
        Git commit hash
    image_name : str
        Docker image name
    test_command : str
        Command to run tests
    fn_test : str
        Test file name
    source_code : str
        Source code being tested
    code : str
        Generated test code
    timeout : int, optional
        Timeout for test execution, by default 300

    Returns
    -------
    Dict[str, Any]
        Test execution results
    """
    repo_instance = JavaDockerRepo(
        repo=repo, base_commit=base_commit, image_name=image_name, cache_mode="volume"
    )

    repo_instance.clean()
    git_diff_wrapper = GitDiffWrapper(repo=repo_instance, base_commit=base_commit)
    git_diff_wrapper.change_test(fn_test=fn_test, str_test=code, str_source=source_code)
    git_diff_wrapper.fix_pom_file()
    git_diff = git_diff_wrapper.git_diff()
    repo_instance.clean()
    repo_instance.apply_patch(git_diff + "\n")
    result = repo_instance.run_test(test_command, timeout=timeout)

    return result


def process_java_testgen_results(tasks: List[Dict[str, Any]]) -> Dict[str, float]:
    """
    Process Java test generation evaluation results.

    Parameters
    ----------
    tasks : List[Dict[str, Any]]
        List of evaluated tasks with results

    Returns
    -------
    Dict[str, float]
        Aggregated metrics
    """
    if not tasks:
        return {"pass@1": 0.0, "compile@1": 0.0, "num_samples": 0}

    pass_at_1 = sum(task.get("pass@1", 0) for task in tasks) / len(tasks)
    compile_at_1 = sum(task.get("compile@1", 0) for task in tasks) / len(tasks)

    return {"pass@1": pass_at_1, "compile@1": compile_at_1, "num_samples": len(tasks)}


def prepare_java_testgen_tasks(df: pd.DataFrame) -> List[Dict[str, Any]]:
    """
    Prepare Java test generation tasks from dataframe.

    Parameters
    ----------
    df : pd.DataFrame
        Input dataframe with Java testgen data

    Returns
    -------
    List[Dict[str, Any]]
        List of prepared task records
    """
    tasks = []
    for _, row in tqdm(
        df.iterrows(), total=len(df), desc="Preparing Java testgen tasks"
    ):
        doc = row["doc"]
        meta = doc["meta"]

        # Extract generated code
        code = row["resps"][0][0] if row["resps"] and row["resps"][0] else ""
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
            "generated_code": code,
            # Store original metrics for comparison
            "original_pass@1": row.get("pass@1", 0),
            "original_compile@1": row.get("compilation_rate", 0),
        }
        tasks.append(task)

    return tasks


def run_java_testgen_evaluation(
    tasks: List[Dict[str, Any]], output_dir: str
) -> pd.DataFrame:
    """
    Run Java test generation evaluation and save results.

    Parameters
    ----------
    tasks : List[Dict[str, Any]]
        Tasks to evaluate
    output_dir : str
        Output directory for results

    Returns
    -------
    pd.DataFrame
        DataFrame with evaluation results
    """
    os.makedirs(output_dir, exist_ok=True)

    # ToDo: remove this
    enable_stdout_logs()

    results = []
    for task in tqdm(tasks, desc="Evaluating Java testgen tasks"):
        try:
            result = evaluate_java_test(
                repo=task["repo"],
                base_commit=task["base_commit"],
                image_name=task["image_name"],
                fn_test=task["fn_test"],
                test_command=task["test_command"],
                source_code=task["source_code"],
                code=task["generated_code"],
            )

            task_result = {
                "doc_id": task.get("doc_id"),
                "instance_id": task.get("instance_id"),
                "pass@1": float(result["parser"]["success"]),
                "compile@1": float(result["parser"]["compiled"]),
                "stdout": result.get("stdout", ""),
                "stderr": result.get("stderr", ""),
                "generated_code": task["generated_code"],
                "original_pass@1": task["original_pass@1"],
                "original_compile@1": task["original_compile@1"],
            }

        except Exception as e:
            print(f"Error evaluating task {task.get('doc_id')}: {e}")
            task_result = {
                "doc_id": task.get("doc_id"),
                "instance_id": task.get("instance_id"),
                "pass@1": 0.0,
                "compile@1": 0.0,
                "stdout": "",
                "stderr": f"Error: {str(e)}",
                "generated_code": task["generated_code"],
                "original_pass@1": task["original_pass@1"],
                "original_compile@1": task["original_compile@1"],
            }

        results.append(task_result)

    # Save detailed results
    results_path = os.path.join(output_dir, "java_testgen_results.json")
    with open(results_path, "w") as f:
        json.dump(results, f, indent=2)

    # Calculate and save metrics
    # metrics = process_java_testgen_results(results)
    _ = process_java_testgen_results(results)
    results_df = pd.DataFrame(results)

    metrics_csv = os.path.join(output_dir, "java_testgen_metrics.csv")
    results_df.to_csv(metrics_csv, index=False)

    return results_df


@pytest.mark.integration
def test_java_testgen_evaluation_light():
    """
    Light integration test for Java test generation with 10 samples.

    Tests the Java testgen evaluation pipeline with a small subset
    to ensure functionality without excessive runtime.
    """
    output_dir = "outputs/eval_java_testgen_light_test"

    # Use relative path to test data file
    script_dir = Path(__file__).parent
    input_jsonl = script_dir / "data" / "samples_java_testgen.jsonl"

    # Check if input file exists
    if not input_jsonl.exists():
        pytest.skip(f"Input file not found: {input_jsonl}")

    df = pd.read_json(input_jsonl, lines=True)

    # Take first 10 samples for light test
    df_subset = df.head(10)
    tasks = prepare_java_testgen_tasks(df_subset)

    results_df = run_java_testgen_evaluation(tasks=tasks, output_dir=output_dir)

    # Validate results
    assert not results_df.empty, "Results DataFrame should not be empty"
    assert len(results_df) == len(tasks), "Results count should match task count"

    # Check expected columns exist
    expected_columns = [
        "doc_id",
        "instance_id",
        "pass@1",
        "compile@1",
        "original_pass@1",
        "original_compile@1",
    ]
    for col in expected_columns:
        assert col in results_df.columns, f"Missing expected column: {col}"

    # Calculate metrics
    metrics = process_java_testgen_results(results_df.to_dict("records"))

    print("Light Java testgen test metrics:")
    print(f"pass@1: {metrics['pass@1']:.3f}")
    print(f"compile@1: {metrics['compile@1']:.3f}")
    print(f"num_samples: {metrics['num_samples']}")

    # Validate metrics consistency with original data
    original_pass_avg = results_df["original_pass@1"].mean()
    original_compile_avg = results_df["original_compile@1"].mean()

    print(f"Original pass@1: {original_pass_avg:.3f}")
    print(f"Original compile@1: {original_compile_avg:.3f}")

    # Allow some tolerance due to potential environment differences
    pass_diff = abs(metrics["pass@1"] - original_pass_avg)
    compile_diff = abs(metrics["compile@1"] - original_compile_avg)

    assert pass_diff <= 0.01, f"pass@1 difference too large: {pass_diff:.3f}"
    assert compile_diff <= 0.01, f"compile@1 difference too large: {compile_diff:.3f}"


@pytest.mark.integration
@pytest.mark.slow
def test_java_testgen_evaluation_full():
    """
    Full integration test for Java test generation with all available samples.

    Tests the complete Java testgen evaluation pipeline with the full dataset.
    This test may take considerable time to complete.
    """
    output_dir = "outputs/eval_java_testgen_full_test"

    # Use relative path to test data file
    script_dir = Path(__file__).parent
    input_jsonl = script_dir / "data" / "samples_java_testgen.jsonl"

    # Check if input file exists
    if not input_jsonl.exists():
        pytest.skip(f"Input file not found: {input_jsonl}")

    df = pd.read_json(input_jsonl, lines=True)
    tasks = prepare_java_testgen_tasks(df)

    results_df = run_java_testgen_evaluation(tasks=tasks, output_dir=output_dir)

    # Validate results
    assert not results_df.empty, "Results DataFrame should not be empty"
    assert len(results_df) == len(tasks), "Results count should match task count"

    # Check expected columns exist
    expected_columns = [
        "doc_id",
        "instance_id",
        "pass@1",
        "compile@1",
        "original_pass@1",
        "original_compile@1",
    ]
    for col in expected_columns:
        assert col in results_df.columns, f"Missing expected column: {col}"

    # Calculate metrics
    metrics = process_java_testgen_results(results_df.to_dict("records"))

    print("Full Java testgen test metrics:")
    print(f"pass@1: {metrics['pass@1']:.3f}")
    print(f"compile@1: {metrics['compile@1']:.3f}")
    print(f"num_samples: {metrics['num_samples']}")

    # Validate metrics consistency with original data
    original_pass_avg = results_df["original_pass@1"].mean()
    original_compile_avg = results_df["original_compile@1"].mean()

    print(f"Original pass@1: {original_pass_avg:.3f}")
    print(f"Original compile@1: {original_compile_avg:.3f}")

    # Allow some tolerance due to potential environment differences
    pass_diff = abs(metrics["pass@1"] - original_pass_avg)
    compile_diff = abs(metrics["compile@1"] - original_compile_avg)

    print(f"Pass@1 difference: {pass_diff:.3f}")
    print(f"Compile@1 difference: {compile_diff:.3f}")

    # More lenient tolerance for full test due to larger dataset
    assert (
        pass_diff < 0.1
    ), f"pass@1 difference too large: {pass_diff:.3f} metrics={metrics}"
    assert (
        compile_diff < 0.1
    ), f"compile@1 difference too large: {compile_diff:.3f} metrics={metrics}"

    # Additional validation for full test
    assert metrics["num_samples"] == len(
        df
    ), f"Sample count should match input data metrics={metrics}"

    # Check that we have reasonable success rates
    assert (
        metrics["compile@1"] > 0.5
    ), f"Compilation rate should be reasonable metrics={metrics}"


if __name__ == "__main__":
    # Allow running tests directly
    test_java_testgen_evaluation_light()
