import os
from typing import Union

from repotest.core.base import AbstractRepo
from repotest.utils.java.java_test_fixer import JavaTestFixer
from repotest.utils.java.pom_file_fixer import PomFileFixer


class GitDiffWrapper:
    """
    A class that wraps basic Git operations in a repository, including
    changing file content, viewing the git diff, and resetting the repository
    to its initial state.
    """

    def __init__(self, repo: AbstractRepo, base_commit: str) -> None:
        """
        Initializes the GitDiffWrapper for a specific repository.

        Parameters
        ----------
        repo : str
            The name of the repository (folder) inside the cache folder.
        default_cache_folder : str, optional
            The default folder where all repositories are stored (default is `DEFAULT_CACHE_FOLDER`).
        """
        self.cache_folder = repo.cache_folder
        assert base_commit == repo.base_commit
        self.base_commit = repo.base_commit

        # Initialize the git repository at the provided path
        self._repo = repo._repo

    def change(self, fn: str, text: str) -> None:
        """
        Change the content of the file `fn` to the given `text` content.
        The file is overwritten with the new content, and the change is staged
        for commit.

        Parameters
        ----------
        fn : str
            The file name (relative to the repository root) to be modified.
        text : str
            The new content to write into the specified file.

        Returns
        -------
        None
            This function does not return any value.
        """
        file_path = os.path.join(self.cache_folder, fn)

        # Write the new content to the file
        with open(file_path, "w") as f:
            f.write(text)

        # Stage the file to be committed
        self._repo.index.add([fn])
        self._repo.index.commit(f"Update {fn}")  # Commit the change to trigger a diff
        return self

    def change_test(self, fn_test: str, str_test: str, str_source: str):
        """
        Logic copied from old pipeline, should be refactored a lot
        """
        fixer = JavaTestFixer()
        code = fixer.correct_code(source_code=str_source, test_code=str_test)
        fn = os.path.join(self.cache_folder, fn_test)
        open(fn, "w").write(code)

    def fix_pom_file(self) -> None:
        pom_fixer = PomFileFixer()
        pom_fixer.fix_pom_file_in_package(self.cache_folder)

    def git_diff(self, n_max_files: Union[int, None] = None) -> str:
        """
        Get the current git diff of the repository. This shows the differences
        between the working directory and the last commit, including staged changes.

        Returns
        -------
        str
            A string containing the git diff output, showing the changes.

        Notes
        -----
        The returned string includes all changes that are staged or not yet committed.
        If there are no changes, it will return an empty string.
        """
        # Check if there are any staged changes
        diff = self._repo.git.diff(self.base_commit)  # Get the git diff

        # ToDo: delete this line, when it is going to be clear chat origin/HEAD is always local latest commit
        # print(diff)
        if n_max_files is not None:
            if diff.count("diff --git ") > n_max_files:
                raise ValueError(f'diff.count("diff --git ") != 1)\n{diff}')

        # Git diff includes a newline at the end, so we add one if it's missing
        if diff and diff[-1] != "\n":
            diff += "\n"

        return diff

    def clean(self) -> None:
        """
        Reset the repository to the initial state by discarding all uncommitted changes.

        Returns
        -------
        None
            This function does not return any value.

        Notes
        -----
        This is a hard reset, which means all uncommitted changes in the working directory
        and staging area will be lost.
        """
        if self.base_commit:
            self._repo.git.checkout(self.base_commit)
        else:
            # ToDo: I am not sure that this gonna work
            self._repo.git.checkout(".")
        self._repo.git.clean("-fd")
        return self
