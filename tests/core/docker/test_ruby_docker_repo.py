# test_ruby_docker_repo.py
import pytest
from repotest.core.docker.ruby import RubyDockerRepo

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
            metafunc.parametrize("cache_mode", ["download", "shared", "local", "volume"])
        else:
            metafunc.parametrize("cache_mode", ["download"])

@pytest.fixture
def test_result_faraday(cache_mode):
    repo_instance = RubyDockerRepo(
        repo="lostisland/faraday",
        base_commit="v2.7.4",
        cache_mode=cache_mode,
    )
    repo_instance.clean()
    repo_instance.build_env()

    assert repo_instance.repo == "lostisland/faraday"
    assert repo_instance.base_commit == "v2.7.4"

    result = repo_instance.run_test(timeout=60 * 5)
    
    return result


def test_ruby_docker_repo_faraday(test_result_faraday):
    assert test_result_faraday is not None
    assert isinstance(test_result_faraday["report"], dict)

    report = test_result_faraday["report"]['summary']
    assert report["total"] == 1064
    assert report["passed"] == 1064
    assert report["collected"] == 1064
    assert report["failed"] == 0
    assert test_result_faraday["report"]["status"] == "passed"