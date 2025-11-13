# test_rust_docker_repo.py
import pytest
from repotest.core.docker.rust import RustDockerRepo

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
def test_result_mio(cache_mode):
    repo_instance = RustDockerRepo(
        repo="serde-rs/serde",
        base_commit="e42684f9a773f0bd0d85f293f0a9034c1ba6c984",
        cache_mode=cache_mode,
    )
    repo_instance.clean()

    assert repo_instance.repo == "serde-rs/serde"
    assert repo_instance.base_commit == "e42684f9a773f0bd0d85f293f0a9034c1ba6c984"

    result = repo_instance.run_test(timeout=60 * 5)
    
    return result


def test_rust_docker_repo_report(test_result_mio):
    assert test_result_mio is not None
    assert isinstance(test_result_mio["report"], dict)

    report = test_result_mio["report"]['summary']
    assert report["total"] == 483
    assert report["passed"] == 478
    assert report["collected"] == 483
    assert report["failed"] == 0
    assert test_result_mio["report"]["status"] == "passed"

def test_rust_docker_repo_parser(test_result_mio):
    assert test_result_mio is not None
    assert isinstance(test_result_mio["parser"], dict)

    report = test_result_mio["parser"]['summary']
    assert report["total"] == 483
    assert report["passed"] == 478
    assert report["collected"] == 483
    assert report["failed"] == 0
    assert test_result_mio["parser"]["status"] == "passed"