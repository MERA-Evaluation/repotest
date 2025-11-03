# collect_repos.py
"""
Step 1: Repository Selection

Searches GitHub for repositories matching specified criteria and extracts metadata.
"""
import json
import os
import time
import logging
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any
from tqdm import tqdm
import fire

from github_client import GitHubClient

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def timedelta_iterator(start_date: str, end_date: str, days: int):
    """Generate dates between start_date and end_date with specified intervals."""
    start = datetime.strptime(start_date, "%Y-%m-%d")
    end = datetime.strptime(end_date, "%Y-%m-%d")
    
    assert start <= end, "start_date must be <= end_date"
    
    current = start
    while current <= end:
        yield current.strftime("%Y-%m-%d")
        current += timedelta(days=days)


def interval_iterator(start_date: str, end_date: str, days: int):
    """Generate date intervals (tuples of consecutive dates)."""
    left_iter = timedelta_iterator(start_date, end_date, days)
    right_iter = timedelta_iterator(start_date, end_date, days)
    next(right_iter)
    
    while True:
        try:
            yield (next(left_iter), next(right_iter))
        except StopIteration:
            break


def search_repositories(
    client: GitHubClient,
    language: str,
    min_date: str,
    max_date: str,
    min_stars: int = 0,
    max_stars: Optional[int] = None,
    min_forks: int = 0,
    max_forks: Optional[int] = None,
    pushed_year: Optional[int] = None,
    license_list: Optional[List[str]] = None,
    max_results: int = 100
) -> Dict[str, Any]:
    """
    Search repositories with filters.
    
    Parameters
    ----------
    client : GitHubClient
        GitHub API client
    language : str
        Programming language
    min_date : str
        Minimum creation date (YYYY-MM-DD)
    max_date : str
        Maximum creation date (YYYY-MM-DD)
    min_stars : int
        Minimum stars
    max_stars : int, optional
        Maximum stars
    min_forks : int
        Minimum forks
    max_forks : int, optional
        Maximum forks
    pushed_year : int, optional
        Year of last push
    license_list : list of str, optional
        List of licenses
    max_results : int
        Maximum results to return
        
    Returns
    -------
    dict
        Search results with repositoryCount and nodes
    """
    logger.info(f"Searching repos: {language}, {min_date} to {max_date}, stars {min_stars}-{max_stars}, forks {min_forks}-{max_forks}")
    
    # Build search query string
    query_parts = [f"language:{language}"]
    
    # Stars filter
    if max_stars is not None:
        query_parts.append(f"stars:{min_stars}..{max_stars}")
    else:
        query_parts.append(f"stars:>={min_stars}")
    
    # Forks filter
    if max_forks is not None:
        query_parts.append(f"forks:{min_forks}..{max_forks}")
    else:
        query_parts.append(f"forks:>={min_forks}")
    
    query_parts.append(f"created:{min_date}..{max_date}")
    
    if pushed_year:
        query_parts.append(f"pushed:>={pushed_year}-01-01")
    
    if license_list:
        license_query = " OR ".join([f"license:{lic}" for lic in license_list])
        query_parts.append(f"({license_query})")
    
    search_query = " ".join(query_parts)
    logger.debug(f"Search query string: {search_query}")
    
    variables = {
        "searchQuery": search_query,
        "maxResults": min(max_results, 100)
    }
    
    result = client.execute_query_from_file("search_repos", variables)
    
    # Extract nodes
    search_data = result["data"]["search"]
    nodes = [edge["node"] for edge in search_data.get("edges", [])]
    
    logger.info(f"Found {search_data['repositoryCount']} total repos, fetched {len(nodes)}")
    
    return {
        "repositoryCount": search_data["repositoryCount"],
        "nodes": nodes
    }


def get_repo_details(client: GitHubClient, owner: str, name: str) -> Dict[str, Any]:
    """
    Get detailed repository information.
    
    Parameters
    ----------
    client : GitHubClient
        GitHub API client
    owner : str
        Repository owner
    name : str
        Repository name
        
    Returns
    -------
    dict
        Detailed repository metadata
    """
    logger.debug(f"Fetching details for {owner}/{name}")
    
    variables = {"owner": owner, "name": name}
    result = client.execute_query_from_file("repo_details", variables)
    
    repo = result["data"]["repository"]
    
    # Flatten counts
    repo['pullRequestsTotal'] = repo.pop('pullRequests')['totalCount']
    repo['pullRequestsMerged'] = repo.pop('mergedPRs')['totalCount']
    repo['issuesTotal'] = repo.pop('issues')['totalCount']
    repo['issuesClosed'] = repo.pop('closedIssues')['totalCount']
    repo['issuesOpen'] = repo.pop('openIssues')['totalCount']
    
    logger.debug(f"Fetched details for {owner}/{name}: {repo['pullRequestsTotal']} PRs, {repo['issuesTotal']} issues")
    
    return repo


def collect_repos(
    output_file: str,
    language: str = "python",
    start_date: str = "2020-01-01",
    end_date: str = "2024-12-31",
    window_days: int = 7,
    stars_min: int = 0,
    stars_max: Optional[int] = None,
    forks_min: int = 0,
    forks_max: Optional[int] = None,
    pushed_year: Optional[int] = None,
    license_list: Optional[str] = None,
    github_token: Optional[str] = None,
    checkpoint_file: Optional[str] = None,
    max_retries: int = 5,
    max_results_per_window: int = 100,
    fetch_detailed_info: bool = False,
    detailed_info_delay: float = 1.0
):
    """
    Search GitHub repositories and save results to JSONL file.
    
    Parameters
    ----------
    output_file : str
        Path to output JSONL file
    language : str
        Programming language filter
    start_date : str
        Start date (YYYY-MM-DD)
    end_date : str
        End date (YYYY-MM-DD)
    window_days : int
        Size of date windows in days
    stars_min : int
        Minimum stars
    stars_max : int, optional
        Maximum stars
    forks_min : int
        Minimum forks
    forks_max : int, optional
        Maximum forks
    pushed_year : int, optional
        Filter by push year
    license_list : str, optional
        Comma-separated list of licenses
    github_token : str, optional
        GitHub API token
    checkpoint_file : str, optional
        Checkpoint file path
    max_retries : int
        Maximum consecutive failures
    max_results_per_window : int
        Maximum results per time window
    fetch_detailed_info : bool
        Fetch detailed repo info for each repository
    detailed_info_delay : float
        Delay in seconds between detailed info requests
    """
    logger.info("Starting repository collection")
    
    if github_token is None:
        github_token = os.environ.get('GITHUB_TOKEN')
        if not github_token:
            raise ValueError("GitHub token required")
    
    if checkpoint_file is None:
        checkpoint_file = f"{output_file}.checkpoint"
    
    # Parse license list
    licenses = None
    if license_list:
        licenses = [lic.strip() for lic in license_list.split(",")]
    
    # Load checkpoint
    processed_periods = set()
    if os.path.exists(checkpoint_file):
        with open(checkpoint_file, 'r') as f:
            processed_periods = set(line.strip() for line in f)
        logger.info(f"Loaded {len(processed_periods)} processed periods from checkpoint")
    
    # Initialize client
    client = GitHubClient(github_token)
    client.print_limit()
    
    # Calculate total intervals
    total_intervals = sum(1 for _ in interval_iterator(start_date, end_date, window_days))
    logger.info(f"Total intervals to process: {total_intervals}")
    
    # Open output
    output_mode = 'a' if os.path.exists(output_file) else 'w'
    consecutive_failures = 0
    
    with open(output_file, output_mode) as out_f, \
         open(checkpoint_file, 'a') as chk_f:
        
        for left, right in tqdm(
            interval_iterator(start_date, end_date, window_days),
            total=total_intervals,
            desc="Searching repos"
        ):
            period = f"{left}:{right}"
            
            if period in processed_periods:
                logger.debug(f"Skipping period {period} (already processed)")
                continue
            
            try:
                # Step 1: Lightweight search
                result = search_repositories(
                    client=client,
                    language=language,
                    min_date=left,
                    max_date=right,
                    min_stars=stars_min,
                    max_stars=stars_max,
                    min_forks=forks_min,
                    max_forks=forks_max,
                    pushed_year=pushed_year,
                    license_list=licenses,
                    max_results=max_results_per_window
                )
                
                repo_count = result['repositoryCount']
                nodes = result['nodes']
                print(f"{period}: {repo_count} repos, fetched {len(nodes)}")
                
                # Step 2: Fetch detailed info if requested
                if fetch_detailed_info:
                    logger.info(f"Fetching detailed info for {len(nodes)} repos")
                    for i, repo in enumerate(nodes):
                        try:
                            owner = repo['owner']['login']
                            name = repo['name']
                            detailed = get_repo_details(client, owner, name)
                            repo.update(detailed)
                            
                            if (i + 1) % 10 == 0:
                                print(f"  Fetched {i + 1}/{len(nodes)}")
                            
                            time.sleep(detailed_info_delay)
                        except Exception as e:
                            logger.warning(f"Failed to fetch details for {repo['nameWithOwner']}: {e}")
                
                # Step 3: Write results
                for repo in nodes:
                    repo['_period'] = period
                    repo['_search_params'] = {
                        'language': language,
                        'stars_min': stars_min,
                        'stars_max': stars_max,
                        'forks_min': forks_min,
                        'forks_max': forks_max,
                        'date_range': period
                    }
                    out_f.write(json.dumps(repo) + '\n')
                
                chk_f.write(period + '\n')
                chk_f.flush()
                out_f.flush()
                
                processed_periods.add(period)
                consecutive_failures = 0
                
                client.print_limit()
                time.sleep(1)
                
            except Exception as e:
                consecutive_failures += 1
                logger.error(f"Failed {period}: {e}")
                
                if consecutive_failures >= max_retries:
                    raise
                
                time.sleep(5)
    
    logger.info(f"Done! Saved to {output_file}")


if __name__ == "__main__":
    fire.Fire(collect_repos)
