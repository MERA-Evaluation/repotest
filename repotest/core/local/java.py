import os
import subprocess
from repotest.core.base import AbstractRepo
from repotest.constants import DEFAULT_EVAL_TIMEOUT_INT
from repotest.parsers.java.maven_stdout import analyze_maven_stdout
from repotest.parsers.java.jacoco_report import parse_jacoco_report
from repotest.parsers.java.surefire_report import (
    find_test_reports,
    parse_xml_test_report,
    group_test_cases_by_status,
    )

class JavaLocalRepo(AbstractRepo):
    """
    A class for managing and testing local Java repositories.

    Attributes
    ----------
    test_timeout : int
        Maximum time (in seconds) to wait for test execution (default is 60 seconds).
    """
    def build_env(self, 
                  command: str,
                  timeout: int = DEFAULT_EVAL_TIMEOUT_INT
                 ) -> None:
        self.run_test(command=command,
                      timeout=timeout
                     )
        pass

    def run_test(self, command = 'mvn test', timeout = DEFAULT_EVAL_TIMEOUT_INT):
        """
        Run tests in the Java repository using Maven.

        Returns
        -------
        dict
            A dictionary containing the test results with the following keys:
            - 'stdout': str, standard output from the test execution.
            - 'stderr': str, standard error from the test execution.
            - 'returncode': int, the return code from the Maven process.
        
        Notes
        -----
        The method detects the location of the `pom.xml` file and runs the tests 
        from the appropriate directory. If the Maven command succeeds (return code 0),
        it prints a success message. Otherwise, it prints a failure message.
        """

        # To Do: delete this put this to the command; command is the input parametre
        # Determine the working directory for Maven

        # Run the Maven test command
        #ToDo: use base_class Popen
        process = subprocess.Popen(
            command,
            shell=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=self.cache_folder,
        )
        
        stdout, stderr = '', ''
        try:
            stdout, stderr = process.communicate(timeout=timeout)
            stdout = stdout.decode("utf-8", errors = "replace") if stdout else ""
            stderr = stderr.decode("utf-8", errors = "replace") if stderr else ""
        except subprocess.TimeoutExpired:
            process.kill()
            stderr += f"\nTest execution timed out after {timeout} seconds."
        
        returncode = process.returncode
        print(f"Process return code: {returncode}")


        report = []
        test_reports_paths = find_test_reports(self.cache_folder)
        for report_path in test_reports_paths:
            testsuite = parse_xml_test_report(report_path)
            entry = group_test_cases_by_status(testsuite)
            report.append(entry)
        
        # Prepare the result dictionary
        result = {
            'stdout': stdout,
            'stderr': stderr,
            'returncode': returncode,
            "parser": analyze_maven_stdout(stdout=stdout, 
                                           full_path=self.default_cache_folder
                                           ),
            # "time": self.evaluation_time,
            "parser_xml": report # ToDo: rename parser_xml -> report
            }

        # Log success or failure
        if returncode == 0:
            print(f"Success [{self.repo}]")
        else:
            print(f"Fail [{self.repo}]")
            print("stdout")
            print(stdout)

            print("stderr")
            print(stderr)

        return result

    def run_jacoco(self, maven_path: str = "mvn", timeout = DEFAULT_EVAL_TIMEOUT_INT) -> str:
        """
        Runs Jacoco to generate coverage report.
        """
        result = self.subprocess_popen(command = maven_path + " jacoco:prepare-agent test jacoco:report -Dmaven.test.failure.ignore=true",
                                       timeout = timeout
                                      )
        coverage_dir = os.path.join(self.cache_folder, "target/site/jacoco")
        return coverage_dir
        # try:
        #     cmd = maven_path + " jacoco:prepare-agent test jacoco:report -Dmaven.test.failure.ignore=true"

        #     p = subprocess.Popen(
        #         cmd,
        #         shell=True,
        #         cwd=self.cache_folder,
        #         stdout=subprocess.PIPE,
        #         stderr=subprocess.PIPE,
        #     )
        #     stdout, stderr = p.communicate(timeout=timeout)
        #     if p.returncode != 0:
        #         return None
        # except Exception as e:
        #     return None
        # coverage_dir = os.path.join(self.cache_folder, "target/site/jacoco")
        # return coverage_dir
