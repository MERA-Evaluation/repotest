"""
Unit tests for metrics processing and validation functions.

This module tests the correctness of metric calculation and processing
functions used in the realcode evaluation pipeline.
"""

import pandas as pd
import pytest
from test_realcode_evaluation import (generate_stub_codes,
                                      prepare_task_records, process_results)


class TestProcessResults:
    """Test cases for the process_results function."""

    def test_process_results_all_metrics(self):
        """Test process_results with all available metrics."""
        mock_task = {
            "pass_gen": 1,
            "pass_gt": 1,
            "pass_return_pass": 0,
            "pass_return_empty_str": 1,
            "pass_dry_run": 1,
            "status": 1,
        }

        result = process_results(None, [mock_task])

        expected = {
            "pass@1": 1,
            "pass_oracle@1": 1,
            "pass_stub_pass@1": 0,
            "pass_stub_empty_str@1": 1,
            "pass_dry_run@1": 1,
            "execution_success": 1,
            "num_samples": 1,
        }

        assert result == expected

    def test_process_results_partial_metrics(self):
        """Test process_results with only some metrics available."""
        mock_task = {"pass_gen": 0, "pass_gt": 1, "status": 0}

        result = process_results(None, [mock_task])

        expected = {
            "pass@1": 0,
            "pass_oracle@1": 1,
            "execution_success": 0,
            "num_samples": 1,
        }

        assert result == expected

        # Check that missing metrics are not included
        assert "pass_stub_pass@1" not in result
        assert "pass_stub_empty_str@1" not in result
        assert "pass_dry_run@1" not in result

    def test_process_results_empty_metrics(self):
        """Test process_results with empty task metrics."""
        mock_task = {}

        result = process_results(None, [mock_task])

        expected = {"num_samples": 1}
        assert result == expected

    def test_process_results_metric_name_mapping(self):
        """Test that metric names are correctly mapped."""
        mock_task = {
            "pass_gen": 1,
            "pass_gt": 0,
            "pass_return_pass": 1,
            "pass_return_empty_str": 0,
            "pass_dry_run": 1,
            "status": 1,
        }

        result = process_results(None, [mock_task])

        # Verify all expected mapped names are present
        expected_keys = {
            "pass@1",
            "pass_oracle@1",
            "pass_stub_pass@1",
            "pass_stub_empty_str@1",
            "pass_dry_run@1",
            "execution_success",
            "num_samples",
        }

        assert set(result.keys()) == expected_keys

        # Verify values are correctly mapped
        assert result["pass@1"] == mock_task["pass_gen"]
        assert result["pass_oracle@1"] == mock_task["pass_gt"]
        assert result["pass_stub_pass@1"] == mock_task["pass_return_pass"]
        assert result["pass_stub_empty_str@1"] == mock_task["pass_return_empty_str"]
        assert result["pass_dry_run@1"] == mock_task["pass_dry_run"]
        assert result["execution_success"] == mock_task["status"]


class TestGenerateStubCodes:
    """Test cases for the generate_stub_codes function."""

    def test_generate_stub_codes_no_indent(self):
        """Test stub generation for code with no indentation."""
        gt_code = "def function():\npass"
        result = generate_stub_codes(gt_code)

        expected = {"return_pass": "pass", "return_empty_str": 'return ""'}

        assert result == expected

    def test_generate_stub_codes_with_indent(self):
        """Test stub generation for code with indentation."""
        gt_code = "    def function():\n        pass"
        result = generate_stub_codes(gt_code)

        expected = {"return_pass": "    pass", "return_empty_str": '    return ""'}

        assert result == expected

    def test_generate_stub_codes_deep_indent(self):
        """Test stub generation for deeply indented code."""
        gt_code = "        nested_function()\n        return value"
        result = generate_stub_codes(gt_code)

        expected = {
            "return_pass": "        pass",
            "return_empty_str": '        return ""',
        }

        assert result == expected

    def test_generate_stub_codes_empty_lines(self):
        """Test stub generation with empty lines at the beginning."""
        gt_code = "\n\n    def function():\n        pass"
        result = generate_stub_codes(gt_code)

        expected = {"return_pass": "    pass", "return_empty_str": '    return ""'}

        assert result == expected

    def test_generate_stub_codes_only_whitespace(self):
        """Test stub generation for code with only whitespace."""
        gt_code = "   \n  \n\t\n"
        result = generate_stub_codes(gt_code)

        expected = {"return_pass": "pass", "return_empty_str": 'return ""'}

        assert result == expected

    def test_generate_stub_codes_mixed_indentation(self):
        """Test stub generation with mixed indentation styles."""
        gt_code = "\t    if condition:\n\t        process()"
        result = generate_stub_codes(gt_code)

        # Function counts total character length, so \t (1 char) + 4 spaces = 5 spaces
        expected = {
            "return_pass": "     pass",  # 5 spaces
            "return_empty_str": '     return ""',  # 5 spaces
        }

        assert result == expected


class TestPrepareTaskRecords:
    """Test cases for the prepare_task_records function."""

    def test_prepare_task_records_single_row(self):
        """Test task record preparation with a single row."""
        # Create mock dataframe
        mock_data = {
            "doc": {
                "meta": {
                    "id": "test_001",
                    "repo": "test/repo",
                    "base_commit": "abc123",
                    "image_name": "test_image",
                    "build_command": "pip install -e .",
                    "test_command": "python -m pytest",
                    "fn": "test_file.py",
                    "PASS_TO_PASS": 1,
                    "FAIL_TO_PASS": 0,
                    "gt": "def test():\n    pass",
                    "intent": "Test function",
                    "intent_type": "function",
                    "left_context": "# Before\n",
                    "right_context": "\n# After",
                }
            },
            "fixed_code": "def test():\n    assert True",
        }

        df = pd.DataFrame([mock_data])
        result = prepare_task_records(df)

        assert len(result) == 1
        task = result[0]

        # Verify all expected fields are present
        expected_fields = {
            "id",
            "repo",
            "base_commit",
            "image_name",
            "build_command",
            "test_command",
            "fn",
            "PASS_TO_PASS",
            "FAIL_TO_PASS",
            "gt",
            "intent",
            "intent_type",
            "left_context",
            "right_context",
            "gen",
            "return_pass",
            "return_empty_str",
        }

        assert set(task.keys()) == expected_fields

        # Verify field values
        assert task["id"] == "test_001"
        assert task["repo"] == "test/repo"
        assert task["gen"] == "def test():\n    assert True"
        assert task["return_pass"] == "pass"  # No indentation in gt
        assert task["return_empty_str"] == 'return ""'

    def test_prepare_task_records_multiple_rows(self):
        """Test task record preparation with multiple rows."""
        mock_data = [
            {
                "doc": {
                    "meta": {
                        "id": f"test_{i:03d}",
                        "repo": f"test/repo{i}",
                        "base_commit": f"abc{i}",
                        "image_name": f"test_image{i}",
                        "build_command": "pip install -e .",
                        "test_command": "python -m pytest",
                        "fn": f"test_file{i}.py",
                        "PASS_TO_PASS": i % 2,
                        "FAIL_TO_PASS": (i + 1) % 2,
                        "gt": f"    def test{i}():\n        pass",
                        "intent": f"Test function {i}",
                        "intent_type": "function",
                        "left_context": f"# Before {i}\n",
                        "right_context": f"\n# After {i}",
                    }
                },
                "fixed_code": f"    def test{i}():\n        assert True",
            }
            for i in range(3)
        ]

        df = pd.DataFrame(mock_data)
        result = prepare_task_records(df)

        assert len(result) == 3

        for i, task in enumerate(result):
            assert task["id"] == f"test_{i:03d}"
            assert task["repo"] == f"test/repo{i}"
            assert task["gen"] == f"    def test{i}():\n        assert True"
            # Check indentation is preserved in stubs
            assert task["return_pass"] == "    pass"
            assert task["return_empty_str"] == '    return ""'


class TestMetricsConsistency:
    """Test cases for metrics consistency and validation."""

    def test_metrics_aggregation_consistency(self):
        """Test that metrics can be properly aggregated."""
        # Simulate multiple task results
        task_results = [
            {"pass_gen": 1, "pass_gt": 1, "status": 1},
            {"pass_gen": 0, "pass_gt": 1, "status": 1},
            {"pass_gen": 1, "pass_gt": 0, "status": 0},
        ]

        metrics_list = [process_results(None, [task]) for task in task_results]
        metrics_df = pd.DataFrame(metrics_list)

        # Test aggregation
        total_metrics = metrics_df.sum(numeric_only=True)

        assert total_metrics["pass@1"] == 2  # 2 out of 3 passed
        assert total_metrics["pass_oracle@1"] == 2  # 2 out of 3 passed
        assert total_metrics["execution_success"] == 2  # 2 out of 3 succeeded
        assert total_metrics["num_samples"] == 3  # 3 total samples

        # Test averages
        avg_metrics = metrics_df.mean(numeric_only=True)
        assert abs(avg_metrics["pass@1"] - 2 / 3) < 1e-10
        assert abs(avg_metrics["pass_oracle@1"] - 2 / 3) < 1e-10
        assert abs(avg_metrics["execution_success"] - 2 / 3) < 1e-10
        assert avg_metrics["num_samples"] == 1  # Each sample counts as 1

    def test_column_consistency(self):
        """Test that all processed results have consistent columns."""
        # Test with varying available metrics
        task_results = [
            {"pass_gen": 1, "pass_gt": 1, "pass_return_pass": 0, "status": 1},
            {"pass_gen": 0, "pass_gt": 1, "status": 1},  # Missing pass_return_pass
            {"pass_gen": 1, "status": 0},  # Missing pass_gt and pass_return_pass
        ]

        metrics_list = [process_results(None, [task]) for task in task_results]
        metrics_df = pd.DataFrame(metrics_list)

        # All rows should have num_samples
        assert (metrics_df["num_samples"] == 1).all()

        # Missing metrics should be NaN
        assert metrics_df["pass_stub_pass@1"].isna().sum() == 2  # Missing in 2 tasks
        assert metrics_df["pass_oracle@1"].isna().sum() == 1  # Missing in 1 task

        # Present metrics should have correct values
        assert metrics_df.loc[0, "pass@1"] == 1
        assert metrics_df.loc[1, "pass@1"] == 0
        assert metrics_df.loc[2, "pass@1"] == 1


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
