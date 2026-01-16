"""
JavaScript Mocha-only filter for S3 repository collection.
Strictly accepts ONLY repositories where `npm test` reliably runs Mocha tests.
Fully compatible with rich S3 dumps containing file contents.
"""
from typing import Dict, Any, List
import json

from . import LanguageFilter


class JavaScriptMochaFilter(LanguageFilter):
    """Strict filter: only JS/TS repositories with real, runnable Mocha tests via `npm test`."""

    JS_EXTENSIONS = {'.js', '.jsx', '.ts', '.tsx', '.mjs', '.cjs'}
    PACKAGE_JSON_PATH = 'package.json'

    TEST_PATTERNS = {
        '.test.js', '.test.jsx', '.test.ts', '.test.tsx',
        '.spec.js', '.spec.jsx', '.spec.ts', '.spec.tsx'
    }
    TEST_DIRS = {'__tests__', 'test', 'tests', 'spec', 'specs'}

    EXCLUDED_DIRS = {
        'node_modules/', 'dist/', 'build/', 'coverage/', '.git/',
        'vendor/', '__mocks__/', 'cypress/', 'playwright/', 'e2e/', 'integration/'
    }

    def get_language_name(self) -> str:
        """Return language name."""
        return "JavaScript-Mocha"

    def _extract_files_with_content(self, repo: Dict[str, Any]) -> List[Dict[str, str]]:
        """
        Extract list of files with path/content from repo['files'].
        Supports:
        - list[str]
        - list[dict] with 'path', 'content', 'name', etc.
        """
        raw_files = repo.get('files') or []
        result = []

        for item in raw_files:
            if isinstance(item, str):
                result.append({"path": item, "content": None})
            elif isinstance(item, dict):
                path = item.get('path') or item.get('name') or item.get('filename') or ''
                content = item.get('content') or item.get('data') or None
                result.append({"path": path, "content": content})
        return result

    def _get_package_json(self, files_with_content: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Find and parse package.json from files list."""
        for file in files_with_content:
            if file['path'].lower() == self.PACKAGE_JSON_PATH:
                content = file['content']
                if not content:
                    continue
                try:
                    return json.loads(content)
                except json.JSONDecodeError:
                    continue
        return {}

    def matches_language(self, repo: Dict[str, Any]) -> bool:
        """
        Strict check: repository must satisfy ALL conditions:
        1. Has package.json (in files)
        2. package.json has "scripts.test" that contains "mocha"
        3. Mocha is listed in dependencies/devDependencies
        4. Has at least one real .test.js / .spec.ts / file in test/ etc.
        5. Does NOT have jest in dependencies (Mocha-only)
        """
        files_with_content = self._extract_files_with_content(repo)

        has_package_json = any(
            f['path'].lower() == self.PACKAGE_JSON_PATH for f in files_with_content
        )
        if not has_package_json:
            return False

        pkg = self._get_package_json(files_with_content)
        if not pkg:
            return False

        scripts = pkg.get("scripts") or {}
        test_script = str(scripts.get("test", "")).lower()

        # Must have test script with mocha
        if not test_script or "no test specified" in test_script or "exit 1" in test_script:
            return False
        if "mocha" not in test_script:
            return False

        deps = pkg.get("dependencies", {}) or {}
        dev_deps = pkg.get("devDependencies", {}) or {}
        all_deps = {**deps, **dev_deps}

        # Must have Mocha
        has_mocha = "mocha" in all_deps
        if not has_mocha:
            return False

        # Must NOT have Jest (Mocha-only filter)
        has_jest = any(k == "jest" or k.startswith("jest-") or "jest" in k for k in all_deps)
        if has_jest:
            return False

        # Must have at least one real test file
        test_files = self._find_test_files(files_with_content)
        return len(test_files) > 0

    def has_runnable_tests(self, repo: Dict[str, Any]) -> bool:
        """Same as matches_language — strict and reliable."""
        return self.matches_language(repo)

    def _find_test_files(self, files_with_content: List[Dict[str, Any]]) -> List[str]:
        """Find valid Mocha test files by path."""
        test_files = []
        for file in files_with_content:
            path = file['path']
            lowered = path.lower()

            if self._is_excluded_path(lowered):
                continue

            if not any(lowered.endswith(ext) for ext in self.JS_EXTENSIONS):
                continue

            if any(pat in lowered for pat in self.TEST_PATTERNS):
                test_files.append(path)
                continue

            if any(d in lowered.split('/') for d in self.TEST_DIRS):
                test_files.append(path)

        return test_files

    def _is_excluded_path(self, path: str) -> bool:
        """Exclude junk and non-unit-test directories."""
        return any(ex in path for ex in self.EXCLUDED_DIRS)

    def get_test_command(self) -> str:
        """Guaranteed working test command."""
        return "npm test"

    def get_test_file_count(self, repo: Dict[str, Any]) -> int:
        """Count detected test files."""
        files = self._extract_files_with_content(repo)
        return len(self._find_test_files(files))