"""
Configuration file for big_test pytest suite.

This module provides pytest configuration for integration tests that may
take significant time to run or require special resources.
"""

import os
import shutil
import tempfile

import pytest


def pytest_configure(config):
    """Configure pytest with custom markers."""
    config.addinivalue_line("markers", "integration: mark test as integration test")
    config.addinivalue_line("markers", "slow: mark test as slow running")


@pytest.fixture(scope="session")
def test_output_dir():
    """
    Create a temporary directory for test outputs.

    This fixture provides a clean directory for each test session
    and ensures cleanup after all tests complete.

    Yields
    ------
    str
        Path to temporary output directory
    """
    temp_dir = tempfile.mkdtemp(prefix="repotest_integration_")
    yield temp_dir
    # Cleanup after tests
    shutil.rmtree(temp_dir, ignore_errors=True)


@pytest.fixture
def sample_task_data():
    """
    Provide sample task data for testing.

    Returns
    -------
    dict
        Sample task dictionary with required fields
    """
    return {
        "id": "test_task_001",
        "repo": "test/repo",
        "base_commit": "abc123",
        "image_name": "test_image",
        "build_command": "pip install -e .",
        "test_command": "python -m pytest",
        "fn": "test_file.py",
        "PASS_TO_PASS": 1,
        "FAIL_TO_PASS": 0,
        "gt": "def test_function():\n    pass",
        "intent": "Test function implementation",
        "intent_type": "function",
        "left_context": "# Context before\n",
        "right_context": "\n# Context after",
        "gen": "def test_function():\n    assert True",
        "return_pass": "    pass",
        "return_empty_str": '    return ""',
    }


@pytest.fixture
def skip_if_no_input_file():
    """
    Skip test if the required input JSONL file is not available.

    This fixture can be used to conditionally skip tests that require
    specific input files that may not be available in all environments.
    """

    def _skip_if_missing(file_path):
        if not os.path.exists(file_path):
            pytest.skip(f"Input file not found: {file_path}")

    return _skip_if_missing


# Pytest collection configuration
def pytest_collection_modifyitems(config, items):
    """
    Modify test collection to add markers based on test names.

    This automatically adds markers to tests based on their names,
    allowing for easy filtering of test categories.
    """
    for item in items:
        # Add integration marker to all tests in integration directory
        if "integration" in str(item.fspath):
            item.add_marker(pytest.mark.integration)

        # Add slow marker to full evaluation tests
        if "full" in item.name:
            item.add_marker(pytest.mark.slow)
