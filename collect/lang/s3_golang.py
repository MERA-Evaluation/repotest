"""
Go language filter for S3 repository collection.
"""
from typing import Dict, Any
from . import LanguageFilter


class GoFilter(LanguageFilter):
    """Filter for Go repositories with runnable tests."""
    
    GO_EXTENSIONS = {'.go'}
    TEST_FILE_SUFFIX = '_test.go'
    GO_MOD_FILE = 'go.mod'
    
    def get_language_name(self) -> str:
        """Return language name."""
        return "Go"
    
    def matches_language(self, repo: Dict[str, Any]) -> bool:
        """
        Check if repository is a Go project.
        
        Criteria:
        1. Has .go files
        2. Preferably has go.mod (but not strictly required for older projects)
        3. Language field (if present) should indicate Go
        
        Parameters
        ----------
        repo : dict
            Repository metadata
            
        Returns
        -------
        bool
            True if repository is a Go project
        """
        language_field = repo.get('language')
        if language_field and isinstance(language_field, str):
            if language_field.lower() in ['go', 'golang']:
                return True
        
        file_paths = self.get_file_paths(repo)
        has_go_files = any(path.endswith('.go') for path in file_paths)
        
        if not has_go_files:
            return False
        
        has_go_mod = any(path == self.GO_MOD_FILE or path.startswith(f'{self.GO_MOD_FILE}/') 
                         for path in file_paths)
        has_root_go = any('/' not in path and path.endswith('.go') 
                          for path in file_paths)
        
        return has_go_mod or has_root_go
    
    def has_runnable_tests(self, repo: Dict[str, Any]) -> bool:
        """
        Check if repository has runnable Go tests.
        
        Criteria for runnable tests:
        1. Has at least one *_test.go file
        2. Test files are not in vendor/ or third_party/ directories
        3. Repository has go.mod OR has a valid Go project structure
        
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
        
        test_files = [
            path for path in file_paths 
            if path.endswith(self.TEST_FILE_SUFFIX)
        ]
        
        if not test_files:
            return False
        
        valid_test_files = [
            path for path in test_files
            if not self._is_excluded_path(path)
        ]
        
        if not valid_test_files:
            return False
        
        # Check for go.mod (modern Go projects)
        has_go_mod = any(path == self.GO_MOD_FILE for path in file_paths)
        
        if has_go_mod:
            return True
        
        # For older projects without go.mod, check for reasonable structure
        # Should have .go files alongside test files
        test_dirs = set()
        for test_file in valid_test_files:
            if '/' in test_file:
                test_dir = test_file.rsplit('/', 1)[0]
                test_dirs.add(test_dir)
            else:
                test_dirs.add('')  # root directory
        
        # Check if there are corresponding .go files (non-test) in test directories
        for test_dir in test_dirs:
            has_source_files = any(
                path.endswith('.go') and 
                not path.endswith(self.TEST_FILE_SUFFIX) and
                (path.startswith(f"{test_dir}/") if test_dir else '/' not in path)
                for path in file_paths
            )
            if has_source_files:
                return True
        
        return False
    
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
            'vendor/',
            'third_party/',
            'third-party/',
            'node_modules/',
            '.git/',
            'testdata/',
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
            Test command
        """
        return "go test"
    
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
        test_files = [
            path for path in file_paths 
            if path.endswith(self.TEST_FILE_SUFFIX) and not self._is_excluded_path(path)
        ]
        return len(test_files)