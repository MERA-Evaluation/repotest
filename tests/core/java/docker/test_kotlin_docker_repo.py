# test_kotlin_docker_repo.py
import pytest
from repotest.core.docker.kotlin import KotlinDockerRepo

@pytest.fixture(params=["download", "shared", "local", "volume"])
def repo(request):
    repo_instance = KotlinDockerRepo(
        repo="grpc/grpc-kotlin",
        base_commit="v1.3.0",
        cache_mode=request.param,
    )
    repo_instance.clean()
    return repo_instance

def test_kotlin_docker_repo(repo):
    assert repo.repo == "grpc/grpc-kotlin"

    result = repo.run_test(timeout=60 * 5)
    
    assert result is not None
    parser = result["parser"]
    assert parser["status"] in ["passed", "failed", "unknown"]
    assert parser["summary"]["total"] >= 0
    assert isinstance(result["report"], dict)