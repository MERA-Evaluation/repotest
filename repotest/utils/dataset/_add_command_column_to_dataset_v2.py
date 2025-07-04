import os
import glob
import pickle
import pandas as pd
from repotest.constants import CONDA_ENV_NAME
from subprocess import Popen, TimeoutExpired, PIPE, run
from tqdm import tqdm
from repotest.constants import CONDA_ENV_NAME
# import os
import sys
sys.path.append("/Users/22530318/Documents/Work/realcode/RealCode_eval/")

from realcode_eval.lm_eval.utils import run_tests
from pathlib import Path

TIMEOUT = 60
p = None

def load_build_logs(path = "/Users/22530318/Documents/Work/realcode/logs_build/**"):
    files = glob.glob(path)
    files.sort()

    data = []
    for fn in files:
        data.append(pickle.load(open(fn, "rb")))

    data = pd.DataFrame(data)
    return data

def get_command(lib_name,
                path = "/Users/22530318/Documents/Work/realcode/lm-evaluation-harness/"
               ):
    path_conda = os.path.join(path, lib_name, CONDA_ENV_NAME)
    path_repo = os.path.join(path, lib_name)
    
    command = f"cd {str(path_repo)} && PYTHONPATH=$(pwd) conda run -p {path_conda} pytest tests --color=no -p no:cacheprovider"
    return command

data = load_build_logs()
# data_res = {}
# list_libs = [str(i) for i in data['path_lib_name'].unique()]
# for lib_name in tqdm(list_libs):
#     if lib_name in data_res:
#         continue
    
#     print(lib_name)
#     data_res[lib_name] = {}
#     command = get_command(lib_name)
#     # run(command)
#     try:
#         p = run([command.replace('\n', ' ')], 
#                    shell=True, capture_output=True, check=False,  timeout=TIMEOUT
#                  )
#     except Exception as e:
#         data_res['stderr'] = str(t)
#         continue
    
#     data_res[lib_name]['p'] = p
#     data_res[lib_name]['args'] = p.args
#     data_res[lib_name]['stdout'] = p.stdout
#     data_res[lib_name]['stderr'] = p.stderr
#     data_res[lib_name]['returncode'] = p.returncode
    
#     p_realcode_original = run_tests(bin = Path(f"/Users/22530318/Documents/Work/realcode/lm-evaluation-harness/{lib_name}/{CONDA_ENV_NAME}/"),
#                                     repo = Path(f"/Users/22530318/Documents/Work/realcode/lm-evaluation-harness/{lib_name}/")
#                                    )
#     data_res[lib_name]['realcode_origin'] = p_realcode_original
    
#     print("returncode=", data_res[lib_name]['returncode'])
#     print(p_realcode_original)
#     pickle.dump(data_res, open('data_res.pickle', "wb"))
# # res


assert data['path_lib_name'].apply(lambda x: str(x).count('/') == 2).all()
print("add lib name column")
data['lib_name'] = data['path_lib_name'].apply(lambda x: str(x).split('/')[2])

print("Libs all", data['lib_name'].nunique())
print("Libs with status code == 0", data.loc[(data['returncode'] == 0), 'lib_name'].nunique())


print("data.loc[2]['path_lib_name']", data.loc[2]['path_lib_name'])

# data.loc[2]['cmd']
# /Users/22530318/Documents/Work/realcode/lm-evaluation-harness/data/realcode_v3/pytablericons/{CONDA_ENV_NAME}
print("add columns _fn_venv_bench, _fn_patj")
data['_fn_venv_bench'] = data['path_lib_name'].apply(lambda x:
f'/Users/22530318/Documents/Work/realcode/lm-evaluation-harness/{str(x)}/{CONDA_ENV_NAME}')

data['_fn_path'] = data['path_lib_name'].apply(lambda x:
f'/Users/22530318/Documents/Work/realcode/lm-evaluation-harness/{str(x)}')


print("groupby commands for every repo")
df = data.loc[(data['returncode'] == 0)].groupby('lib_name').\
apply(lambda x: pd.Series({"cmd_not_zero_status": '\n'.join(x['cmd']),
                           "fn_path": x.iloc[0]['_fn_path'],
                           "fn_venv_bench": x.iloc[0]['_fn_venv_bench']
                          }
                         ))

print("Creating cmd command")
def simplify_command(cmd_not_zero_status, fn_path, fn_venv_bench):
    cmd = cmd_not_zero_status
    cmd = cmd.replace(fn_venv_bench, '$path_venv')
    cmd = cmd.replace(fn_path, '$path_lib')
    return cmd

df['cmd'] = [simplify_command(**row.to_dict()) for _, row in df.iterrows()]
dct = df['cmd'].to_dict()

print("Add column command to dataset")
fn_dataset = "/Users/22530318/Documents/git/java-utils/datasets/realcode_v2_no_build.jsonl"
from datasets import load_dataset

dataset = load_dataset("json", data_files=fn_dataset)

dataset_v3 = dataset.map(lambda x: {'command': dct[x['repo']]})
dataset_v3['train'].to_json("/Users/22530318/Documents/git/java-utils/datasets/realcode_v3_no_build.jsonl")