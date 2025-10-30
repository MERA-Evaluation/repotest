# test_typescript_docker_repo.py
import pytest
from repotest.core.docker.typescript import TypeScriptDockerRepo

@pytest.fixture(params=["download", "shared", "local", "volume"])
def repo(request):
    repo_instance = TypeScriptDockerRepo(
        repo="nestjs/nest",
        base_commit="v11.1.7",
        cache_mode=request.param,
    )
    repo_instance.clean()
    return repo_instance

def test_typescript_docker_repo(repo):
    assert repo.repo == "nestjs/nest"
    assert repo.base_commit == "v11.1.7"
    
    result = repo.run_test(timeout=60 * 5)
    
    assert result is not None
    parser = result["parser"]
    assert parser["status"] == "passed"
    assert parser["summary"]["total"] > 0
    assert parser["summary"]["passed"] > 0
    assert parser["summary"]["failed"] >= 0
    assert parser["summary"]["skipped"] >= 0
    assert isinstance(result["report"], dict)