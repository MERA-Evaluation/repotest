# test_golang_docker_repo.py
import pytest
from repotest.core.docker.golang import GoLangDockerRepo

@pytest.fixture(params=["download", "shared", "local", "volume"])
def repo(request):
    repo_instance = GoLangDockerRepo(
        repo="golang/go",
        base_commit="go1.21.5",
        cache_mode=request.param,
    )
    repo_instance.clean()
    return repo_instance

def test_golang_docker_repo(repo):
    assert repo.repo == "golang/go"
    
    result = repo.run_test(timeout=60 * 5)
    
    assert result is not None
    parser = result["parser"]
    assert parser["status"] == "passed"
    assert parser["summary"]["total"] > 0
    assert parser["summary"]["passed"] > 0
    assert parser["summary"]["failed"] >= 0
    assert parser["summary"]["skipped"] >= 0
    assert len(parser["packages"]) >= 0
    assert len(parser["tests"]) >= 0
    assert isinstance(result["report"], dict)