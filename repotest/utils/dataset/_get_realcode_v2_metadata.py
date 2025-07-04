import os
import re

#path to realcode data
path = '/Users/22530318/Documents/Work/realcode/lm-evaluation-harness/data/realcode_v3'
repo_list = os.listdir(path)

patern_url = r"(?<=url\s=\s)(https?://[^\s]+)"

data = []

# Parse git structure using only .git folder level
# .git folder at data was not changed after parsing
for repo in repo_list:
    folder = f"{path}/{repo}"
    if not os.path.isdir(folder):
        continue
    branch = open(f"{folder}/.git/HEAD", "r").read()
    branch_name = branch.split('\n')[0].split('/')[-1]
    base_commit = open(f"{folder}/.git/refs/heads/{branch_name}", "r").read()
    
    config_content = open(f"{folder}/.git/config", "r").read()
    urls = re.findall(patern_url, config_content)
    assert len(urls) == 1
    url = urls[0]
    data.append({"repo": repo,
                 "branch": branch_name,
                 "base_commit": base_commit,
                 "_url": url
                })
    

from datasets import Dataset
dataset = Dataset.from_list(data)
dataset.to_json("/Users/22530318/Documents/git/java-utils/datasets/realcode_v2_no_build.jsonl")