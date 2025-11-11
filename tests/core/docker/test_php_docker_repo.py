# test_php_docker_repo.py
import pytest
from repotest.core.docker.php import PhpDockerRepo

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
def test_result_guzzle_services(cache_mode):
    repo_instance = PhpDockerRepo(
        repo="guzzle/guzzle-services",
        base_commit="45bfeb80d5ed072bb39e9f6ed1ec5d650edae961",
        cache_mode=cache_mode,
    )
    repo_instance.build_env()

    assert repo_instance.repo == "guzzle/guzzle-services"
    assert repo_instance.base_commit == "45bfeb80d5ed072bb39e9f6ed1ec5d650edae961"

    result = repo_instance.run_test(timeout=60 * 5)
    
    return result


def test_php_docker_repo_guzzle_services(test_result_guzzle_services):
    assert test_result_guzzle_services is not None
    assert isinstance(test_result_guzzle_services["report"], dict)

    report = test_result_guzzle_services["report"]['summary']
    assert report["total"] == 621
    assert report["passed"] == 621
    assert report["collected"] == 621
    assert report["failed"] == 0
    assert test_result_guzzle_services["report"]["status"] == "passed"