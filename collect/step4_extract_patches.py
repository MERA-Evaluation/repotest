# pipeline/steps/step4_patch_extraction.py
"""
Step 4: Patch Extraction and Validation

Extracts git diffs between base and merge commits, separates test and non-test patches.
"""
import json
import os
import re
import logging
from typing import Optional, Tuple
from tqdm import tqdm
import fire
import subprocess
import shutil
import pandas as pd

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def clone_repo(repo_url: str, target_dir: str, depth: int = 1) -> bool:
    """Clone a git repository."""
    logger.debug(f"Cloning {repo_url} to {target_dir}")
    
    try:
        result = subprocess.run(
            ["git", "clone", "--depth", str(depth), repo_url, target_dir],
            capture_output=True,
            text=True,
            timeout=300
        )
        
        if result.returncode != 0:
            logger.error(f"Clone failed: {result.stderr}")
            return False
        
        logger.debug(f"Successfully cloned {repo_url}")
        return True
        
    except Exception as e:
        logger.error(f"Clone exception: {e}")
        return False


def fetch_commits(repo_dir: str, base_commit: str, merge_commit: str) -> bool:
    """Fetch specific commits if not present."""
    logger.debug(f"Ensuring commits {base_commit[:7]} and {merge_commit[:7]} exist")
    
    try:
        # Check if shallow clone needs to be unshallowed
        is_shallow = subprocess.run(
            ["git", "-C", repo_dir, "rev-parse", "--is-shallow-repository"],
            capture_output=True,
            text=True
        ).stdout.strip() == "true"
        
        if is_shallow:
            logger.debug("Unshallowing repository")
            subprocess.run(
                ["git", "-C", repo_dir, "fetch", "--unshallow"],
                capture_output=True,
                text=True,
                timeout=300
            )
        
        # Fetch the specific commits
        for commit in [base_commit, merge_commit]:
            result = subprocess.run(
                ["git", "-C", repo_dir, "cat-file", "-e", commit],
                capture_output=True,
                text=True
            )
            
            if result.returncode != 0:
                logger.debug(f"Fetching commit {commit[:7]}")
                subprocess.run(
                    ["git", "-C", repo_dir, "fetch", "origin", commit],
                    capture_output=True,
                    text=True,
                    timeout=120
                )
        
        return True
        
    except Exception as e:
        logger.error(f"Fetch commits exception: {e}")
        return False


def get_git_diff(repo_dir: str, base_commit: str, merge_commit: str) -> Optional[str]:
    """Get git diff between two commits."""
    logger.debug(f"Getting diff between {base_commit[:7]} and {merge_commit[:7]}")
    
    try:
        result = subprocess.run(
            ["git", "-C", repo_dir, "diff", base_commit, merge_commit],
            capture_output=True,
            text=True,
            timeout=60
        )
        
        if result.returncode != 0:
            logger.error(f"Git diff failed: {result.stderr}")
            return None
        
        diff = result.stdout
        logger.debug(f"Diff size: {len(diff)} chars")
        return diff
        
    except Exception as e:
        logger.error(f"Git diff exception: {e}")
        return None


def parse_diff_by_file(full_diff: str) -> dict:
    """Parse full diff into per-file diffs."""
    file_diffs = {}
    current_file = None
    current_diff = []
    
    for line in full_diff.split('\n'):
        if line.startswith('diff --git'):
            if current_file:
                file_diffs[current_file] = '\n'.join(current_diff)
            
            parts = line.split()
            if len(parts) >= 4:
                filepath = parts[2].lstrip('a/')
                current_file = filepath
                current_diff = [line]
            else:
                current_file = None
                current_diff = []
        elif current_file:
            current_diff.append(line)
    
    if current_file:
        file_diffs[current_file] = '\n'.join(current_diff)
    
    return file_diffs


def split_test_patch(
    full_diff: str,
    test_files_regexp: str = r"(tests?/|test_.*\.py$|.*_test\.py$)"
) -> Tuple[str, str]:
    """Split diff into test and non-test patches."""
    logger.debug(f"Splitting patch with test pattern: {test_files_regexp}")
    
    file_diffs = parse_diff_by_file(full_diff)
    test_pattern = re.compile(test_files_regexp)
    
    test_files = []
    non_test_files = []
    
    for filepath, file_diff in file_diffs.items():
        if test_pattern.search(filepath):
            test_files.append(file_diff)
        else:
            non_test_files.append(file_diff)
    
    test_patch = '\n'.join(test_files)
    patch = '\n'.join(non_test_files)
    
    logger.debug(f"Split: {len(test_files)} test files, {len(non_test_files)} non-test files")
    
    return test_patch, patch


def extract_patches(
    input_file: str,
    output_file: str,
    cache_dir: str = "data/repo_cache",
    test_files_regexp: str = r"(tests?/|test_.*\.py$|.*_test\.py$)",
    checkpoint_file: Optional[str] = None
):
    """
    Extract patches from git repositories.
    
    Parameters
    ----------
    input_file : str
        Path to step3_output.jsonl
    output_file : str
        Path to output JSONL file
    cache_dir : str
        Directory for caching cloned repositories
    test_files_regexp : str
        Regex pattern to match test files
    checkpoint_file : str, optional
        Checkpoint file path
    """
    logger.info("Starting patch extraction")
    
    if checkpoint_file is None:
        checkpoint_file = f"{output_file}.checkpoint"
    
    # Create cache directory
    os.makedirs(cache_dir, exist_ok=True)
    
    # Load checkpoint
    processed_items = set()
    if os.path.exists(checkpoint_file):
        with open(checkpoint_file, 'r') as f:
            processed_items = set(line.strip() for line in f)
        logger.info(f"Loaded {len(processed_items)} processed items from checkpoint")
    
    # Load data as pandas DataFrame
    df = pd.read_json(input_file, lines=True)
    logger.info(f"Loaded {len(df)} rows from {input_file}")
    
    # Convert datetime columns to strings
    for col in ['issue_created_at', 'issue_closed_at', 'issue_updated_at']:
        df[col] = df[col].astype(str)
    
    # Filter valid rows
    df['has_valid_mapping'] = df['map_issue_pr_ok'].fillna(False)
    df['has_base_commit'] = df['base_commit'].notna()
    df['has_merge_commit'] = df['merge_commit'].notna()
    df['should_process'] = df['has_valid_mapping'] & df['has_base_commit'] & df['has_merge_commit']
    
    # Print statistics
    num_all = len(df)
    num_map_ok = df['has_valid_mapping'].sum()
    num_commits_ok = (df['has_base_commit'] & df['has_merge_commit']).sum()
    num_will_process = df['should_process'].sum()
    
    logger.info(f"All: {num_all}")
    logger.info(f"map_issue_pr_ok: {num_map_ok}")
    logger.info(f"commit is not None: {num_commits_ok}")
    logger.info(f"will process: {num_will_process}")
    
    # Split into valid and invalid
    df_valid = df[df['should_process']].copy()
    df_invalid = df[~df['should_process']].copy()
    
    # Open output
    output_mode = 'a' if os.path.exists(output_file) else 'w'
    pred_repo = None
    
    with open(output_file, output_mode) as out_f, \
         open(checkpoint_file, 'a') as chk_f:
        
        # Write invalid rows immediately
        for _, row in df_invalid.iterrows():
            item_id = f"{row['repo_name']}#{row.get('pr_number', 'none')}#{row.get('issue_number', 'none')}"
            
            if item_id not in processed_items:
                row_dict = row.to_dict()
                row_dict['patch_extraction_status'] = 'skipped_invalid'
                out_f.write(json.dumps(row_dict) + '\n')
                chk_f.write(item_id + '\n')
                processed_items.add(item_id)
        
        chk_f.flush()
        out_f.flush()
        
        # Process valid rows
        for _, row in tqdm(df_valid.iterrows(), total=len(df_valid), desc="Extracting patches"):
            item_id = f"{row['repo_name']}#{row['pr_number']}#{row['issue_number']}"
            
            if item_id in processed_items:
                logger.debug(f"Skipping {item_id} (already processed)")
                continue
            
            repo_name = row['repo_name']
            base_commit = row['base_commit']
            merge_commit = row['merge_commit']
            
            repo_url = f"https://github.com/{repo_name}.git"
            repo_dir = os.path.join(cache_dir, repo_name.replace('/', '_'))
            
            # Cleanup repo if requested
            if os.path.exists(repo_dir) and (pred_repo is not None) and (pred_repo != repo_name):
                shutil.rmtree(repo_dir)
                logger.debug(f"Cleaned up {repo_dir}")
            pred_repo = repo_name
            
            
            
            row_dict = row.to_dict()
            
            try:
                # Clone if not exists
                if not os.path.exists(repo_dir):
                    success = clone_repo(repo_url, repo_dir)
                    if not success:
                        logger.warning(f"Failed to clone {repo_name}")
                        row_dict['patch_extraction_status'] = 'clone_failed'
                        out_f.write(json.dumps(row_dict) + '\n')
                        chk_f.write(item_id + '\n')
                        chk_f.flush()
                        out_f.flush()
                        continue
                
                # Fetch commits if needed
                success = fetch_commits(repo_dir, base_commit, merge_commit)
                if not success:
                    logger.warning(f"Failed to fetch commits for {item_id}")
                    row_dict['patch_extraction_status'] = 'fetch_failed'
                    out_f.write(json.dumps(row_dict) + '\n')
                    chk_f.write(item_id + '\n')
                    chk_f.flush()
                    out_f.flush()
                    continue
                
                # Get diff
                full_diff = get_git_diff(repo_dir, base_commit, merge_commit)
                if full_diff is None:
                    logger.warning(f"Failed to get diff for {item_id}")
                    row_dict['patch_extraction_status'] = 'diff_failed'
                    out_f.write(json.dumps(row_dict) + '\n')
                    chk_f.write(item_id + '\n')
                    chk_f.flush()
                    out_f.flush()
                    continue
                
                # Split into test and non-test patches
                test_patch, patch = split_test_patch(full_diff, test_files_regexp)
                
                # Add to row
                row_dict['full_patch'] = full_diff + (full'\n' if full_diff and full_diff[-1] != '\n' else '')
                row_dict['test_patch'] = test_patch + (test_'\n' if test_patch and test_patch[-1] != '\n' else '')
                row_dict['patch'] = patch + ('\n' if patch and patch[-1] != '\n' else '')
                row_dict['patch_extraction_status'] = 'success'
                
                logger.debug(f"Extracted patches for {item_id}: full={len(full_diff)}, test={len(test_patch)}, patch={len(patch)}")
                
                
            except Exception as e:
                logger.error(f"Exception processing {item_id}: {e}")
                row_dict['patch_extraction_status'] = 'exception'
                row_dict['patch_extraction_error'] = str(e)
            
            # Write result
            out_f.write(json.dumps(row_dict) + '\n')
            chk_f.write(item_id + '\n')
            chk_f.flush()
            out_f.flush()
            
            processed_items.add(item_id)
    
    logger.info(f"Done! Saved to {output_file}")


if __name__ == "__main__":
    fire.Fire(extract_patches)
