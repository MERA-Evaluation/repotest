import pytest
from repotest.core.docker.python import PythonDockerRepo
from repotest.core.exceptions import TimeOutException
from repotest.core.local.python import PythonLocalRepo

# Random task configuration
TASK_CONFIG = {
    "repo": "niklashenning/pytablericons",
    "base_commit": "29f2138c6399c04b4a0818503995b35627aaa754",
    "image_name": "python:3.11.11-slim-bookworm",
    "build_command": "sleep 3",
    "build_timeout": 1,
    "test_timeout": 1,
    "test_command": "sleep 3",
}


@pytest.fixture
def local_repo():
    repo = PythonLocalRepo(
        repo=TASK_CONFIG["repo"], base_commit=TASK_CONFIG["base_commit"]
    )
    yield repo
    repo.clean()  # Cleanup after test


# Fixture for PythonDockerRepo
@pytest.fixture
def docker_repo():
    repo = PythonDockerRepo(
        repo=TASK_CONFIG["repo"],
        base_commit=TASK_CONFIG["base_commit"],
        image_name=TASK_CONFIG["image_name"],
    )
    yield repo
    repo.clean()  # Cleanup after test


def test_python_docker_build_timeout(docker_repo):
    """Test building and running tests separately."""
    try:
        _ = docker_repo.build_env(TASK_CONFIG["build_command"], timeout=1)
    except TimeOutException:
        return

    raise ValueError("Expected a TimeOutException but none was raised")


def test_python_docker_test_timeout(docker_repo):
    """Test building and running tests separately."""
    dct_test = docker_repo.run_test(TASK_CONFIG["test_command"], timeout=2)
    assert dct_test["returncode"] == 2
    print(dct_test)
    assert dct_test["stderr"] == "Timeout exception"


def test_python_local_build_timeout(local_repo):
    """Test building and running tests separately."""
    try:
        dct = local_repo.build_env(TASK_CONFIG["build_command"], timeout=1)
    except TimeOutException:
        return
    print(dct)
    raise ValueError("Expected a TimeOutException but none was raised")


def test_python_local_test_timeout(local_repo):
    """Test building and running tests separately."""
    dct_test = local_repo.run_test(TASK_CONFIG["test_command"], timeout=2)
    print(dct_test)
    assert dct_test["returncode"] == 2
    assert dct_test["stderr"] == "Timeout exception"
