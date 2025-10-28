# test_scala_docker_repo.py
import pytest
from repotest.core.docker.scala import ScalaDockerRepo

@pytest.fixture(params=["download", "shared", "local", "volume"])
def repo(request):
    repo_instance = ScalaDockerRepo(
        repo="monix/monix",
        base_commit="v3.4.0",
        cache_mode=request.param,
    )
    repo_instance.clean()
    return repo_instance

def test_scala_docker_repo(repo):
    assert repo.repo == "monix/monix"
    
    result = repo.run_test(timeout=60 * 10)
    
    assert result is not None
    parser = result["parser"]
    assert parser["status"] in ["passed", "failed"]
    assert parser["summary"]["total"] >= 0
    assert parser["summary"]["passed"] >= 0
    assert parser["summary"]["failed"] >= 0
    assert parser["summary"]["skipped"] >= 0
    assert isinstance(result["report"], dict)