"""
Unit tests for Java test generation processing and validation functions.

This module tests the correctness of metric calculation and processing
functions used in the Java testgen evaluation pipeline.
"""

import pandas as pd
import pytest
from test_java_testgen_evaluation import (ExtractFromTagJava,
                                          prepare_java_testgen_tasks,
                                          process_java_testgen_results)


class TestExtractFromTagJava:
    """Test cases for the ExtractFromTagJava class."""

    def test_extract_java_with_java_block(self):
        """Test extraction from text with ```java markdown block."""
        text = "Here is some Java code:\n```java\npublic class Test {\n    // code\n}\n```\nEnd of code."
        result = ExtractFromTagJava._extract_java(text)
        expected = "public class Test {\n    // code\n}"
        assert result == expected

    def test_extract_java_with_generic_block(self):
        """Test extraction from text with generic ``` block."""
        text = "Some text\n```\npublic class Test {\n    // code\n}\n```\nMore text"
        result = ExtractFromTagJava._extract_java(text)
        expected = "public class Test {\n    // code\n}"
        assert result == expected

    def test_extract_java_no_blocks(self):
        """Test extraction from plain text without blocks."""
        text = "public class Test {\n    // code\n}"
        result = ExtractFromTagJava._extract_java(text)
        assert result == text.strip()

    def test_extract_java_java_block_priority(self):
        """Test that ```java blocks take priority over generic blocks."""
        text = "Some text\n```java\npublic class JavaTest {}\n```\nMore text\n```\npublic class GenericTest {}\n```"
        result = ExtractFromTagJava._extract_java(text)
        expected = "public class JavaTest {}"
        assert result == expected

    def test_extract_java_empty_input(self):
        """Test extraction from empty or whitespace input."""
        assert ExtractFromTagJava._extract_java("") == ""
        assert ExtractFromTagJava._extract_java("   \n  \t  ") == ""

    def test_extract_java_complex_code(self):
        """Test extraction of complex Java code."""
        text = """Here's a test class:
```java
import org.junit.jupiter.api.Test;
import static org.junit.jupiter.api.Assertions.*;

public class CalculatorTest {
    @Test
    void testAdd() {
        Calculator calc = new Calculator();
        assertEquals(5, calc.add(2, 3));
    }
}
```
This is the end."""

        result = ExtractFromTagJava._extract_java(text)
        expected = """import org.junit.jupiter.api.Test;
import static org.junit.jupiter.api.Assertions.*;

public class CalculatorTest {
    @Test
    void testAdd() {
        Calculator calc = new Calculator();
        assertEquals(5, calc.add(2, 3));
    }
}"""
        assert result == expected


class TestProcessJavaTestgenResults:
    """Test cases for the process_java_testgen_results function."""

    def test_process_results_all_passing(self):
        """Test processing with all tasks passing."""
        tasks = [
            {"pass@1": 1.0, "compile@1": 1.0},
            {"pass@1": 1.0, "compile@1": 1.0},
            {"pass@1": 1.0, "compile@1": 1.0},
        ]

        result = process_java_testgen_results(tasks)

        expected = {"pass@1": 1.0, "compile@1": 1.0, "num_samples": 3}

        assert result == expected

    def test_process_results_mixed_results(self):
        """Test processing with mixed pass/fail results."""
        tasks = [
            {"pass@1": 1.0, "compile@1": 1.0},
            {"pass@1": 0.0, "compile@1": 1.0},
            {"pass@1": 0.0, "compile@1": 0.0},
        ]

        result = process_java_testgen_results(tasks)

        expected = {
            "pass@1": 1 / 3,  # 1 out of 3 passed
            "compile@1": 2 / 3,  # 2 out of 3 compiled
            "num_samples": 3,
        }

        assert abs(result["pass@1"] - expected["pass@1"]) < 1e-10
        assert abs(result["compile@1"] - expected["compile@1"]) < 1e-10
        assert result["num_samples"] == expected["num_samples"]

    def test_process_results_empty_tasks(self):
        """Test processing with empty task list."""
        result = process_java_testgen_results([])

        expected = {"pass@1": 0.0, "compile@1": 0.0, "num_samples": 0}

        assert result == expected

    def test_process_results_missing_metrics(self):
        """Test processing with tasks missing some metrics."""
        tasks = [
            {"pass@1": 1.0, "compile@1": 1.0},
            {"compile@1": 1.0},  # Missing pass@1
            {"pass@1": 0.0},  # Missing compile@1
        ]

        result = process_java_testgen_results(tasks)

        # Should treat missing metrics as 0
        expected = {
            "pass@1": 1 / 3,  # (1.0 + 0 + 0.0) / 3
            "compile@1": 2 / 3,  # (1.0 + 1.0 + 0) / 3
            "num_samples": 3,
        }

        assert abs(result["pass@1"] - expected["pass@1"]) < 1e-10
        assert abs(result["compile@1"] - expected["compile@1"]) < 1e-10
        assert result["num_samples"] == expected["num_samples"]


class TestPrepareJavaTestgenTasks:
    """Test cases for the prepare_java_testgen_tasks function."""

    def test_prepare_tasks_single_row(self):
        """Test task preparation with a single row."""
        mock_data = {
            "doc_id": 0,
            "doc": {
                "meta": {
                    "instance_id": "test_001",
                    "repo": "test/java-repo",
                    "base_commit": "abc123",
                    "image_name": "java_test_image",
                    "test_command": "mvn test",
                    "fn_test": "src/test/java/TestClass.java",
                    "source_code": "public class Calculator { public int add(int a, int b) { return a + b; } }",
                }
            },
            "resps": [["```java\ntest code here\n```"]],
            "pass@1": 0.8,
            "compilation_rate": 0.9,
        }

        df = pd.DataFrame([mock_data])
        result = prepare_java_testgen_tasks(df)

        assert len(result) == 1
        task = result[0]

        # Verify all expected fields are present
        expected_fields = {
            "doc_id",
            "instance_id",
            "repo",
            "base_commit",
            "image_name",
            "test_command",
            "fn_test",
            "source_code",
            "generated_code",
            "original_pass@1",
            "original_compile@1",
        }

        assert set(task.keys()) == expected_fields

        # Verify field values
        assert task["doc_id"] == 0
        assert task["instance_id"] == "test_001"
        assert task["repo"] == "test/java-repo"
        assert task["generated_code"] == "test code here"  # Java code extracted
        assert task["original_pass@1"] == 0.8
        assert task["original_compile@1"] == 0.9

    def test_prepare_tasks_multiple_rows(self):
        """Test task preparation with multiple rows."""
        mock_data = [
            {
                "doc_id": i,
                "doc": {
                    "meta": {
                        "instance_id": f"test_{i:03d}",
                        "repo": f"test/repo{i}",
                        "base_commit": f"abc{i}",
                        "image_name": f"image{i}",
                        "test_command": "mvn test",
                        "fn_test": f"Test{i}.java",
                        "source_code": f"class Source{i} {{}}",
                    }
                },
                "resps": [[f"```java\ntest code {i}\n```"]],
                "pass@1": i * 0.1,
                "compilation_rate": (i + 5) * 0.1,
            }
            for i in range(3)
        ]

        df = pd.DataFrame(mock_data)
        result = prepare_java_testgen_tasks(df)

        assert len(result) == 3

        for i, task in enumerate(result):
            assert task["doc_id"] == i
            assert task["instance_id"] == f"test_{i:03d}"
            assert task["repo"] == f"test/repo{i}"
            assert task["generated_code"] == f"test code {i}"
            assert task["original_pass@1"] == i * 0.1
            assert task["original_compile@1"] == (i + 5) * 0.1

    def test_prepare_tasks_empty_responses(self):
        """Test task preparation with empty or missing responses."""
        mock_data = {
            "doc_id": 0,
            "doc": {
                "meta": {
                    "instance_id": "test_001",
                    "repo": "test/repo",
                    "base_commit": "abc123",
                    "image_name": "test_image",
                    "test_command": "mvn test",
                    "fn_test": "Test.java",
                    "source_code": "class Source {}",
                }
            },
            "resps": [],  # Empty responses
            "pass@1": 0.0,
            "compilation_rate": 0.0,
        }

        df = pd.DataFrame([mock_data])
        result = prepare_java_testgen_tasks(df)

        assert len(result) == 1
        task = result[0]
        assert task["generated_code"] == ""  # Should handle empty responses

    def test_prepare_tasks_missing_original_metrics(self):
        """Test task preparation with missing original metrics."""
        mock_data = {
            "doc_id": 0,
            "doc": {
                "meta": {
                    "instance_id": "test_001",
                    "repo": "test/repo",
                    "base_commit": "abc123",
                    "image_name": "test_image",
                    "test_command": "mvn test",
                    "fn_test": "Test.java",
                    "source_code": "class Source {}",
                }
            },
            "resps": [["test code"]],
            # Missing pass@1 and compilation_rate
        }

        df = pd.DataFrame([mock_data])
        result = prepare_java_testgen_tasks(df)

        assert len(result) == 1
        task = result[0]
        assert task["original_pass@1"] == 0  # Should default to 0
        assert task["original_compile@1"] == 0  # Should default to 0


class TestJavaTestgenMetricsConsistency:
    """Test cases for Java testgen metrics consistency and validation."""

    def test_metrics_aggregation_consistency(self):
        """Test that metrics can be properly aggregated."""
        # Simulate multiple task results
        task_results = [
            {"pass@1": 1.0, "compile@1": 1.0},
            {"pass@1": 0.0, "compile@1": 1.0},
            {"pass@1": 1.0, "compile@1": 0.0},
            {"pass@1": 0.0, "compile@1": 0.0},
        ]

        metrics = process_java_testgen_results(task_results)

        assert metrics["pass@1"] == 0.5  # 2 out of 4 passed
        assert metrics["compile@1"] == 0.5  # 2 out of 4 compiled
        assert metrics["num_samples"] == 4

    def test_edge_case_all_zeros(self):
        """Test behavior with all zero results."""
        task_results = [
            {"pass@1": 0.0, "compile@1": 0.0},
            {"pass@1": 0.0, "compile@1": 0.0},
            {"pass@1": 0.0, "compile@1": 0.0},
        ]

        metrics = process_java_testgen_results(task_results)

        assert metrics["pass@1"] == 0.0
        assert metrics["compile@1"] == 0.0
        assert metrics["num_samples"] == 3

    def test_edge_case_perfect_scores(self):
        """Test behavior with perfect results."""
        task_results = [
            {"pass@1": 1.0, "compile@1": 1.0},
            {"pass@1": 1.0, "compile@1": 1.0},
            {"pass@1": 1.0, "compile@1": 1.0},
        ]

        metrics = process_java_testgen_results(task_results)

        assert metrics["pass@1"] == 1.0
        assert metrics["compile@1"] == 1.0
        assert metrics["num_samples"] == 3


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
