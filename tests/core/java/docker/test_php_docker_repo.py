# test_php_docker_repo.py
import pytest
from repotest.core.docker.php import PhpDockerRepo

@pytest.fixture(params=["download", "shared", "local", "volume"])
def repo(request):
    repo_instance = PhpDockerRepo(
        repo="symfony/symfony",
        base_commit="v6.4.0",
        cache_mode=request.param,
    )
    repo_instance.clean()
    return repo_instance

def test_php_docker_repo(repo):
    assert repo.repo == "symfony/symfony"
    
    result = repo.run_test(timeout=60 * 5)
    
    assert result is not None
    parser = result["parser"]
    assert parser["status"] in ["passed", "failed", "unknown"]
    assert parser["summary"]["total"] >= 0
    assert isinstance(result["report"], dict)