# test_python_docker_repo.py
import pytest
from repotest.core.docker.python import PythonDockerRepo
from repotest.core.types import OutputBuildEnv, OutputTests, OutputSummary

@pytest.fixture(params=["download", "shared", "local", "volume"])
def repo_and_build_env(request):
    repo_instance = PythonDockerRepo(
        repo="niklashenning/pytablericons",
        base_commit="29f2138c6399c04b4a0818503995b35627aaa754",
        cache_mode=request.param,
        working_mode='docker'
    )
    repo_instance.clean()
    build_env_result = repo_instance.build_env()

    return repo_instance, build_env_result

def test_python_docker_repo(repo_and_build_env):
    repo, build_env_result = repo_and_build_env

    assert repo.repo == "niklashenning/pytablericons"
    assert repo.base_commit == "29f2138c6399c04b4a0818503995b35627aaa754"
    
    # Test that build_env returns correct type
    assert isinstance(build_env_result, OutputBuildEnv)
    assert hasattr(build_env_result, 'stdout')
    assert hasattr(build_env_result, 'stderr')
    assert hasattr(build_env_result, 'returncode')
    
    # Test dictionary-style access for build_env
    assert build_env_result['stdout'] == build_env_result.stdout
    assert build_env_result['stderr'] == build_env_result.stderr
    assert build_env_result['returncode'] == build_env_result.returncode

    result = repo.run_test(timeout=60 * 5)

    assert result is not None

    # Test parser result
    # ToDO: latency, now we are using strict typing, change to .status, .summary etc
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
    assert report['tests'][-1]['call']['outcome'] == "failed"
    assert report['tests'][-1]['call']['crash']['message'] == "assert (255, 0, 0, 255) == (0, 0, 0, 0)\n  \n  At index 0 diff: 255 != 0\n  Use -v to get more diff"

    # Test that run_test returns correct type
    # ToDO: latency, now we are using strict typing
    assert isinstance(result, OutputTests)
    
    # Test dictionary-style access for run_test
    # ToDO: latency, now we are using strict typing
    assert result['stdout'] == result.stdout
    assert result['stderr'] == result.stderr
    assert result['returncode'] == result.returncode
    
    # Test nested dataclass access
    # ToDO: latency, now we are using strict typing
    assert isinstance(result.summary, OutputSummary)
    assert result['summary']['passed'] == result.summary.passed
    assert result['summary']['failed'] == result.summary.failed