# test_cpp_docker_repo.py
import pytest
from repotest.core.docker.cpp import CppDockerRepo

@pytest.fixture(params=["download", "shared", "local", "volume"])
def repo(request):
    repo_instance = CppDockerRepo(
        repo="google/googletest",
        base_commit="release-1.12.1",
        cache_mode=request.param,
    )
    repo_instance.clean()
    return repo_instance

def test_cpp_docker_repo(repo):
    assert repo.repo == "google/googletest"
    
    result = repo(
        command_build="mkdir build && cd build && cmake .. && make",
        command_test="cd build && ctest -V",
        timeout_build=60 * 5,
        timeout_test=60 * 5
    )
    
    assert result is not None
    parser = result["parser"]
    assert parser["status"] in ["passed", "failed", "unknown"]
    assert parser["summary"]["total"] >= 0
    assert isinstance(result["report"], dict)