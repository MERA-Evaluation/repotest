# test_ruby_docker_repo.py
import pytest
from repotest.core.docker.ruby import RubyDockerRepo

@pytest.fixture(params=["download", "shared", "local", "volume"])
def repo(request):
    repo_instance = RubyDockerRepo(
        repo="lostisland/faraday",
        base_commit="v2.7.4",
        cache_mode=request.param,
    )
    repo_instance.clean()
    return repo_instance

def test_ruby_docker_repo(repo):
    assert repo.repo == "lostisland/faraday"
    
    result = repo.run_test(timeout=60 * 5)
    
    assert result is not None
    parser = result["parser"]
    assert parser["status"] in ["passed", "failed", "unknown"]
    assert parser["summary"]["total"] >= 0
    assert isinstance(result["report"], dict)