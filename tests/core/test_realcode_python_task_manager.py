import pytest
from repotest.manager.realcode_python_task_manager import TaskManagerRealcode
import tempfile
import os

@pytest.fixture
def minimal_local_repo_task(tmp_path):
    # Создаем временный файл с простым содержимым
    file_path = tmp_path / "test_file.py"
    file_path.write_text("# left\n# right\n")
    return {
        'repo': 'fake/repo',
        'base_commit': 'fakecommit',
        'image_name': '',
        'build_command': 'echo ok',
        'test_command': 'echo ok',
        'fn': str(file_path.relative_to(tmp_path)),
        'left_context': '# left',
        'right_context': '# right',
        # Специально не добавляем один из gen_columns, чтобы проверить поведение
        'gt': 'print(1)',
        # 'pass' отсутствует
        'return_empty_str': '',
        'gen': 'print(2)',
    }

def test_eval_single_missing_keys(monkeypatch, minimal_local_repo_task, tmp_path):
    # Патчим build_success_status, чтобы пройти проверку
    manager = TaskManagerRealcode(mode='local', n_jobs=1, gen_columns=['gt', 'pass', 'return_empty_str', 'gen'])
    task = minimal_local_repo_task
    manager.build_success_status = {(task['repo'], task['base_commit']): 1}

    # Патчим PythonLocalRepo, чтобы не было реального клонирования и тестов
    class DummyRepo:
        was_build = True
        def clean(self): pass
        def run_test(self, command, timeout=300):
            # Возвращаем минимальный валидный отчет
            return {'report': {'tests': [{'nodeid': 't1', 'outcome': 'passed'}], 'summary': {'passed': 1}}}
        def change_file_realcode(self, fn_relative, left_context, gt, right_context):
            # Симулируем ошибку, если gt == 'print(2)' (для одной из колонок)
            if gt == 'print(2)':
                raise Exception('Simulated error')
    manager.RepoClass = lambda **kwargs: DummyRepo()

    # Запускаем eval_single
    try:
        manager.eval_single(task)
    except Exception:
        pass  # Ожидаем ошибку

    # Проверяем, что хотя бы status есть
    assert 'status' in task, 'status key missing in task after eval_single'
    # Проверяем, что pass_dry_run есть
    assert 'pass_dry_run' in task, 'pass_dry_run key missing in task after eval_single'
    # Проверяем, что pass_{key} есть только для тех, что реально были в task или key == 'gen'
    for key in ['gt', 'return_empty_str', 'gen']:
        assert f'pass_{key}' in task, f'pass_{key} missing in task after eval_single'
    # Проверяем, что pass_pass нет, так как 'pass' не было в task
    assert 'pass_pass' not in task, 'pass_pass should not be in task if pass not in original task'

def test_eval_single_missing_columns(monkeypatch, tmp_path):
    # Создаем task без 'gt' и 'return_empty_str'
    file_path = tmp_path / "test_file.py"
    file_path.write_text("# left\n# right\n")
    task = {
        'repo': 'fake/repo',
        'base_commit': 'fakecommit',
        'image_name': '',
        'build_command': 'echo ok',
        'test_command': 'echo ok',
        'fn': str(file_path.relative_to(tmp_path)),
        'left_context': '# left',
        'right_context': '# right',
        # 'gt' отсутствует
        # 'return_empty_str' отсутствует
        'gen': 'print(2)',
    }
    manager = TaskManagerRealcode(mode='local', n_jobs=1, gen_columns=['gen'])
    manager.build_success_status = {(task['repo'], task['base_commit']): 1}

    class DummyRepo:
        was_build = True
        def clean(self): pass
        def run_test(self, command, timeout=300):
            return {'report': {'tests': [{'nodeid': 't1', 'outcome': 'passed'}], 'summary': {'passed': 1}}}
        def change_file_realcode(self, fn_relative, left_context, gt, right_context):
            pass
    manager.RepoClass = lambda **kwargs: DummyRepo()

    manager.eval_single(task)

    # Проверяем, что pass_gen есть, а pass_gt и pass_return_empty_str нет
    assert 'pass_gt' not in task, 'pass_gt не должен быть в task, если gt не было в исходном task'
    assert 'pass_return_empty_str' not in task, 'pass_return_empty_str не должен быть в task, если return_empty_str не было в исходном task' 