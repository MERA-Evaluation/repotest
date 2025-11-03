# pipeline/steps/step3_metadata_extraction.py
"""
Step 3: Metadata Extraction and Filtering

Validates PR-issue mappings and extracts metadata (comments, bodies, titles).
"""
import json
import os
import time
import logging
from typing import Optional, Dict, Any, List, Set, Tuple
from collections import defaultdict
from tqdm import tqdm
import fire

from github_client import GitHubClient

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def validate_mappings(mappings: List[Dict]) -> Tuple[Dict[str, Dict], Dict[str, Dict]]:
    """
    Validate issue-PR mappings for a repository.
    
    Parameters
    ----------
    mappings : list of dict
        All PR-issue mappings for a repository
        
    Returns
    -------
    tuple of (issue_map, pr_map)
        issue_map: {issue_number: {'linked': set, 'referenced': set}}
        pr_map: {pr_number: {'linked': set, 'referenced': set}}
    """
    # Build maps
    issue_to_prs = defaultdict(lambda: {'linked': set(), 'referenced': set()})
    pr_to_issues = defaultdict(lambda: {'linked': set(), 'referenced': set()})
    
    for mapping in mappings:
        issue_num = mapping['issue_number']
        pr_num = mapping['pr_number']
        map_type = mapping['type']
        
        if map_type == 'linked':
            issue_to_prs[issue_num]['linked'].add(pr_num)
            pr_to_issues[pr_num]['linked'].add(issue_num)
        elif map_type == 'referenced':
            issue_to_prs[issue_num]['referenced'].add(pr_num)
            pr_to_issues[pr_num]['referenced'].add(issue_num)
    
    return dict(issue_to_prs), dict(pr_to_issues)


def check_issue_ok(issue_map: Dict) -> bool:
    """
    Check if issue has valid mapping.
    
    Rules:
    - Only one unique linked PR (no matter how many referenced PRs) - True
    - Only one unique referenced PR (empty linked PRs) - True
    - else False
    
    Parameters
    ----------
    issue_map : dict
        {'linked': set, 'referenced': set}
        
    Returns
    -------
    bool
        Whether issue mapping is valid
    """
    linked = issue_map['linked']
    referenced = issue_map['referenced']
    
    # Case 1: exactly one linked PR (any number of referenced)
    if len(linked) == 1:
        return True
    
    # Case 2: no linked PRs, exactly one referenced PR
    if len(linked) == 0 and len(referenced) == 1:
        return True
    
    return False


def check_pr_ok(pr_map: Dict) -> bool:
    """
    Check if PR has valid mapping.
    
    Rules:
    - Only one unique linked issue (no matter how many referenced issues) - True
    - Only one unique referenced issue (empty linked issues) - True
    - else False
    
    Parameters
    ----------
    pr_map : dict
        {'linked': set, 'referenced': set}
        
    Returns
    -------
    bool
        Whether PR mapping is valid
    """
    linked = pr_map['linked']
    referenced = pr_map['referenced']
    
    # Case 1: exactly one linked issue (any number of referenced)
    if len(linked) == 1:
        return True
    
    # Case 2: no linked issues, exactly one referenced issue
    if len(linked) == 0 and len(referenced) == 1:
        return True
    
    return False


def fetch_pr_details(client: GitHubClient, owner: str, name: str, pr_number: int) -> Dict[str, Any]:
    """
    Fetch PR details including title, body, and comments.
    
    Parameters
    ----------
    client : GitHubClient
        GitHub API client
    owner : str
        Repository owner
    name : str
        Repository name
    pr_number : int
        PR number
        
    Returns
    -------
    dict
        PR metadata with title, body, comments
    """
    logger.debug(f"Fetching PR #{pr_number} from {owner}/{name}")
    
    variables = {
        "owner": owner,
        "name": name,
        "prNumber": pr_number
    }
    
    result = client.execute_query_from_file("pr_details", variables)
    pr = result['data']['repository']['pullRequest']
    
    # Extract comments
    comments = []
    for edge in pr['comments']['edges']:
        comments.append({
            'author': edge['node']['author']['login'] if edge['node']['author'] else None,
            'body': edge['node']['body'],
            'createdAt': edge['node']['createdAt']
        })
    
    return {
        'title': pr['title'],
        'body': pr['body'],
        'comments': comments
    }


def fetch_issue_details(client: GitHubClient, owner: str, name: str, issue_number: int) -> Dict[str, Any]:
    """
    Fetch issue details including title, body, and comments.
    
    Parameters
    ----------
    client : GitHubClient
        GitHub API client
    owner : str
        Repository owner
    name : str
        Repository name
    issue_number : int
        Issue number
        
    Returns
    -------
    dict
        Issue metadata with title, body, comments
    """
    logger.debug(f"Fetching issue #{issue_number} from {owner}/{name}")
    
    variables = {
        "owner": owner,
        "name": name,
        "issueNumber": issue_number
    }
    
    result = client.execute_query_from_file("issue_details", variables)
    issue = result['data']['repository']['issue']
    
    # Extract comments
    comments = []
    for edge in issue['comments']['edges']:
        comments.append({
            'author': edge['node']['author']['login'] if edge['node']['author'] else None,
            'body': edge['node']['body'],
            'createdAt': edge['node']['createdAt']
        })
    
    return {
        'title': issue['title'],
        'body': issue['body'],
        'comments': comments
    }


def metadata_extraction_and_filtering(
    input_file: str,
    output_file: str,
    github_token: Optional[str] = None,
    checkpoint_file: Optional[str] = None,
    request_delay: float = 0.5
):
    """
    Extract and filter PR-issue metadata.
    
    Parameters
    ----------
    input_file : str
        Path to step2_output.jsonl
    output_file : str
        Path to output JSONL file
    github_token : str, optional
        GitHub API token
    checkpoint_file : str, optional
        Checkpoint file path
    request_delay : float
        Delay between requests in seconds
    """
    logger.info("Starting metadata extraction and filtering")
    
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
    
    # Load mappings from step 2, grouped by repo
    repo_mappings = defaultdict(list)
    with open(input_file, 'r') as f:
        for line in f:
            mapping = json.loads(line)
            repo_name = mapping['repo_name']
            repo_mappings[repo_name].append(mapping)
    
    logger.info(f"Found {len(repo_mappings)} repositories")
    
    # Initialize client
    client = GitHubClient(github_token)
    client.print_limit()
    
    # Open output
    output_mode = 'a' if os.path.exists(output_file) else 'w'
    
    with open(output_file, output_mode) as out_f, \
         open(checkpoint_file, 'a') as chk_f:
        
        for repo_name in tqdm(sorted(repo_mappings.keys()), desc="Processing repos"):
            if repo_name in processed_repos:
                logger.debug(f"Skipping {repo_name} (already processed)")
                continue
            
            mappings = repo_mappings[repo_name]
            
            # Step 1: Validate mappings
            issue_to_prs, pr_to_issues = validate_mappings(mappings)
            
            # Check each mapping
            for mapping in mappings:
                issue_num = mapping['issue_number']
                pr_num = mapping['pr_number']
                
                # Check issue validity
                map_issue_ok = check_issue_ok(issue_to_prs[issue_num])
                
                # Check PR validity
                map_pr_ok = check_pr_ok(pr_to_issues[pr_num])
                
                # Combined validity
                map_issue_pr_ok = map_issue_ok and map_pr_ok
                
                mapping['map_issue_ok'] = map_issue_ok
                mapping['map_pr_ok'] = map_pr_ok
                mapping['map_issue_pr_ok'] = map_issue_pr_ok
            
            # Step 2: Print stats
            num_rows = len(mappings)
            num_issues = len(issue_to_prs)
            num_prs = len(pr_to_issues)
            
            num_rows_issue_ok = sum(1 for m in mappings if m['map_issue_ok'])
            num_rows_pr_ok = sum(1 for m in mappings if m['map_pr_ok'])
            num_rows_issue_pr_ok = sum(1 for m in mappings if m['map_issue_pr_ok'])
            
            num_issues_issue_ok = sum(1 for i in issue_to_prs.values() if check_issue_ok(i))
            num_prs_pr_ok = sum(1 for p in pr_to_issues.values() if check_pr_ok(p))
            
            # Count combined valid issues and PRs
            valid_issues = set()
            valid_prs = set()
            for m in mappings:
                if m['map_issue_pr_ok']:
                    valid_issues.add(m['issue_number'])
                    valid_prs.add(m['pr_number'])
            
            print(f"\n{repo_name} Stats:")
            print(f"  Total:          rows={num_rows:4d}, issues={num_issues:4d}, prs={num_prs:4d}")
            print(f"  map_issue_ok:   rows={num_rows_issue_ok:4d}, issues={num_issues_issue_ok:4d}")
            print(f"  map_pr_ok:      rows={num_rows_pr_ok:4d}, prs={num_prs_pr_ok:4d}")
            print(f"  map_issue_pr_ok: rows={num_rows_issue_pr_ok:4d}, issues={len(valid_issues):4d}, prs={len(valid_prs):4d}")
            
            # Step 3: Fetch details for valid mappings
            owner, name = repo_name.split('/')
            
            # Cache for fetched details to avoid duplicates
            pr_details_cache = {}
            issue_details_cache = {}
            
            for mapping in mappings:
                if not mapping['map_issue_pr_ok']:
                    # Write without additional metadata
                    out_f.write(json.dumps(mapping) + '\n')
                    continue
                
                issue_num = mapping['issue_number']
                pr_num = mapping['pr_number']
                
                try:
                    # Fetch PR details (with caching)
                    if pr_num not in pr_details_cache:
                        pr_details = fetch_pr_details(client, owner, name, pr_num)
                        pr_details_cache[pr_num] = pr_details
                        time.sleep(request_delay)
                    else:
                        pr_details = pr_details_cache[pr_num]
                    
                    # Fetch issue details (with caching)
                    if issue_num not in issue_details_cache:
                        issue_details = fetch_issue_details(client, owner, name, issue_num)
                        issue_details_cache[issue_num] = issue_details
                        time.sleep(request_delay)
                    else:
                        issue_details = issue_details_cache[issue_num]
                    
                    # Add to mapping
                    mapping['pr_title'] = pr_details['title']
                    mapping['pr_body'] = pr_details['body']
                    mapping['pr_comments'] = pr_details['comments']
                    
                    mapping['issue_body'] = issue_details['body']
                    mapping['issue_comments'] = issue_details['comments']
                    # issue_title already exists from step 2
                    
                except Exception as e:
                    logger.warning(f"Failed to fetch details for {repo_name} PR#{pr_num} Issue#{issue_num}: {e}")
                
                # Write enriched mapping
                out_f.write(json.dumps(mapping) + '\n')
            
            # Save checkpoint
            chk_f.write(repo_name + '\n')
            chk_f.flush()
            out_f.flush()
            
            processed_repos.add(repo_name)
            
            if len(processed_repos) % 10 == 0:
                client.print_limit()
    
    logger.info(f"Done! Saved to {output_file}")


if __name__ == "__main__":
   fire.Fire(metadata_extraction_and_filtering)
