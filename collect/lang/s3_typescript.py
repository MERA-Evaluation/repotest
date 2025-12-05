"""
TypeScript language filter for S3 repository collection.
Supports Jest and Mocha test frameworks.
"""
from typing import Dict, Any
from . import LanguageFilter


class TypeScriptFilter(LanguageFilter):
    """Filter for TypeScript repositories with Jest or Mocha tests."""
    
    TS_EXTENSIONS = {'.ts', '.tsx', '.mts', '.cts'}
    PACKAGE_JSON = 'package.json'
    TSCONFIG_JSON = 'tsconfig.json'
    
    TEST_PATTERNS = [
        '.test.ts', '.test.tsx', '.test.mts',
        '.spec.ts', '.spec.tsx', '.spec.mts',
        '__tests__'
    ]
    
    TEST_DIRS = {'test', 'tests', '__tests__', 'spec', 'specs'}
    
    def get_language_name(self) -> str:
        """Return language name."""
        return "TypeScript"
    
    def matches_language(self, repo: Dict[str, Any]) -> bool:
        """
        Check if repository is a TypeScript project.
        
        Criteria:
        1. Has .ts/.tsx/.mts/.cts files
        2. Has package.json and preferably tsconfig.json
        3. Language field indicates TypeScript
        
        Parameters
        ----------
        repo : dict
            Repository metadata
            
        Returns
        -------
        bool
            True if repository is a TypeScript project
        """
        language_field = repo.get('language')
        if language_field and isinstance(language_field, str):
            if language_field.lower() in ['typescript', 'ts']:
                return True
        
        file_paths = self.get_file_paths(repo)
        
        has_package_json = any(
            path == self.PACKAGE_JSON or path.endswith(f'/{self.PACKAGE_JSON}')
            for path in file_paths
        )
        
        if not has_package_json:
            return False
        
        has_ts_files = any(
            any(path.endswith(ext) for ext in self.TS_EXTENSIONS)
            for path in file_paths
        )
        
        if not has_ts_files:
            return False
        
        has_tsconfig = any(
            path == self.TSCONFIG_JSON or path.endswith(f'/{self.TSCONFIG_JSON}')
            for path in file_paths
        )
        
        return has_ts_files
    
    def has_runnable_tests(self, repo: Dict[str, Any]) -> bool:
        """
        Check if repository has runnable Jest or Mocha tests.
        
        Criteria for runnable tests:
        1. Has package.json with jest or mocha in dependencies/devDependencies
           OR has test files matching Jest/Mocha patterns
        2. Test files are not in node_modules/ or excluded directories
        3. Has at least one test file
        
        Parameters
        ----------
        repo : dict
            Repository metadata
            
        Returns
        -------
        bool
            True if repository has runnable tests
        """
        file_paths = self.get_file_paths(repo)
        
        test_files = []
        for path in file_paths:
            if self._is_excluded_path(path):
                continue
            
            is_test_file = False
            
            for pattern in self.TEST_PATTERNS:
                if pattern in path.lower():
                    is_test_file = True
                    break
            
            if not is_test_file:
                path_parts = path.lower().split('/')
                for test_dir in self.TEST_DIRS:
                    if test_dir in path_parts:
                        if any(path.endswith(ext) for ext in self.TS_EXTENSIONS):
                            is_test_file = True
                            break
            
            if is_test_file:
                test_files.append(path)
        
        if not test_files:
            return False
        
        has_package_json = any(
            path == self.PACKAGE_JSON for path in file_paths
        )
        
        return has_package_json and len(test_files) > 0
    
    def _is_excluded_path(self, path: str) -> bool:
        """
        Check if path should be excluded from test detection.
        
        Parameters
        ----------
        path : str
            File path
            
        Returns
        -------
        bool
            True if path should be excluded
        """
        excluded_dirs = [
            'node_modules/',
            'bower_components/',
            'vendor/',
            'dist/',
            'build/',
            'coverage/',
            '.git/',
            'fixtures/',
            'mocks/',
        ]
        
        path_lower = path.lower()
        
        for excluded in excluded_dirs:
            if excluded in path_lower:
                return True
        
        return False
    
    def get_test_command(self) -> str:
        """
        Get the command to run tests.
        
        Returns
        -------
        str
            Test command (varies by framework)
        """
        return "npm test"
    
    def get_test_file_count(self, repo: Dict[str, Any]) -> int:
        """
        Count the number of test files in repository.
        
        Parameters
        ----------
        repo : dict
            Repository metadata
            
        Returns
        -------
        int
            Number of test files
        """
        file_paths = self.get_file_paths(repo)
        test_files = []
        
        for path in file_paths:
            if self._is_excluded_path(path):
                continue
            
            for pattern in self.TEST_PATTERNS:
                if pattern in path.lower():
                    test_files.append(path)
                    break
            else:
                path_parts = path.lower().split('/')
                for test_dir in self.TEST_DIRS:
                    if test_dir in path_parts:
                        if any(path.endswith(ext) for ext in self.TS_EXTENSIONS):
                            test_files.append(path)
                            break
        
        return len(test_files)