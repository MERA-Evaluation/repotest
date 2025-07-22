import json
import os
from pathlib import Path
from typing import Any, Dict, List

import pandas as pd
import pytest
from repotest.constants import enable_stdout_logs
from repotest.manager.realcode_python_task_manager import TaskManagerRealcode
from tqdm import tqdm


def process_results(
    doc: Dict[str, Any], results: List[Dict[str, Any]]
) -> Dict[str, float]:
    """
    Process evaluation results and convert to standardized metrics format.

    Parameters
    ----------
    doc : Dict[str, Any]
        Document metadata (currently unused but kept for compatibility)
    results : List[Dict[str, Any]]
        List containing task results dictionary

    Returns
    -------
    Dict[str, float]
        Dictionary with standardized metric names and values
    """
    column_replace_dict = {
        "pass_gen": "pass@1",
        "pass_gt": "pass_oracle@1",
        "pass_return_pass": "pass_stub_pass@1",
        "pass_return_empty_str": "pass_stub_empty_str@1",
        "pass_dry_run": "pass_dry_run@1",
        "status": "execution_success",
    }
    metrics = results[0]
    res = {
        column_replace_dict[key]: metrics[key]
        for key in column_replace_dict
        if key in metrics
    }
    res["num_samples"] = 1
    return res


def generate_stub_codes(gt: str) -> Dict[str, str]:
    """
    Generate stub code implementations with proper indentation.

    Parameters
    ----------
    gt : str
        Ground truth code to match indentation from

    Returns
    -------
    Dict[str, str]
        Dictionary with stub implementations
    """

    def get_indent(code: str) -> int:
        """
        Determines indentation level of first non-empty line.

        Parameters
        ----------
        code : str
            Multiline code string.

        Returns
        -------
        int
            Number of leading spaces.
        """
        try:
            line = next(t for t in code.split("\n") if t.strip())
            return len(line) - len(line.lstrip())
        except StopIteration:
            return 0

    return {
        "return_pass": " " * get_indent(gt) + "pass",
        "return_empty_str": " " * get_indent(gt) + 'return ""',
    }


def prepare_task_records(df: pd.DataFrame) -> List[Dict[str, Any]]:
    """
    Prepare task records from dataframe for evaluation.

    Parameters
    ----------
    df : pd.DataFrame
        Input dataframe with evaluation data

    Returns
    -------
    List[Dict[str, Any]]
        List of prepared task records
    """
    task_records = []
    for _, row in tqdm(df.iterrows(), total=len(df), desc="Preparing tasks"):
        doc = row["doc"]["meta"]
        stubs = generate_stub_codes(doc["gt"])
        task = {
            "id": doc["id"],
            "repo": doc["repo"],
            "base_commit": doc["base_commit"],
            "image_name": doc["image_name"],
            "build_command": doc["build_command"],
            "test_command": doc["test_command"],
            "fn": doc["fn"],
            "PASS_TO_PASS": doc["PASS_TO_PASS"],
            "FAIL_TO_PASS": doc["FAIL_TO_PASS"],
            "gt": doc["gt"],
            "intent": doc["intent"],
            "intent_type": doc["intent_type"],
            "left_context": doc["left_context"],
            "right_context": doc["right_context"],
            "gen": row["fixed_code"],
            "return_pass": stubs["return_pass"],
            "return_empty_str": stubs["return_empty_str"],
        }
        task_records.append(task)
    return task_records


def run_evaluation(
    task_records: List[Dict[str, Any]],
    output_dir: str,
    mode: str = "docker",
    n_jobs: int = 1,
    n_jobs_build: int = 1,
) -> pd.DataFrame:
    """
    Run evaluation using TaskManagerRealcode and save results.

    Parameters
    ----------
    task_records : List[Dict[str, Any]]
        Task records to evaluate
    output_dir : str
        Output directory for results
    mode : str, optional
        Execution mode ('docker' or 'local'), by default 'docker'
    n_jobs : int, optional
        Number of parallel jobs for evaluation, by default 1
    n_jobs_build : int, optional
        Number of parallel jobs for building, by default 1

    Returns
    -------
    pd.DataFrame
        DataFrame with evaluation metrics
    """
    os.makedirs(output_dir, exist_ok=True)

    manager = TaskManagerRealcode(
        mode=mode,
        n_jobs=n_jobs,
        n_jobs_build=n_jobs_build,
        gen_columns=["gt", "return_pass", "return_empty_str", "gen"],
        raise_exception=True,
    )

    # ToDo: remove this
    enable_stdout_logs()
    manager.inplace_build_and_eval(task_records)

    # Save task results
    results_path = os.path.join(output_dir, "task_list.jsonl")
    with open(results_path, "w") as f:
        for t in task_records:
            f.write(json.dumps(t) + "\n")

    # Calculate and save metrics
    metrics = [process_results(None, [t]) for t in task_records]
    metrics_df = pd.DataFrame(metrics)
    metrics_csv = os.path.join(output_dir, "metrics_summary.csv")
    metrics_df.to_csv(metrics_csv, index=False)

    return metrics_df


@pytest.mark.integration
@pytest.mark.slow
def test_realcode_evaluation_light():
    """
    Light integration test for TaskManagerRealcode with 100 tasks.

    Tests the full evaluation pipeline with a subset of data to ensure
    functionality without excessive runtime.
    """
    output_dir = "outputs/eval_qwen2.5_coder_light_test"

    # Use relative path to test data file
    script_dir = Path(__file__).parent
    input_jsonl = script_dir / "data" / "samples_qwen2.5_coder_fixed_code.jsonl"

    # Check if input file exists
    if not input_jsonl.exists():
        pytest.skip(f"Input file not found: {input_jsonl}")

    df = pd.read_json(input_jsonl, lines=True)

    # Take first 100 samples for light test
    df_subset = df.head(100)
    task_records = prepare_task_records(df_subset)

    metrics_df = run_evaluation(
        task_records=task_records,
        output_dir=output_dir,
        mode="docker",
        n_jobs=15,
        n_jobs_build=15,
    )

    # Validate results
    assert not metrics_df.empty, "Metrics DataFrame should not be empty"
    assert len(metrics_df) == len(task_records), "Metrics count should match task count"

    # Check expected columns exist
    expected_columns = [
        "pass@1",
        "pass_oracle@1",
        "pass_stub_pass@1",
        "pass_stub_empty_str@1",
        "pass_dry_run@1",
        "execution_success",
        "num_samples",
    ]
    for col in expected_columns:
        assert col in metrics_df.columns, f"Missing expected column: {col}"

    # Print summary metrics
    print("Light test metrics summary:")
    print(metrics_df.sum(numeric_only=True))

    # Basic sanity checks
    assert metrics_df["num_samples"].sum() == len(task_records), "Sample count mismatch"
    assert all(metrics_df["num_samples"] == 1), "Each task should count as 1 sample"


@pytest.mark.integration
@pytest.mark.slow
def test_realcode_evaluation_full():
    """
    Full integration test for TaskManagerRealcode with all available tasks.

    Tests the complete evaluation pipeline with the full dataset.
    This test may take considerable time to complete.
    """
    output_dir = "outputs/eval_qwen2.5_coder_full_test"

    # Use relative path to test data file
    script_dir = Path(__file__).parent
    input_jsonl = script_dir / "data" / "samples_qwen2.5_coder_fixed_code.jsonl"

    # Check if input file exists
    if not input_jsonl.exists():
        pytest.skip(f"Input file not found: {input_jsonl}")

    df = pd.read_json(input_jsonl, lines=True)
    task_records = prepare_task_records(df)

    metrics_df = run_evaluation(
        task_records=task_records,
        output_dir=output_dir,
        mode="docker",
        n_jobs=15,  # Use more parallel jobs for full test
        n_jobs_build=15,
    )

    # Validate results
    assert not metrics_df.empty, "Metrics DataFrame should not be empty"
    assert len(metrics_df) == len(task_records), "Metrics count should match task count"

    # Check expected columns exist
    expected_columns = [
        "pass@1",
        "pass_oracle@1",
        "pass_stub_pass@1",
        "pass_stub_empty_str@1",
        "pass_dry_run@1",
        "execution_success",
        "num_samples",
    ]
    for col in expected_columns:
        assert col in metrics_df.columns, f"Missing expected column: {col}"

    # Print summary metrics
    print("Full test metrics summary:")
    print(metrics_df.sum(numeric_only=True))

    # Basic sanity checks
    assert metrics_df["num_samples"].sum() == len(task_records), "Sample count mismatch"
    assert all(metrics_df["num_samples"] == 1), "Each task should count as 1 sample"

    # Additional validation for full test
    success_rate = metrics_df["execution_success"].mean()
    print(f"Overall execution success rate: {success_rate:.2%}")
    assert success_rate > 0, "Should have some successful executions"


@pytest.mark.integration
def test_realcode_evaluation_local_mode():
    """
    Test TaskManagerRealcode in local mode with a small subset.

    Tests local execution mode which doesn't require Docker.
    """
    output_dir = "outputs/eval_qwen2.5_coder_local_test"

    # Use relative path to test data file
    script_dir = Path(__file__).parent
    input_jsonl = script_dir / "data" / "samples_qwen2.5_coder_fixed_code.jsonl"

    # Check if input file exists
    if not input_jsonl.exists():
        pytest.skip(f"Input file not found: {input_jsonl}")

    df = pd.read_json(input_jsonl, lines=True)

    # Use only 5 samples for local mode test
    df_subset = df.head(5)
    task_records = prepare_task_records(df_subset)

    metrics_df = run_evaluation(
        task_records=task_records,
        output_dir=output_dir,
        mode="local",  # Use local mode
        n_jobs=1,
        n_jobs_build=1,
    )

    # Validate results
    assert not metrics_df.empty, "Metrics DataFrame should not be empty"
    assert len(metrics_df) == len(task_records), "Metrics count should match task count"

    print("Local mode test metrics summary:")
    print(metrics_df.sum(numeric_only=True))


if __name__ == "__main__":
    # Allow running tests directly
    test_realcode_evaluation_light()
