# test_typescript_docker_repo.py
import pytest
from repotest.core.docker.python import PythonDockerRepo

@pytest.fixture(params=["download", "shared", "local", "volume"])
def repo(request):
    repo_instance = PythonDockerRepo(
        repo="niklashenning/pytablericons",
        base_commit="29f2138c6399c04b4a0818503995b35627aaa754",
        cache_mode=request.param,
    )
    repo_instance.clean()
    repo_instance.build_env()

    return repo_instance

def test_typescript_docker_repo(repo):
    assert repo.repo == "niklashenning/pytablericons"
    assert repo.base_commit == "29f2138c6399c04b4a0818503995b35627aaa754"

    result = repo.run_test(timeout=60 * 5)

    assert result is not None

    # Test parser result
    parser = result["parser"]
    assert parser["status"] == "unknown"
    assert parser["summary"]["total"] == 4
    assert parser["summary"]["passed"] == 2
    assert parser["summary"]["failed"] == 2
    assert parser["summary"]["skipped"] == 0
    assert isinstance(result["report"], dict)

    # Test report result
    report = result["report"]
    assert report["summary"]["passed"] == 2
    assert report["summary"]["failed"] == 2
    assert report["summary"]["total"] == 4
    assert report["summary"]["collected"] == 4

    # test error at report format
    report['tests'][-1]['call']['outcome'] == "failed"
    report['tests'][-1]['call']['crash']['message'] == "'assert (255, 0, 0, 255) == (0, 0, 0, 0)\n  \n  At index 0 diff: 255 != 0\n  Use -v to get more diff'"
