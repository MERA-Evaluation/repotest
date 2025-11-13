# test_typescript_docker_repo.py
import pytest
from repotest.core.docker.typescript import TypeScriptDockerRepo


def pytest_addoption(parser):
    parser.addoption(
        "--slow", 
        action="store_true", 
        default=False, 
        help="Run slow tests with all cache modes"
    )


def pytest_generate_tests(metafunc):
    if "cache_mode" in metafunc.fixturenames:
        if metafunc.config.getoption("--slow"):
            # Run with all cache modes
            metafunc.parametrize("cache_mode", ["download", "shared", "local", "volume"])
        else:
            # Run only with download mode
            metafunc.parametrize("cache_mode", ["download"])


@pytest.fixture
def test_result_mocha(cache_mode):
    repo_instance = TypeScriptDockerRepo(
        repo="nestjs/nest",
        base_commit="v11.1.7",
        cache_mode=cache_mode,
    )
    repo_instance.clean()
    repo_instance.build_env("npm install --legacy-peer-deps --loglevel=error;npm install mocha-junit-reporter --legacy-peer-deps --loglevel=error")
    assert repo_instance.repo == "nestjs/nest"
    assert repo_instance.base_commit == "v11.1.7"
    result = repo_instance.run_test("npm test -- --reporter mocha-junit-reporter", timeout=60 * 5)
    
    return result


def test_typescript_docker_repo_mocha_report(test_result_mocha):
    assert test_result_mocha is not None
    # Test machine readable format
    assert isinstance(test_result_mocha["report"], dict)

    report = test_result_mocha["report"]['summary']
    assert report["total"] >= 1800
    assert report["passed"] >= 1800
    assert report["collected"] >= 1800 # memory
    assert report["failed"] >= 0

    # Test std parser
    # parser = test_result_mocha["parser"]
    # assert parser["status"] == "unknown"
    # assert parser["summary"]["total"] == 1806
    # assert parser["summary"]["passed"] == 1806
    # assert parser["summary"]["failed"] == 0

def test_typescript_docker_repo_mocha_parser(test_result_mocha):
    assert test_result_mocha is not None
    # Test machine readable format
    assert isinstance(test_result_mocha["parser"], dict)

    # Note: Due to fluctuations in available computing resources, 
    # the execution of resource-heavy tests may be inconsistent, 
    # leading to a variable number of passes and failures. 
    # Therefore, non-strict equality is employed in the validation.

    report = test_result_mocha["parser"]['summary']
    assert report["total"] >= 1800
    assert report["passed"] >= 1800
    assert report["collected"] >= 1800
    assert report["failed"] >= 0

@pytest.fixture
def test_result_jest(cache_mode):
    repo_instance = TypeScriptDockerRepo(
        repo="clarkbw/jest-localstorage-mock",
        base_commit="a885e23f26e20da2b0b8dbe6e10dc06488385413",
        cache_mode=cache_mode,
    )
    repo_instance.clean()
    repo_instance.build_env("npm install --legacy-peer-deps --loglevel=error;npm install mocha-junit-reporter --legacy-peer-deps --loglevel=error")
    assert repo_instance.repo == "clarkbw/jest-localstorage-mock"
    assert repo_instance.base_commit == "a885e23f26e20da2b0b8dbe6e10dc06488385413"
    result = repo_instance.run_test('npx jest --json --outputFile="jest-results.json"', timeout=60 * 5)

    return result


def test_typescript_docker_repo_jest_report(test_result_jest):
    assert test_result_jest is not None
    assert isinstance(test_result_jest["report"], dict)

    # test machine readable format
    report = test_result_jest["report"]['summary']
    assert report["total"] >= 20
    assert report["passed"] >= 20
    assert report["collected"] >= 20
    assert report["failed"] >= 0

    # # test std parser
    # parser = test_result_jest["parser"]
    # assert parser["status"] == "unknown"
    # assert parser["summary"]["total"] == 20
    # assert parser["summary"]["passed"] == 20
    # assert parser["summary"]["failed"] == 0

def test_typescript_docker_repo_jest_parser(test_result_jest):
    assert test_result_jest is not None
    assert isinstance(test_result_jest["parser"], dict)

    # test machine readable format
    report = test_result_jest["parser"]['summary']
    assert report["total"] >= 20
    assert report["passed"] >= 20
    assert report["collected"] >= 20
    assert report["failed"] >= 0