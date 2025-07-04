import pytest
from repotest.core.docker.java import JavaDockerRepo
from ....fixtures.java_example  import repo_name, base_commit, image_name

@pytest.fixture(params=['download', 'shared', 'local', 'volume'])
def repo(request):
    repo_instance = JavaDockerRepo(
        repo=repo_name,
        base_commit=base_commit,
        image_name=image_name,
        cache_mode=request.param
    )
    repo_instance.clean()  # Очистить папку до состояния как на гите
    return repo_instance

def test_java_docker_repo(repo):
    # Проверяем, что репозиторий очищен
    assert repo.repo == repo_name
    assert repo.base_commit == base_commit
    assert repo.image_name == image_name
    
    # Запуск тестов с ограничением по времени
    result = repo.run_test("mvn test", timeout=60*5)
    
    # Проверяем, что тесты выполнены успешно (зависит от ожидаемого результата)
    assert result is not None
    assert result['parser']['success'] == True
    # assert result['parser']['compiled'] == True
    
    parsed_test_files = result['parser_xml']
    assert len(parsed_test_files) > 0
    
    for test_file in parsed_test_files:
        assert test_file.get('class_name') is not None
        assert any(key in test_file for key in ['passed', 'skipped', 'failure', 'error'])
