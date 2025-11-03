import pytest
from repotest.core.local.java import JavaLocalRepo

from ...fixtures.java_example import base_commit, repo_name


@pytest.fixture
def repo():
    repo_instance = JavaLocalRepo(repo=repo_name, base_commit=base_commit)
    repo_instance.clean()  # Очистить папку до состояния как на гите
    return repo_instance


def test_java_local_repo(repo):
    assert repo.repo == repo_name
    assert repo.base_commit == base_commit

    result = repo.run_test("mvn test", timeout=60 * 5)

    assert result is not None
    assert result["parser"]["success"] is True

    parsed_test_files = result["parser_xml"]
    assert len(parsed_test_files) > 0

    for test_file in parsed_test_files:
        assert test_file.get("class_name") is not None
        assert any(
            key in test_file for key in ["passed", "skipped", "failure", "error"]
        )
