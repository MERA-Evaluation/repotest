# test_cpp_docker_repo.py
import pytest
from repotest.core.docker.cpp import CppDockerRepo

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
def test_result_googletest(cache_mode):
    repo_instance = CppDockerRepo(
        repo="google/googletest",
        base_commit="release-1.12.1",
        cache_mode=cache_mode,
        image_name="gcc:latest"
    )
    repo_instance.clean()
    repo_instance.build_env()

    assert repo_instance.repo == "google/googletest"
    assert repo_instance.base_commit == "release-1.12.1"

    result = repo_instance.run_test(timeout=60 * 5)
    
    return result


def test_cpp_docker_repo_googletest_report(test_result_googletest):
    assert test_result_googletest is not None
    assert isinstance(test_result_googletest["report"], dict)

    report = test_result_googletest["report"]['summary']
    assert report["total"] == 63
    assert report["passed"] == 52
    assert report["collected"] == 63
    assert report["failed"] == 11
    assert test_result_googletest["report"]["status"] == "failed"

def test_cpp_docker_repo_googletest_parser(test_result_googletest):
    assert test_result_googletest is not None
    assert isinstance(test_result_googletest["parser"], dict)

    report = test_result_googletest["parser"]['summary']
    assert report["total"] == 63
    assert report["passed"] == 52
    assert report["collected"] == 63
    assert report["failed"] == 11
    assert test_result_googletest["parser"]["status"] == "failed"