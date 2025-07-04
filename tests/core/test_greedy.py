import pytest
from repotest.core.local.python import PythonLocalRepo
from repotest.core.docker.python import PythonDockerRepo

# Random task configuration
TASK_CONFIG = {
    'repo': 'niklashenning/pytablericons',
    'base_commit': '29f2138c6399c04b4a0818503995b35627aaa754',
    'image_name': 'python:3.11.11-slim-bookworm',
    'build_command': 'pip install .; pip install -r requirements.txt; pip install pytest; pip install pytest-json-report;',
    'test_command': 'pytest tests --json-report --json-report-file=report_pytest.json'
}

# Fixture for PythonLocalRepo
@pytest.fixture
def local_repo():
    repo = PythonLocalRepo(
        repo=TASK_CONFIG['repo'],
        base_commit=TASK_CONFIG['base_commit']
    )
    yield repo
    repo.clean()  # Cleanup after test

# Fixture for PythonDockerRepo
@pytest.fixture
def docker_repo():
    repo = PythonDockerRepo(
        repo=TASK_CONFIG['repo'],
        base_commit=TASK_CONFIG['base_commit'],
        image_name=TASK_CONFIG['image_name']
    )
    yield repo
    repo.clean()  # Cleanup after test

# --- Tests for PythonLocalRepo ---
def test_local_repo_build_and_test_separate(local_repo):
    """Test building and running tests separately."""
    dict_build = local_repo.build_env(TASK_CONFIG['build_command'])
    assert local_repo.was_build
    
    dict_test = local_repo.run_test(TASK_CONFIG['test_command'])
    print("report/summary", dict_test['report']['summary'])
    assert dict_test['report']['summary']['passed'] >= 2

def test_local_repo_build_and_test_combined(local_repo):
    """Test building and running tests in a single command."""
    dict_test = local_repo(
        command_build=TASK_CONFIG['build_command'],
        command_test=TASK_CONFIG['test_command']
    )
    print(dict_test)
    print("report/summary", dict_test['report']['summary'])
    assert local_repo.was_build
    assert dict_test['report']['summary']['passed'] >= 2

# --- Tests for PythonDockerRepo ---
def test_docker_repo_build_and_test_separate(docker_repo):
    """Test building and running tests separately in Docker."""
    dict_build = docker_repo.build_env(TASK_CONFIG['build_command'])
    assert docker_repo.was_build
    
    dict_test = docker_repo.run_test(TASK_CONFIG['test_command'])
    print("report/summary", dict_test['report']['summary'])
    assert dict_test['report']['summary']['passed'] >= 2

def test_docker_repo_build_and_test_combined(docker_repo):
    """Test building and running tests in a single command in Docker."""
    docker_repo.clean()
    dict_test = docker_repo(
        command_build=TASK_CONFIG['build_command'],
        command_test=TASK_CONFIG['test_command']
    )
    assert docker_repo.was_build
    print("dict_test", dict_test)
    print("report/summary", dict_test['report']['summary'])
    assert dict_test['report']['summary']['passed'] >= 2