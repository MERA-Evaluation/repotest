# test_kotlin_docker_repo.py
import pytest
from repotest.core.docker.kotlin import KotlinDockerRepo

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
def test_result_grpc_kotlin(cache_mode):
    repo_instance = KotlinDockerRepo(
        repo="grpc/grpc-kotlin",
        base_commit="cdae63714d52739b80d69ce561ab08c295791e95",
        cache_mode=cache_mode,
    )
    repo_instance.clean()

    assert repo_instance.repo == "grpc/grpc-kotlin"
    assert repo_instance.base_commit == "cdae63714d52739b80d69ce561ab08c295791e95"

    result = repo_instance.run_test(timeout=60 * 5)
    
    return result


def test_kotlin_docker_repo_grpc_kotlin(test_result_grpc_kotlin):
    assert test_result_grpc_kotlin is not None
    assert isinstance(test_result_grpc_kotlin["report"], dict)

    report = test_result_grpc_kotlin["report"]['summary']
    assert report["total"] == 194
    assert report["passed"] == 193
    assert report["collected"] == 194
    assert report["failed"] == 1
    assert test_result_grpc_kotlin["report"]["status"] == "failed"