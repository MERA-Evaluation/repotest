"""
Language-specific repository filters for S3 data collection.
"""
from abc import ABC, abstractmethod
from typing import Dict, Any, List


class LanguageFilter(ABC):
    """Abstract base class for language-specific repository filters."""
    
    def __init__(self):
        self.language_name = self.get_language_name()
    
    @abstractmethod
    def get_language_name(self) -> str:
        """Return the language name (e.g., 'Go', 'Python', 'TypeScript')."""
        pass
    
    @abstractmethod
    def matches_language(self, repo: Dict[str, Any]) -> bool:
        """
        Check if repository is written in the target language.
        
        Parameters
        ----------
        repo : dict
            Repository metadata from S3
            
        Returns
        -------
        bool
            True if repository matches language criteria
        """
        pass
    
    @abstractmethod
    def has_runnable_tests(self, repo: Dict[str, Any]) -> bool:
        """
        Check if repository contains runnable tests.
        
        Parameters
        ----------
        repo : dict
            Repository metadata with 'files' field containing file structure
            
        Returns
        -------
        bool
            True if repository has tests that can be executed
        """
        pass
    
    def filter_repository(self, repo: Dict[str, Any]) -> bool:
        """
        Main filter method - combines language and test checks.
        
        Parameters
        ----------
        repo : dict
            Repository metadata
            
        Returns
        -------
        bool
            True if repository passes all filters
        """
        if not self.matches_language(repo):
            return False
        
        if not self.has_runnable_tests(repo):
            return False
        
        return True
    
    def get_file_paths(self, repo: Dict[str, Any]) -> List[str]:
        """
        Extract file paths from repository metadata.
        
        Parameters
        ----------
        repo : dict
            Repository metadata
            
        Returns
        -------
        list of str
            List of file paths
        """
        if 'files' not in repo or not isinstance(repo['files'], list):
            return []
        
        paths = []
        for file_entry in repo['files']:
            if isinstance(file_entry, dict) and 'path' in file_entry:
                paths.append(file_entry['path'])
        
        return paths
    
    def get_file_extensions(self, repo: Dict[str, Any]) -> set:
        """
        Get unique file extensions in repository.
        
        Parameters
        ----------
        repo : dict
            Repository metadata
            
        Returns
        -------
        set
            Set of file extensions (with dots, e.g., '.py', '.go')
        """
        paths = self.get_file_paths(repo)
        extensions = set()
        
        for path in paths:
            if '.' in path:
                ext = '.' + path.rsplit('.', 1)[1]
                extensions.add(ext)
        
        return extensions