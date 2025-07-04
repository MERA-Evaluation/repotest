from abc import ABC, abstractmethod
import os
import git
import tempfile
from repotest.constants import DEFAULT_CACHE_FOLDER, REPOTEST_MAIN_FOLDER
from repotest.core.exceptions import GitCloneFailed, GitCheckoutFailed

from functools import cached_property
import time
from tenacity import retry, stop_after_attempt, wait_chain, wait_fixed
import uuid
from shutil import copytree, rmtree
from pathlib import Path
import subprocess
import fcntl

import logging
logger = logging.getLogger("repotest") 

def wait_git_release():
    """
        We have a lot of errors if git clone makes in 50+ threads, 
        so as temperary solution we do 1 git clone at 1 time. not more
        This affect only first run
    """
    GIT_LOCK_FILE = Path(os.path.join(REPOTEST_MAIN_FOLDER, "git_operations.lock"))
    with open(GIT_LOCK_FILE, "w") as lock_file:
        fcntl.flock(lock_file, fcntl.LOCK_EX)  # Exclusive lock  


class AbstractRepo(ABC):
    """
    Abstract base class for managing a Git repository.

    Parameters
    ----------
    repo : str
        Name of the repository.
    base_commit : str, optional
        The commit hash to checkout (default is None).
    default_cache_folder : str, optional
        Default folder to cache the cloned repository 
        (default is `DEFAULT_CACHE_FOLDER`).
    default_url : str, optional
        Base URL of the repository source (default is 'http://github.com').
    """

    cache_folder = None
    _FALL_WITH_TIMEOUT_EXCEPTION = False
    _MODE = "collect"

    @cached_property
    def _base_instance_id(self):
        """
        Returns a unique identifier for the repository instance.
        """
        return (self.repo.replace('/', '--') + '--'  + self.base_commit).lower()
    
    @property
    def instance_id(self) -> str:
        """
        Returns a unique identifier (for test it contain some random hash)
        """
        if self._MODE == "collect":
            return self._base_instance_id
        else:
            #ToDo: refactor logic to have totaly random cache
            return self._base_instance_id + "-" + self._INIT_TIME_HASH
    
    def __init__(self, 
                 repo: str, 
                 base_commit: str,
                 default_cache_folder: str = DEFAULT_CACHE_FOLDER, 
                 default_url: str = 'http://github.com'
                 ):
        self._INIT_TIME_HASH = str(time.time()).split('.')[-1]

        assert base_commit is not None
        self.repo = repo
        self.base_commit = base_commit
        self.default_cache_folder = default_cache_folder

        self.original_repo_folder = os.path.join(self.default_cache_folder, repo)
        self.cache_folder = os.path.abspath(os.path.join(self.default_cache_folder, "../runs/", self.run_id))

        self.default_url = default_url
        self.url = os.path.join(self.default_url, repo)

        logger.debug(f"{self.__class__.__name__}(repo={repo}, base_commit={base_commit}, default_url={default_url}, default_url={default_url} #cache_folder={self.cache_folder}")
        #ToDo: think should it be at init. At parallel run there could be multiple instances of the same repo
        #Probably there should be a semafore for this implemented somewhere
        self.clone()

    # @retry(
    #     stop=stop_after_attempt(2),  # Retry 2 times
    #     wait=wait_chain(
    #         wait_fixed(1),  # First retry after 1s
    #         wait_fixed(5),   # Second retry after 5s
    #         wait_fixed(10)   # Second retry after 10s
    #     )
    # )
    def single_git_clone(self):
        """
            git clone has some limit
            will do git clone with tenacity
        """
        wait_git_release()

        #ToDo: add checking that repo exist
        if not os.path.exists(self.original_repo_folder):
            self._repo = git.Repo.clone_from(self.url, self.original_repo_folder)
        
        copytree(self.original_repo_folder, self.cache_folder, dirs_exist_ok=True)
        self._repo = git.Repo(self.cache_folder)

        logger.debug(f"Checking out commit {self.base_commit}")
        try:
            try:
                self._repo.git.checkout(self.base_commit)
            except git.GitCommandError as e:
                logger.critical(f"We did force checkout for {self.cache_folder} base_commit={self.base_commit}")
                logger.critical("Please check that this action is not damage pipeline")
                self._repo.git.checkout(self.base_commit, force=True)
        except git.GitCommandError as e:
            logger.critical("Checkout failed %s"%self)
            logger.critical(e, exc_info=True)
            raise GitCheckoutFailed(str(self))
        
        logger.info("Repository is loaded and checked out to the specified commit.")


    def __del__(self):
        """
        Cleanup the repository.
        """
        logger.debug("docker.base.__del__")
        if os.path.exists(self.cache_folder):
            logger.debug(f"Removing repository cache folder {self.cache_folder}")
            rmtree(self.cache_folder)


    def clone(self):
        """
        Clone the repository from the remote source or open it if it already exists.
        """
        if not os.path.exists(os.path.join(self.cache_folder, ".git")):
            logger.debug(f"Cloning repository {self.url} into {self.cache_folder}")
            try:
                self.single_git_clone()
            except git.GitCommandError:
                logger.critical("Clone failed %s"%self)
                raise GitCloneFailed(str(self))
        else:
            logger.debug(f"Repository already exists in {self.cache_folder}, opening the repo.")
            self._repo = git.Repo(self.cache_folder)

    def apply_patch_fn(self, patch_file):
        """
        Apply a Git patch to the repository.

        Parameters
        ----------
        patch_file : str
            Path to the patch file to be applied.
        """
        self._repo.git.execute(['git', 'apply', patch_file])

    def apply_patch(self, git_patch):
        """
        Apply a patch string to the repository.

        Parameters
        ----------
        git_patch : str
            Git patch content as a string.
        """
        if (not git_patch) or (git_patch.strip() == ""):
            logger.warning(f"Empty git patch for %s", self)
            return
        
        if not git_patch.startswith("diff --git"):
            logger.warning(f"Git format is frong, not contain diff --git for %s", self)
            return
        
        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                patch_file_path = os.path.join(temp_dir, "patch.diff")
                logger.debug(f"Saving Git patch to {patch_file_path}")
                with open(patch_file_path, "w") as patch_file:
                    patch_file.write(git_patch)
                logger.debug("Applying patch to repository")
                self.apply_patch_fn(patch_file_path)
        except Exception as e:
            logger.critical("critical faile %s", self)
            logger.critical("git_patch %s", git_patch)
            logger.critical(e, exc_info=True)
            raise e

    def get_git_diff(self):
        """Get git diff"""
        # git add -A
        self._repo.git.add(A=True)
        # echo git diff
        diff = self._repo.git.diff(self.base_commit)
        # git reset HEAD
        self._repo.git.reset('HEAD')
        return diff
    
    @abstractmethod
    def run_test(self):
        """
        Abstract method to execute tests on the repository.

        This method must be implemented by subclasses.
        """
        pass

    def add_m2_to_gitignore(self):
        #ToDo: refactor this logic is not clear
        # Idea to have .mw folder at every repo level
        # But if we don't want to download it we also print this to gitignore
        # This affect clean(), but not affect hard_clean()
        fn = os.path.join(self.cache_folder, ".gitignore")
        if os.path.exists(fn):
            txt_gitignore = open(fn, "r").read()
            if "\n.m2\n" not in txt_gitignore:
                with open(fn, "a") as f:
                    f.write("\n.m2\n")    
        else:
            with open(fn, "w+") as f:
                f.write("\n.m2\n")
    
    def clean(self):
        """
        Reset the repository to its original state by discarding changes and cleaning files.
        Ignore files from gitignore
        """
        logger.info("clean")
        # self.add_m2_to_gitignore()
        self._repo.git.checkout('.')
        self._repo.git.clean('-fd')

    def hard_clean(self):
        """
        Reset the repository to its original state by discarding changes and cleaning files.
        """
        logger.info("hard clean")
        
        self._repo.git.reset('--hard')
        self._repo.git.clean('-fdx')
        logger.error("This place contain a bug, so raise exception")
    
    @cached_property
    def run_id(self):
        # Generate a UUID and truncate it to 8 characters
        short_hash = uuid.uuid4().hex[:8]
        return short_hash
    
    def status(self):
        self._repo.status()

    def _fn_relative_to_absolute(self, fn_relative: str) -> str:
        fn = os.path.join(self.cache_folder, fn_relative)
        assert os.path.exists(fn)
        return fn
    
    def change_file(self, fn_relative: str, code: str):
        fn = self._fn_relative_to_absolute(fn_relative)        
        open(fn, "w+").write(code)
    
    def file_contain(self, fn_relative, substring):
        fn = self._fn_relative_to_absolute(fn_relative)
        return substring in open(fn, "r").read()

    def change_file_realcode(self, fn_relative, left_context, gt, right_context):
        assert self.file_contain(fn_relative, left_context)
        
        right_context = right_context
        while right_context and right_context[-1] == '\n':
            right_context = right_context[:-1]
        
        assert self.file_contain(fn_relative, right_context)
        self.change_file(fn_relative, 
                         left_context + '\n' + gt + "\n" + right_context
                         )
    
    def _get_git_diff_before_after(self, base_commit_before: str, base_commit_after: str, binary: bool) -> str:
        """
        Fetch git diff between two commits in the specified repository folder.
        
        Parameters
        ----------
            base_commit_before: The older commit hash
            base_commit_after: The newer commit hash
        
        Returns
        -------
            The git diff as a string
        """
        # Convert to absolute path and resolve any symlinks
        folder = str(Path(self.cache_folder).resolve())
        
        # Run git diff command
        result = subprocess.run(
            ["git", "-C", folder, "diff"] +\
            (["--binary"] if binary else []) + \
            [f"{base_commit_before}..{base_commit_after}"],
            capture_output=True,
            text=True,
            check=True
        )
        return result.stdout

    @staticmethod
    def _get_test_patch(git_diff: str) -> str:
        """
        Extract test-related changes from the git diff.
        
        Parameters
        ----------
            git_diff: The full git diff string
            
        Returns
        -------
            A diff string containing only test files (files that match common test patterns)
        """
        test_patches = []
        current_patch = []
        in_patch = False
        is_test_file = False
        
        for line in git_diff.splitlines(keepends=True):
            if line.startswith("diff --git"):
                # Process the previous patch if we were in one
                if in_patch and is_test_file:
                    test_patches.extend(current_patch)
                
                # Reset for new patch
                current_patch = [line]
                in_patch = True
                is_test_file = False
                
                # Check if this is a test file
                if "test/" in line or "tests/" in line or "_test.py" in line or "test_" in line:
                    is_test_file = True
            elif in_patch:
                current_patch.append(line)
        
        # Add the last patch if it was a test file
        if in_patch and is_test_file:
            test_patches.extend(current_patch)
        
        return "".join(test_patches)

    @staticmethod
    def _get_gold_patch(git_diff: str) -> str:
        """
        Extract non-test-related changes from the git diff.
        
        Parameters
        ----------
            git_diff: The full git diff string
            
        Returns
        -------
            A diff string containing only non-test files
        """
        other_patches = []
        current_patch = []
        in_patch = False
        is_test_file = False
        
        for line in git_diff.splitlines(keepends=True):
            if line.startswith("diff --git"):
                # Process the previous patch if we were in one
                if in_patch and not is_test_file:
                    other_patches.extend(current_patch)
                
                # Reset for new patch
                current_patch = [line]
                in_patch = True
                is_test_file = False
                
                # Check if this is a test file
                if "test/" in line or "tests/" in line or "_test.py" in line or "test_" in line:
                    is_test_file = True
            elif in_patch:
                current_patch.append(line)
        
        # Add the last patch if it wasn't a test file
        if in_patch and not is_test_file:
            other_patches.extend(current_patch)
        
        return "".join(other_patches)

    def get_liveswebench_patch_dict(self, base_commit_before, base_commit_after, binary=True):
        """
        Generate patch information between two Git commits for LiveSWeBench evaluation.

        Computes the diff between two Git commits and extracts relevant patch
        data, including test and gold standard patches.

        Parameters
        ----------
        base_commit_before : str
            The Git commit hash representing the base (earlier) commit.
        base_commit_after : str
            The Git commit hash representing the target (later) commit.

        Returns
        -------
        dict
            Dictionary with the following keys:
            
            - 'full_path' : str
                Path to the full diff file between the two commits.
            - 'test_patch' : str
                Extracted test patch from the full diff.
            - 'gold_patch' : str
                Extracted gold/reference patch from the full diff.
        """
        full_path = self._get_git_diff_before_after(base_commit_before=base_commit_before, 
                                                    base_commit_after=base_commit_after,
                                                    binary=binary
                                                   )
        test_patch = self._get_test_patch(full_path)
        gold_patch = self._get_gold_patch(full_path)

        return {"full_path": full_path,
                "test_patch": test_patch,
                "gold_patch": gold_patch
               }
    
    def __repr__(self):
        return f'{self.__class__.__name__}(repo="{self.repo}", cache_folder="{self.cache_folder}", base_commit="{self.base_commit}")'