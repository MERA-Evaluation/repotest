import xmltodict
import os
from junitparser import JUnitXml
from repotest.logger import logger
import re

def get_failed_passed_tests(report, verbose=False):
    """
    Extract passed and failed tests from a test report.
    
    Args:
        report: Dictionary containing test results with 'testsuites' and 'summary'
        verbose: Whether to print detailed output
    
    Returns:
        tuple: (passed_test set, failed_test set, all_test list)
    """
    if verbose:
        print(report['summary'])
    
    failed_test = set()
    passed_test = set()
    all_test = []
    
    for ind0, test_suite in enumerate(report['testsuites']['testsuite']):
        suite_failures = int(test_suite.get('@failures', 0))
        suite_errors = int(test_suite.get('@errors', 0))
        suite_tests = int(test_suite.get('@tests', 0))
        
        # Check if suite has failures/errors but no testcases (build failure)
        if (suite_failures > 0 or suite_errors > 0) and 'testcase' not in test_suite:
            # This is a build failure - the entire suite failed
            suite_name = test_suite.get('@name', f'unknown_suite_{ind0}')
            test = f"{suite_name}::BUILD_FAILURE"
            if verbose:
                print(f"[{ind0}] Build failure in suite: {suite_name}")
            failed_test.add(test)
            all_test.append(test)
            continue
        
        # Process all testcases regardless of suite_tests count
        testcases = test_suite.get('testcase', [])
        if not isinstance(testcases, list):
            testcases = [testcases] if testcases else []
        
        for ind1, _test in enumerate(testcases):
            try:
                test = f"{_test['@classname']}::{_test['@name']}"
            except KeyError as e:
                if verbose:
                    print(f"[{ind0}][{ind1}] Missing key: {e}")
                raise
            
            if test in all_test:
                if verbose:
                    print(f"Warning: Duplicate test found: {test}")
                continue
            
            all_test.append(test)
            
            # Check for BOTH 'failure' and 'error' keys - both mean NOT passed
            if "failure" in _test or "error" in _test:
                failure_type = "failure" if "failure" in _test else "error"
                if verbose:
                    print(f"[{ind0}][{ind1}] Failed ({failure_type}): {test}")
                failed_test.add(test)
            else:
                passed_test.add(test)
    
    expected_failed = report['summary']['failed'] + report['summary']['error']
    
    if verbose:
        print(f"\nSummary: {len(passed_test)} passed, {len(failed_test)} failed, {len(all_test)} total")
        print(f"Expected: {report['summary']['passed']} passed, {expected_failed} failed")
        
        if len(failed_test) != expected_failed:
            print(f"⚠️  WARNING: Found {len(failed_test)} failed but expected {expected_failed}")

    passed_test = list(passed_test)
    failed_test = list(failed_test)
    
    return passed_test, failed_test, all_test

def parse_junit_report(fn_xml_result):
    report = {}
    if os.path.exists(fn_xml_result):
        try:
            xml = JUnitXml.fromfile(fn_xml_result)
            report = xmltodict.parse(xml.tostring())
        except Exception as e: # Debug this carefully
            logger.warning("Failed to parse JUnit XML report at %s: %s", fn_xml_result, e)
            # raise # after debug delete one of this lines
            
    else:
        logger.debug("File %s does not exist", fn_xml_result)
        return {}
     
    # Add summary field same as at pytest   
    n_total = int(report.get('testsuites', {}).get('@tests', 0))
    n_failures = int(report.get('testsuites', {}).get('@failures', 0))
    n_errors = int(report.get('testsuites', {}).get('@errors', 0))

    if report:
        try:
            passed_test, failed_test, all_test = get_failed_passed_tests(report)
        except:
            passed_test, failed_test, all_test = [], [], []
    else:
        passed_test, failed_test, all_test = [], [], []

    report['summary'] = {
                'total': n_total,
                'passed': n_total - n_failures - n_errors,
                'failed': n_failures,
                'error': n_errors,
                'xpassed': 0,
                'xfailed': 0,
                'list_all': all_test,  # Duplicates could be here by design (this field is never use and need only for debug purpose)
                'list_xfailed': failed_test,
                'list_xpassed': passed_test,

            }
    
    return report

def parse_junit_stdout(s):
    result = {'tests': [],
            'summary': {
                'total': 0,
                'passed': 0,
                'error': 0,
                'failed': 0,
                'warning': 0,
                'list_warning': [],
                'skipped': 0,
                'list_skipped': [],
                'xfailed': 0,
                'list_xfailed': [],
                'xpassed': 0,
                'list_xpassed': []
            },
            'failures': [],
            'out': '',
            'summary_raw': '',
            'status': 'failed'
        }

    # Parse summary line
    summary_pattern = r'DONE (\d+) tests, (\d+) failures, (\d+) errors'
    match = re.search(summary_pattern, s)

    # Parse failures
    failures = re.findall(r'=== FAIL: (\S+)', s)

    # Parse errors  
    errors = re.findall(r'=== Errors\n(.*?)(?=\n\nDONE|\Z)', s, re.DOTALL)
    error_list = []
    if errors:
        error_list = re.findall(r'^(\S+?):', errors[0], re.MULTILINE)

    if match:
        total = int(match.group(1))
        failed = int(match.group(2))
        error = int(match.group(3))
        passed = total - failed - error
        
        # Calculate status (same logic as old parse_pytest_stdout)
        n_passed = passed
        n_failed = failed + error
        
        if n_passed > 0 and n_failed == 0:
            status = "passed"
        elif n_passed == 0:
            status = "failed"
        else:
            status = "unknown"
        
        result['summary']['total'] = total
        result['summary']['passed'] = total
        result['summary']['error'] = total
        result['summary']['failed'] = total
        result['summary']['failures'] = failures + error_list,
        result['status'] = status
        
    return result

