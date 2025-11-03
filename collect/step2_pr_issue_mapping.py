# step2_pr_issue_mapping.py
"""
Step 2: PR-Issue Mapping Construction

Finds closed issues and maps them to pull requests that resolved them.
"""
import json
import os
import time
import logging
from typing import Optional, Dict, Any, List
from tqdm import tqdm
import fire

from github_client import GitHubClient

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def get_path(dct: Dict, path: str) -> Any:
    """Navigate nested dictionary using path string."""
    ptr = dct
    for key in path.split('/'):
        if isinstance(ptr, dict) and key in ptr:
            ptr = ptr[key]
        else:
            return None
    return ptr


def extract_pr_issue_mappings(issue_data: Dict, owner: str, name: str) -> List[Dict]:
    """
    Extract PR-issue mappings from issue timeline.
    
    Parameters
    ----------
    issue_data : dict
        Issue node data with timeline items
    owner : str
        Repository owner
    name : str
        Repository name
        
    Returns
    -------
    list of dict
        List of PR-issue mappings
    """
    mappings = []
    issue_number = issue_data['number']
    timeline_items = issue_data.get('timelineItems', {}).get('nodes', [])
    
    logger.debug(f"Extracting mappings for issue #{issue_number}, {len(timeline_items)} timeline items")
    
    for item in timeline_items:
        # Check for CLOSED_EVENT (direct link)
        if item.get('closer'):
            pr_data = item['closer']
            mappings.append({
                "type": "linked",
                "issue_number": issue_number,
                "pr_number": pr_data['number'],
                "issue_repo": f"{owner}/{name}",
                "pr_repo": f"{pr_data['repository']['owner']['login']}/{pr_data['repository']['name']}",
                "mergedAt": pr_data['mergedAt'],
                "base_commit": pr_data['baseRefOid'],
                "merge_commit": get_path(pr_data, 'mergeCommit/oid'),
                "committed_date": get_path(pr_data, 'mergeCommit/committedDate')
            })
        
        # Check for CROSS_REFERENCED_EVENT (comment reference)
        if item.get('source'):
            pr_data = item['source']
            mappings.append({
                "type": "referenced",
                "issue_number": issue_number,
                "pr_number": pr_data['number'],
                "issue_repo": f"{owner}/{name}",
                "pr_repo": f"{pr_data['repository']['owner']['login']}/{pr_data['repository']['name']}",
                "mergedAt": pr_data['mergedAt'],
                "base_commit": pr_data['baseRefOid'],
                "merge_commit": get_path(pr_data, 'mergeCommit/oid'),
                "committed_date": get_path(pr_data, 'mergeCommit/committedDate')
            })
    
    logger.debug(f"Extracted {len(mappings)} mappings for issue #{issue_number}")
    return mappings


def fetch_repo_pr_issue_map(
    client: GitHubClient,
    owner: str,
    name: str,
    closed_after: str = "2020-01-01T00:00:00Z",
    max_issues: Optional[int] = None
) -> List[Dict]:
    """
    Fetch PR-issue mappings for a repository.
    
    Parameters
    ----------
    client : GitHubClient
        GitHub API client
    owner : str
        Repository owner
    name : str
        Repository name
    closed_after : str
        Only fetch issues closed after this date (ISO format)
    max_issues : int, optional
        Maximum number of issues to fetch
        
    Returns
    -------
    list of dict
        List of PR-issue mappings
    """
    logger.info(f"Fetching PR-issue map for {owner}/{name} (closed after {closed_after})")
    
    all_mappings = []
    issues_cursor = None
    date_ok = True
    issues_fetched = 0
    
    while date_ok:
        variables = {
            "owner": owner,
            "name": name,
            "cursor": issues_cursor,
            "timelineAfter": None
        }
        
        result = client.execute_query_from_file("issue_pr_map", variables)
        
        issues = result['data']['repository']['issues']
        edges = issues['edges']
        
        logger.debug(f"Fetched {len(edges)} issues (cursor: {issues_cursor})")
        
        for edge in edges:
            issue_node = edge['node']
            updated_at = issue_node['updatedAt']
            
            # Stop if we've gone past the date threshold
            if updated_at and updated_at < closed_after:
                logger.debug(f"Reached date threshold at issue #{issue_node['number']}")
                date_ok = False
                break
            
            # Extract mappings for this issue
            mappings = extract_pr_issue_mappings(issue_node, owner, name)
            
            # Add issue metadata to each mapping
            for mapping in mappings:
                mapping['issue_created_at'] = issue_node['createdAt']
                mapping['issue_closed_at'] = issue_node['closedAt']
                mapping['issue_updated_at'] = issue_node['updatedAt']
                mapping['issue_title'] = issue_node['title']
            
            all_mappings.extend(mappings)
            issues_fetched += 1
            
            if max_issues and issues_fetched >= max_issues:
                logger.info(f"Reached max_issues limit: {max_issues}")
                date_ok = False
                break
        
        # Check pagination
        page_info = issues['pageInfo']
        if page_info['hasNextPage'] and date_ok:
            issues_cursor = page_info['endCursor']
        else:
            break
        
        time.sleep(0.5)
    
    logger.info(f"Fetched {len(all_mappings)} PR-issue mappings from {issues_fetched} issues")
    return all_mappings


def build_pr_issue_mapping(
    input_file: str,
    output_file: str,
    github_token: Optional[str] = None,
    closed_after: str = "2020-01-01T00:00:00Z",
    checkpoint_file: Optional[str] = None,
    max_retries: int = 3,
    request_delay: float = 1.0
):
    """
    Build PR-issue mappings for repositories from step 1.
    
    Parameters
    ----------
    input_file : str
        Path to step1_output.jsonl
    output_file : str
        Path to output JSONL file
    github_token : str, optional
        GitHub API token
    closed_after : str
        Only fetch issues closed after this date (ISO format)
    checkpoint_file : str, optional
        Checkpoint file path
    max_retries : int
        Maximum retries per repository
    request_delay : float
        Delay between requests in seconds
    """
    logger.info("Starting PR-issue mapping construction")
    
    if github_token is None:
        github_token = os.environ.get('GITHUB_TOKEN')
        if not github_token:
            raise ValueError("GitHub token required")
    
    if checkpoint_file is None:
        checkpoint_file = f"{output_file}.checkpoint"
    
    # Load checkpoint
    processed_repos = set()
    if os.path.exists(checkpoint_file):
        with open(checkpoint_file, 'r') as f:
            processed_repos = set(line.strip() for line in f)
        logger.info(f"Loaded {len(processed_repos)} processed repos from checkpoint")
    
    # Load repositories from step 1
    repos = []
    with open(input_file, 'r') as f:
        for line in f:
            repo = json.loads(line)
            repos.append(repo)
    
    logger.info(f"Found {len(repos)} repositories from step 1")
    
    # Initialize client
    client = GitHubClient(github_token)
    client.print_limit()
    
    # Open output
    output_mode = 'a' if os.path.exists(output_file) else 'w'
    
    with open(output_file, output_mode) as out_f, \
         open(checkpoint_file, 'a') as chk_f:
        
        for repo in tqdm(repos, desc="Processing repos"):
            repo_name = repo['nameWithOwner']
            
            if repo_name in processed_repos:
                logger.debug(f"Skipping {repo_name} (already processed)")
                continue
            
            owner, name = repo_name.split('/')
            
            for attempt in range(max_retries):
                try:
                    mappings = fetch_repo_pr_issue_map(
                        client=client,
                        owner=owner,
                        name=name,
                        closed_after=closed_after
                    )
                    
                    print(f"{repo_name}: {len(mappings)} PR-issue mappings")
                    
                    # Write mappings
                    for mapping in mappings:
                        mapping['repo_name'] = repo_name
                        mapping['_step1_data'] = repo
                        out_f.write(json.dumps(mapping) + '\n')
                    
                    # Save checkpoint
                    chk_f.write(repo_name + '\n')
                    chk_f.flush()
                    out_f.flush()
                    
                    processed_repos.add(repo_name)
                    
                    time.sleep(request_delay)
                    break
                    
                except Exception as e:
                    logger.warning(f"Attempt {attempt + 1} failed for {repo_name}: {e}")
                    if attempt == max_retries - 1:
                        logger.error(f"Skipping {repo_name} after {max_retries} attempts")
                    time.sleep(5)
            
            if len(processed_repos) % 10 == 0:
                client.print_limit()
    
    logger.info(f"Done! Saved to {output_file}")


if __name__ == "__main__":
    fire.Fire(build_pr_issue_mapping)
