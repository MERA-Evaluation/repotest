"""
Строгий фильтр для JavaScript/TypeScript-репозиториев,
которые используют ТОЛЬКО Jest (без Mocha, Vitest, Ava,
Jasmine, Cypress, Playwright и других тестовых систем).

Фильтр применяется к “богатым” S3-дампам, где есть содержимое файлов.

Требования:
1. Должен существовать package.json.
2. В зависимостях должен присутствовать jest или @jest/*.
3. НИКАКИХ других тестовых фреймворков в зависимостях.
4. Должен существовать минимум один реальный тестовый файл:
   - *.test.js / *.spec.ts
   - или лежащий в __tests__ / tests / spec / specs
5. Репозиторий должен быть исполняемым через `npx jest`.
"""

from typing import Dict, Any, List
import json

from . import LanguageFilter


class JavaScriptJestFilter(LanguageFilter):
    """Фильтр, принимающий только репозитории c чистым Jest."""

    # Разрешённые языковые расширения
    JS_EXTENSIONS = {".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs"}

    PACKAGE_JSON_PATH = "package.json"

    # Явные паттерны Jest-тестов
    TEST_SUFFIXES = (
        ".test.js", ".test.jsx", ".test.ts", ".test.tsx",
        ".spec.js", ".spec.jsx", ".spec.ts", ".spec.tsx",
    )

    # Тестовые каталоги
    TEST_DIRS = {"__tests__", "test", "tests", "spec", "specs"}

    # Исключающие каталоги
    EXCLUDED_DIRS = {
        "node_modules/", "dist/", "build/", "coverage/", ".git/",
        "vendor/", "__mocks__/", "cypress/", "playwright/",
        "e2e/", "integration/", "out/", "tmp/", "temp/",
    }

    # Запрещённые тестовые фреймворки
    OTHER_TEST_FRAMEWORKS = {
        "mocha",
        "chai",
        "sinon",
        "ava",
        "vitest",
        "vite",         # иногда используется вместо jest
        "uvu",
        "tap",
        "tape",
        "jasmine",
        "jasmine-core",
        "qunit",
        "cypress",
        "playwright",
        "webdriverio",
        "nightwatch",
        "protractor",
        "karma",
    }

    def get_language_name(self) -> str:
        return "JavaScript-Jest"

    # -------------------------------------------------------
    # Вспомогательные методы
    # -------------------------------------------------------

    def _extract_files_with_content(self, repo: Dict[str, Any]) -> List[Dict[str, str]]:
        """
        Извлекает список файлов в виде {path, content}.
        Поддерживает форматы:
        - list[str]
        - list[dict] с ключами path/name/filename/content/data
        """
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
        """Ищет и парсит package.json."""
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
        """Проверяет, что путь относится к исключённым каталогам."""
        return any(ex in path for ex in self.EXCLUDED_DIRS)

    # -------------------------------------------------------
    # Определение тестовых файлов
    # -------------------------------------------------------

    def _find_test_files(self, files_with_content: List[Dict[str, Any]]) -> List[str]:
        """Ищет валидные Jest-тесты по паттернам и каталогам."""
        test_files = []

        for f in files_with_content:
            path = f["path"]
            lowered = path.lower()

            # Пропускаем мусорные каталоги
            if self._is_excluded_path(lowered):
                continue

            # Проверка разрешённых расширений
            if not any(lowered.endswith(ext) for ext in self.JS_EXTENSIONS):
                continue

            # 1) Явные *.test.* / *.spec.*
            if lowered.endswith(self.TEST_SUFFIXES):
                test_files.append(path)
                continue

            # 2) Файлы внутри __tests__/spec/tests/
            parts = lowered.split("/")
            if any(d in parts for d in self.TEST_DIRS):
                test_files.append(path)

        return test_files

    # -------------------------------------------------------
    # Основная логика фильтра
    # -------------------------------------------------------

    def matches_language(self, repo: Dict[str, Any]) -> bool:
        """
        Репозиторий считается подходящим ТОЛЬКО если:
        - Есть package.json
        - Jest присутствует в зависимостях
        - НЕТ других тестовых систем
        - Есть реальные Jest-тесты
        """
        files = self._extract_files_with_content(repo)

        # Проверка наличия package.json
        if not any(f["path"].lower() == self.PACKAGE_JSON_PATH for f in files):
            return False

        pkg = self._get_package_json(files)
        if not pkg:
            return False

        deps = pkg.get("dependencies", {}) or {}
        dev_deps = pkg.get("devDependencies", {}) or {}
        all_deps = {**deps, **dev_deps}

        # --------- Проверка Jest ---------
        has_jest = any(
            k == "jest"
            or k.startswith("jest-")
            or k.startswith("@jest/")
            for k in all_deps
        )
        if not has_jest:
            return False

        # --------- Запрещённые фреймворки ---------
        conflicting = {k for k in all_deps if k.lower() in self.OTHER_TEST_FRAMEWORKS}
        if conflicting:
            return False

        # --------- Тестовые файлы ---------
        test_files = self._find_test_files(files)
        if len(test_files) == 0:
            return False

        return True

    def has_runnable_tests(self, repo: Dict[str, Any]) -> bool:
        """Репозиторий runnable, если соответствует строгому Jest-фильтру."""
        return self.matches_language(repo)

    def get_test_command(self) -> str:
        """
        Команда запуска Jest, всегда завершающаяся returncode=0
        (важно для Docker пайплайна).
        """
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
        """Количество найденных Jest-тестов."""
        files = self._extract_files_with_content(repo)
        return len(self._find_test_files(files))
