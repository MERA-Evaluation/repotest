# test_rust_docker_repo.py
import pytest
from repotest.core.docker.rust import RustDockerRepo

@pytest.fixture(params=["download", "shared", "local", "volume"])
def repo(request):
    repo_instance = RustDockerRepo(
        repo="tokio-rs/mio",
        base_commit="v1.1.0",
        cache_mode=request.param,
    )
    repo_instance.clean()
    return repo_instance

def test_rust_docker_repo(repo):
    assert repo.repo == "tokio-rs/mio"
    assert repo.base_commit == "v1.1.0"
    
    result = repo.run_test(timeout=60 * 5)
    
    assert result is not None
    parser = result["parser"]
    assert parser["status"] == "passed"
    assert parser["summary"]["total"] > 0
    assert parser["summary"]["passed"] > 0
    assert parser["summary"]["failed"] >= 0
    assert parser["summary"]["skipped"] >= 0
    assert isinstance(result["report"], dict)