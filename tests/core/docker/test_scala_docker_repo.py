# test_scala_docker_repo.py
import pytest
from repotest.core.docker.scala import ScalaDockerRepo

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
def test_result_json4s(cache_mode):
    repo_instance = ScalaDockerRepo(
        repo="json4s/json4s",
        base_commit="7cee8785cb3c701192820de4a66c86c87c380523",
        cache_mode=cache_mode,
    )
    repo_instance.clean()

    assert repo_instance.repo == "json4s/json4s"
    assert repo_instance.base_commit == "7cee8785cb3c701192820de4a66c86c87c380523"

    result = repo_instance.run_test(timeout=60 * 10)
    
    return result


def test_scala_docker_repo_report(test_result_json4s):
    assert test_result_json4s is not None
    assert isinstance(test_result_json4s["report"], dict)

    report = test_result_json4s["report"]['summary']
    assert report["total"] == 1771
    assert report["passed"] == 1767
    assert report["collected"] == 1771
    assert report["failed"] == 0
    assert test_result_json4s["report"]["status"] == "passed"

def test_scala_docker_repo_parser(test_result_json4s):
    assert test_result_json4s is not None
    assert isinstance(test_result_json4s["parser"], dict)

    report = test_result_json4s["parser"]['summary']
    assert report["total"] == 1771
    assert report["passed"] == 1767
    assert report["collected"] == 1771
    assert report["failed"] == 0
    assert test_result_json4s["parser"]["status"] == "passed"