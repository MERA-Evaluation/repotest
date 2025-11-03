#github_client.py
"""
Shared GitHub GraphQL API client for all pipeline steps.
"""
import json
import os
import logging
import requests
from pathlib import Path
from typing import Optional, Dict, Any

logger = logging.getLogger("GitHubClient")


class GitHubClient:
    """GitHub GraphQL API client with query file support."""
    
    def __init__(self, token: str):
        self.token = token
        self.api_url = "https://api.github.com/graphql"
        self.headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        }
        self.queries_dir = Path(__file__).parent / "gql"
        logger.info(f"Initialized GitHubClient with queries dir: {self.queries_dir}")
    
    def load_query(self, query_name: str) -> str:
        """Load GraphQL query from .gql file."""
        query_file = self.queries_dir / f"{query_name}.gql"
        logger.debug(f"Loading query from {query_file}")
        
        if not query_file.exists():
            logger.error(f"Query file not found: {query_file}")
            raise FileNotFoundError(f"Query file not found: {query_file}")
        
        with open(query_file, 'r') as f:
            query = f.read().strip()
        
        logger.debug(f"Loaded query {query_name}: {len(query)} chars")
        return query
    
    def execute_query(self, query: str, variables: Dict[str, Any]) -> Dict[str, Any]:
        """Execute GraphQL query."""
        payload = {
            "query": query,
            "variables": variables
        }
        
        logger.debug(f"Executing query with variables: {json.dumps(variables, indent=2)}")
        
        response = requests.post(
            self.api_url,
            headers=self.headers,
            json=payload,
            timeout=60
        )
        
        logger.debug(f"Response status: {response.status_code}")
        response.raise_for_status()
        
        data = response.json()
        
        if "errors" in data:
            logger.error(f"GraphQL errors: {json.dumps(data['errors'], indent=2)}")
            raise ValueError(f"GraphQL errors: {data['errors']}")
        
        logger.debug("Query executed successfully")
        return data
    
    def execute_query_from_file(self, query_name: str, variables: Dict[str, Any]) -> Dict[str, Any]:
        """Load and execute query from .gql file."""
        logger.info(f"Executing query from file: {query_name}")
        query = self.load_query(query_name)
        return self.execute_query(query, variables)
    
    def get_rate_limit(self) -> Dict[str, Any]:
        """Get current rate limit status."""
        logger.debug("Fetching rate limit info")
        query = """
        query {
          rateLimit {
            limit
            remaining
            resetAt
          }
        }
        """
        result = self.execute_query(query, {})
        rate_limit = result["data"]["rateLimit"]
        logger.info(f"Rate limit: {rate_limit['remaining']}/{rate_limit['limit']}, resets at {rate_limit['resetAt']}")
        return rate_limit
    
    def print_limit(self):
        """Print current rate limit."""
        limit_info = self.get_rate_limit()
        print(f"Rate limit: {limit_info['remaining']}/{limit_info['limit']}, resets at {limit_info['resetAt']}")
