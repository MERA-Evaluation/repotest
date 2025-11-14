"""
Step 1: Repository Collection from S3 + GitHub Details

Collects repositories from S3, filters by language and tests,
fetches full GitHub details for passed repos, and saves in collect_repos.py format.
"""
import json
import os
import logging
import time
from datetime import datetime
from typing import Optional, List, Dict, Any
from tqdm import tqdm
import fire
import boto3
from botocore.exceptions import ClientError

from collect.github_client import GitHubClient

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class S3RepositoryCollector:
    """Collector for repositories stored in S3."""
    
    def __init__(
        self, 
        s3_bucket: str,
        s3_prefix: str,
        aws_profile: Optional[str] = None,
        region_name: str = 'us-east-1'
    ):
        self.s3_bucket = s3_bucket
        self.s3_prefix = s3_prefix.rstrip('/') + '/'
        
        session_kwargs = {'region_name': region_name}
        if aws_profile:
            session_kwargs['profile_name'] = aws_profile
        
        session = boto3.Session(**session_kwargs)
        self.s3_client = session.client('s3')
        
        logger.info(f"Initialized S3 collector: s3://{s3_bucket}/{self.s3_prefix}")
    
    def list_date_folders(self) -> List[str]:
        shards_prefix = self.s3_prefix + 'shards/'
        logger.info(f"Listing date folders from: s3://{self.s3_bucket}/{shards_prefix}")
        
        date_folders = []
        paginator = self.s3_client.get_paginator('list_objects_v2')
        
        try:
            for page in paginator.paginate(Bucket=self.s3_bucket, Prefix=shards_prefix, Delimiter='/'):
                for prefix_info in page.get('CommonPrefixes', []):
                    folder_name = prefix_info['Prefix'].rstrip('/').split('/')[-1]
                    if self._is_valid_date_folder(folder_name):
                        date_folders.append(folder_name)
        except ClientError as e:
            logger.error(f"Error listing S3 folders: {e}")
            raise
        
        date_folders.sort()
        logger.info(f"Found {len(date_folders)} date folders")
        return date_folders
    
    def _is_valid_date_folder(self, folder_name: str) -> bool:
        try:
            datetime.strptime(folder_name, '%Y-%m-%d')
            return True
        except ValueError:
            return False
    
    def list_json_files(self, date_folder: str) -> List[str]:
        folder_prefix = f"{self.s3_prefix}shards/{date_folder}/"
        json_files = []
        paginator = self.s3_client.get_paginator('list_objects_v2')
        
        try:
            for page in paginator.paginate(Bucket=self.s3_bucket, Prefix=folder_prefix):
                for obj in page.get('Contents', []):
                    key = obj['Key']
                    if key.endswith('.json'):
                        json_files.append(key)
        except ClientError as e:
            logger.error(f"Error listing JSON files in {date_folder}: {e}")
            return []
        
        json_files.sort()
        return json_files
    
    def read_json_file(self, s3_key: str) -> List[Dict[str, Any]]:
        try:
            response = self.s3_client.get_object(Bucket=self.s3_bucket, Key=s3_key)
            content = response['Body'].read().decode('utf-8')
            data = json.loads(content)
            return data if isinstance(data, list) else []
        except ClientError as e:
            logger.error(f"Error reading S3 file {s3_key}: {e}")
            return []
        except json.JSONDecodeError as e:
            logger.error(f"Error parsing JSON from {s3_key}: {e}")
            return []


def get_repo_details(client: GitHubClient, owner: str, name: str) -> Dict[str, Any]:
    """Fetch detailed repository information from GitHub."""
    logger.debug(f"Fetching details for {owner}/{name}")
    try:
        variables = {"owner": owner, "name": name}
        result = client.execute_query_from_file("repo_details", variables)
        repo = result["data"]["repository"]
        repo['pullRequestsTotal'] = repo.pop('pullRequests')['totalCount']
        repo['pullRequestsMerged'] = repo.pop('mergedPRs')['totalCount']
        repo['issuesTotal'] = repo.pop('issues')['totalCount']
        repo['issuesClosed'] = repo.pop('closedIssues')['totalCount']
        repo['issuesOpen'] = repo.pop('openIssues')['totalCount']
        
        return repo
    except Exception as e:
        logger.warning(f"Failed to fetch details for {owner}/{name}: {e}")
        return {}


def collect_repos_from_s3(
    output_file: str,
    s3_bucket: str,
    s3_prefix: str,
    language_filter: 'LanguageFilter',
    github_token: Optional[str] = None,
    aws_profile: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    checkpoint_file: Optional[str] = None,
    max_retries: int = 3,
    fetch_detailed_info: bool = True,
    detailed_info_delay: float = 1.0
):
    """
    Collect repos from S3, filter, fetch GitHub details, save in collect_repos.py format.
    """
    logger.info(f"Starting S3 + GitHub detailed collection for {language_filter.language_name}")
    
    if github_token is None:
        github_token = os.environ.get('GITHUB_TOKEN')
        if not github_token:
            raise ValueError("GitHub token required (set GITHUB_TOKEN env var)")
    
    if checkpoint_file is None:
        checkpoint_file = f"{output_file}.checkpoint"
    
    processed_files = set()
    if os.path.exists(checkpoint_file):
        with open(checkpoint_file, 'r') as f:
            processed_files = set(line.strip() for line in f)
        logger.info(f"Loaded {len(processed_files)} processed files from checkpoint")
    
    collector = S3RepositoryCollector(s3_bucket=s3_bucket, s3_prefix=s3_prefix, aws_profile=aws_profile)
    date_folders = collector.list_date_folders()
    
    if start_date:
        date_folders = [d for d in date_folders if d >= start_date]
    if end_date:
        date_folders = [d for d in date_folders if d <= end_date]
    
    logger.info(f"Processing {len(date_folders)} date folders")
    
    gh_client = GitHubClient(github_token)
    gh_client.print_limit()
    
    stats = {
        'total_repos': 0,
        'filtered_repos': 0,
        'language_mismatch': 0,
        'no_tests': 0,
        'files_processed': 0,
        'folders_processed': 0,
        'details_fetched': 0,
        'details_failed': 0
    }
    
    output_mode = 'a' if os.path.exists(output_file) else 'w'
    
    with open(output_file, output_mode) as out_f, \
         open(checkpoint_file, 'a') as chk_f:
        
        for date_folder in tqdm(date_folders, desc="Date folders"):
            json_files = collector.list_json_files(date_folder)
            logger.info(f"{date_folder}: {len(json_files)} JSON files")
            
            for json_file_key in tqdm(json_files, desc=f"  Files in {date_folder}", leave=False):
                if json_file_key in processed_files:
                    continue
                
                retries = 0
                success = False
                
                while retries < max_retries and not success:
                    try:
                        repos = collector.read_json_file(json_file_key)
                        stats['files_processed'] += 1
                        
                        for repo in repos:
                            stats['total_repos'] += 1

                            if not language_filter.matches_language(repo):
                                stats['language_mismatch'] += 1
                                continue
                            
                            if not language_filter.has_runnable_tests(repo):
                                stats['no_tests'] += 1
                                continue
                            
                            name_with_owner = repo.get('nameWithOwner') or repo.get('full_name')
                            if not name_with_owner or '/' not in name_with_owner:
                                continue
                            owner, name = name_with_owner.split('/', 1)

                            base_repo = {
                                "nameWithOwner": name_with_owner,
                                "owner": {"login": owner},
                                "name": name,
                                "description": repo.get("description"),
                                "stargazerCount": repo.get("stargazers", 0),
                                "forkCount": repo.get("forks", 0),
                                "createdAt": repo.get("created_at") or repo.get("createdAt"),
                                "pushedAt": repo.get("pushed_at") or repo.get("pushedAt"),
                                "url": repo.get("html_url") or f"https://github.com/{name_with_owner}",
                                "primaryLanguage": repo.get("language") or repo.get("primaryLanguage"),
                                "isFork": repo.get("fork", False),
                                "licenseInfo": repo.get("license"),
                                "diskUsage": repo.get("size", 0)
                            }

                            detailed_repo = base_repo.copy()
                            if fetch_detailed_info:
                                detailed = get_repo_details(gh_client, owner, name)
                                if detailed:
                                    detailed_repo.update(detailed)
                                    stats['details_fetched'] += 1
                                else:
                                    stats['details_failed'] += 1
                                time.sleep(detailed_info_delay)
                            else:
                                detailed_repo.update({
                                    "pullRequestsTotal": repo.get("open_pull_requests", 0) + repo.get("closed_pull_requests", 0),
                                    "issuesTotal": repo.get("open_issues", 0) + repo.get("closed_issues", 0),
                                    "issuesOpen": repo.get("open_issues", 0),
                                    "issuesClosed": repo.get("closed_issues", 0),
                                })
                            
                            period = f"{date_folder}:{date_folder}"
                            detailed_repo['_period'] = period
                            detailed_repo['_search_params'] = {
                                'language': language_filter.language_name,
                                'stars_min': 0,
                                'stars_max': None,
                                'forks_min': 0,
                                'forks_max': None,
                                'date_range': period
                            }
                            detailed_repo['_source'] = 's3'
                            detailed_repo['_s3_key'] = json_file_key
                            detailed_repo['_date_folder'] = date_folder
                            detailed_repo['_language_filter'] = language_filter.language_name
                            out_f.write(json.dumps(detailed_repo, ensure_ascii=False) + '\n')
                            stats['filtered_repos'] += 1
                        chk_f.write(json_file_key + '\n')
                        chk_f.flush()
                        out_f.flush()
                        processed_files.add(json_file_key)
                        success = True
                        
                    except Exception as e:
                        retries += 1
                        logger.error(f"Error processing {json_file_key} (attempt {retries}): {e}")
                        if retries >= max_retries:
                            logger.error(f"Skipping {json_file_key} after {max_retries} retries")
                        else:
                            time.sleep(2 ** retries)
                
                stats['folders_processed'] += 1 if success else 0
            
            logger.info(
                f"Progress: {stats['folders_processed']}/{len(date_folders)} folders, "
                f"{stats['filtered_repos']}/{stats['total_repos']} passed, "
                f"details: {stats['details_fetched']} fetched, {stats['details_failed']} failed"
            )
            gh_client.print_limit()
    
    logger.info("=" * 80)
    logger.info("S3 collect сomplete!")
    logger.info(f"Total repos scanned: {stats['total_repos']}")
    logger.info(f"Passed filters: {stats['filtered_repos']}")
    logger.info(f"  Language mismatch: {stats['language_mismatch']}")
    logger.info(f"  No tests: {stats['no_tests']}")
    logger.info(f"Details fetched: {stats['details_fetched']}, failed: {stats['details_failed']}")
    logger.info(f"Files processed: {stats['files_processed']}")
    logger.info(f"Output: {output_file}")
    logger.info("=" * 80)


def collect_golang_repos_from_s3(
    output_file: str,
    s3_bucket: str = "test",
    s3_prefix: str = "test/test",
    aws_profile: Optional[str] = "maintainer",
    github_token: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    checkpoint_file: Optional[str] = None,
    max_retries: int = 3,
    fetch_detailed_info: bool = True,
    detailed_info_delay: float = 1.0
):
    """Convenience function for Go repos."""
    from collect.lang.s3_golang import GoFilter
    language_filter = GoFilter()
    
    collect_repos_from_s3(
        output_file=output_file,
        s3_bucket=s3_bucket,
        s3_prefix=s3_prefix,
        language_filter=language_filter,
        github_token=github_token,
        aws_profile=aws_profile,
        start_date=start_date,
        end_date=end_date,
        checkpoint_file=checkpoint_file,
        max_retries=max_retries,
        fetch_detailed_info=fetch_detailed_info,
        detailed_info_delay=detailed_info_delay
    )


if __name__ == "__main__":
    fire.Fire({
        'golang': collect_golang_repos_from_s3,
        'custom': collect_repos_from_s3
    })