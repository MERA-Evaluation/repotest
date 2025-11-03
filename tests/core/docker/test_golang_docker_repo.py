# test_golang_docker_repo.py
import pytest
from repotest.core.docker.golang import GoLangDockerRepo

def pytest_addoption(parser):
    parser.addoption(
        "--slow", 
        action="store_true", 
        default=False, 
        help="Run slow tests with all cache modes"
    )


def pytest_generate_tests(metafunc):
    if "cache_mode" in metafunc.fixturenames:
        if metafunc.config.getoption("--slow"):
            # Run with all cache modes
            metafunc.parametrize("cache_mode", ["download", "shared", "local", "volume"])
        else:
            # Run only with download mode
            metafunc.parametrize("cache_mode", ["download"])


@pytest.fixture
def repo(cache_mode):
    repo_instance = GoLangDockerRepo(
        repo="TheAlgorithms/Go",
        base_commit="5ba447ec5ff3d1213de65b92e726ee74c5d5cc19",
        cache_mode=cache_mode,
        image_name="golang:latest"
    )
    repo_instance.clean()
    return repo_instance

def test_golang_docker_repo(repo):
    assert repo.repo == "TheAlgorithms/Go"
    assert repo.base_commit == "5ba447ec5ff3d1213de65b92e726ee74c5d5cc19"
    result = repo.run_test(timeout=60 * 5)
    
    assert result is not None
    parser = result["parser"]
    assert parser["status"] == "failed"
    assert parser["summary"]["total"] == 2636
    assert parser["summary"]["passed"] == 2633
    assert parser["summary"]["failed"] == 2
    assert parser["summary"]["skipped"] == 1
    assert isinstance(result["report"], dict)

    # Test report result
    report = result["report"]
    assert report["summary"]["passed"] == 2633
    assert report["summary"]["failed"] == 2
    assert report["summary"]["total"] == 2636
    assert report["summary"]["collected"] == 2636

    assert len(parser["packages"]) >= 10
    assert len(parser["tests"]) >= 10
    assert isinstance(result["report"], dict)