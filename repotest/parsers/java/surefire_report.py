"""
Парсинг результатов тестов из xml отчетов плагина surefire. 
Не все тесты формируют отчеты на диске. Настройки плагина в pom.xml ?

https://maven.apache.org/surefire/maven-surefire-plugin/index.html
https://maven.apache.org/surefire/maven-surefire-plugin/examples/inclusion-exclusion.html
"""
# ToDo: Move this to base_java class

import os
import xml.etree.ElementTree as ET

from typing import List


"""
Находит список директорий `surefire-reports` по всему проекту,
в т.ч. пустые.
"""
def find_all_test_report_dirs(root_dir: str) -> List[str]:
    report_dirs = []
    walk_iter = os.walk(root_dir, topdown=True, onerror=None, followlinks=False)
    for dirpath, dirnames, filenames in walk_iter:
        if os.path.split(dirpath)[1] == 'surefire-reports':
            report_dirs.append(dirpath)
    return report_dirs


"""
Находит пути к отчетам c результатами тестов плагина `surefire`.
"""
def find_test_reports(root_dir: str) -> List[str]:
    report_paths = []
    dir_prefixes = set()
    walk_iter = os.walk(root_dir, topdown=True, onerror=None, followlinks=False)
    for dirpath, dirs, files in walk_iter:
        if os.path.split(dirpath)[1] == 'surefire-reports':
            dir_prefixes.add(dirpath)
        if any(dirpath.startswith(prefix) for prefix in dir_prefixes):
            for file in files:
                if file.startswith('TEST-') and file.endswith('.xml'):
                    full_path = os.path.join(dirpath, file)
                    report_paths.append(full_path)
    return report_paths


def parse_xml_test_report(path: str) -> dict:
    tree = ET.parse(path)
    root = tree.getroot()
    assert root.tag == 'testsuite'
    testsuite = {
        'name': root.attrib['name'],
        'tests': int(root.attrib.get('tests', 0)),
        # Пока только skipped отсутствовал в одном из отчетов
        'skipped': int(root.attrib.get('skipped', 0)),
        'failures': int(root.attrib.get('failures', 0)),
        'errors': int(root.attrib.get('errors', 0)),
    }
    parsed_tests = []
    for testcase in root.iter('testcase'):
        res = {
            'name': testcase.attrib['name'],
            'classname': testcase.attrib['classname'],
            'status': None,
        }
        for err in testcase.iter():
            if err.tag in ['failure', 'rerunFailure', 'flakyFailure']:
                res['message'] = err.attrib.get('message')
                res['error_type'] = err.attrib.get('type')
                res['full_error'] = err.text
                res['status'] = 'failure'
            if err.tag in ['error', 'rerunError', 'flakyError']:
                res['message'] = err.attrib.get('message')
                res['error_type'] = err.attrib.get('type')
                res['full_error'] = err.text
                res['status'] = 'error'
            if err.tag == 'skipped':
                res['message'] = err.attrib.get('message')
                res['status'] = 'skipped'
            if err.tag == 'system-err':
                # Похоже, эти тесты не учитываются как ошибочные в общей статистике
                # Но для бенча будет важно, что тест не запускался
                res['system_error'] = err.text
                res['status'] = 'system-error'
            # Не нужно это сохранять, только раздувает отчет
            # if err.tag == 'system-out':
            #     test_res['system_out'] = err.text
        if res['status'] is None:
            res['status'] = 'passed'
        parsed_tests.append(res)
    testsuite['testcases'] = parsed_tests
    return testsuite


def group_test_cases_by_status(testsuite: dict) -> dict:
    out = {'class_name': testsuite['name']}
    for testcase in testsuite['testcases']:
        # Вроде бы еще раз класс дублировать не нужно, 
        # один файл на один класс
        out.setdefault(testcase['status'], []).append(testcase['name'])
    return out