from typing import Dict, Any, List
import json

from . import LanguageFilter


class TypeScriptJestFilter(LanguageFilter):
    """Filter accepting only TypeScript repositories with pure Jest."""

    TS_EXTENSIONS = {".ts", ".tsx"}
    PACKAGE_JSON_PATH = "package.json"

    TEST_SUFFIXES = (
        ".test.ts", ".test.tsx",
        ".spec.ts", ".spec.tsx",
    )

    TEST_DIRS = {"__tests__", "test", "tests", "spec", "specs"}

    EXCLUDED_DIRS = {
        "node_modules/", "dist/", "build/", "coverage/", ".git/",
        "vendor/", "__mocks__/", "cypress/", "playwright/",
        "e2e/", "integration/", "out/", "tmp/", "temp/",
    }

    OTHER_TEST_FRAMEWORKS = {
        "mocha", "chai", "sinon", "ava", "vitest", "vite",
        "uvu", "tap", "tape", "jasmine", "jasmine-core",
        "qunit", "cypress", "playwright", "webdriverio",
        "nightwatch", "protractor", "karma",
    }

    def get_language_name(self) -> str:
        return "TypeScript-Jest"

    def _extract_files_with_content(self, repo: Dict[str, Any]) -> List[Dict[str, str]]:
        """Extract files as {path, content} from repo['files']."""
        raw_files = repo.get("files") or []
        result = []

        for item in raw_files:
            if isinstance(item, str):
                result.append({"path": item, "content": None})
            elif isinstance(item, dict):
                path = (
                    item.get("path")
                    or item.get("name")
                    or item.get("filename")
                    or ""
                )
                content = item.get("content") or item.get("data") or None
                result.append({"path": path, "content": content})

        return result

    def _get_package_json(self, files_with_content: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Find and parse package.json."""
        for f in files_with_content:
            if f["path"].lower() == self.PACKAGE_JSON_PATH:
                content = f["content"]
                if not content:
                    continue
                try:
                    return json.loads(content)
                except json.JSONDecodeError:
                    continue
        return {}

    def _is_excluded_path(self, path: str) -> bool:
        """Check if path belongs to excluded directories."""
        return any(ex in path for ex in self.EXCLUDED_DIRS)

    def _find_test_files(self, files_with_content: List[Dict[str, Any]]) -> List[str]:
        """Find valid Jest test files by patterns and directories."""
        test_files = []

        for f in files_with_content:
            path = f["path"]
            lowered = path.lower()

            if self._is_excluded_path(lowered):
                continue

            if not any(lowered.endswith(ext) for ext in self.TS_EXTENSIONS):
                continue

            if lowered.endswith(self.TEST_SUFFIXES):
                test_files.append(path)
                continue

            parts = lowered.split("/")
            if any(d in parts for d in self.TEST_DIRS):
                test_files.append(path)

        return test_files

    def matches_language(self, repo: Dict[str, Any]) -> bool:
        """
        Repository is valid if:
        - Has package.json
        - TypeScript present in dependencies
        - Jest present in dependencies
        - NO other test frameworks
        - Has real Jest test files
        """
        files = self._extract_files_with_content(repo)

        if not any(f["path"].lower() == self.PACKAGE_JSON_PATH for f in files):
            return False

        pkg = self._get_package_json(files)
        if not pkg:
            return False

        deps = pkg.get("dependencies", {}) or {}
        dev_deps = pkg.get("devDependencies", {}) or {}
        all_deps = {**deps, **dev_deps}

        has_typescript = any(
            k == "typescript"
            or k == "ts-node"
            or k.startswith("@types/")
            for k in all_deps
        )
        if not has_typescript:
            return False

        has_jest = any(
            k == "jest"
            or k.startswith("jest-")
            or k.startswith("@jest/")
            or k == "ts-jest"
            for k in all_deps
        )
        if not has_jest:
            return False

        conflicting = {k for k in all_deps if k.lower() in self.OTHER_TEST_FRAMEWORKS}
        if conflicting:
            return False

        test_files = self._find_test_files(files)
        if len(test_files) == 0:
            return False

        return True

    def has_runnable_tests(self, repo: Dict[str, Any]) -> bool:
        """Repository is runnable if it matches strict Jest filter."""
        return self.matches_language(repo)

    def get_test_command(self) -> str:
        """Command always exits with returncode=0 for Docker pipeline."""
        return (
            "npx jest "
            "--json --outputFile=jest-results.json "
            "--passWithNoTests "
            "--runInBand "
            "--forceExit "
            "--maxWorkers=1 "
            "|| true"
        )

    def get_test_file_count(self, repo: Dict[str, Any]) -> int:
        """Count detected TypeScript Jest test files."""
        files = self._extract_files_with_content(repo)
        return len(self._find_test_files(files))