# Test 139 samples from old realcode that they have simmilar @pass
# from repotest.utils.clean import clean_all
# clean_all()
raise NotImplementedError("change columns to be  ['gt', 'return_pass', 'return_empty_str', 'gen']" + \
"output to be pass_{key}")
from repotest.manager.realcode_python_task_manager import TaskManagerRealcode
import json
task_list = json.load(open("task_list.json", "r"))

# task_list = task_list[:10]
manager = TaskManagerRealcode(mode = 'local', n_jobs = 10, n_jobs_build=10)
manager.inplace_build_and_eval(task_list)

import pandas as pd

df_res = pd.DataFrame([{**task.get("passed_dict", {}), 
               **{k:v for k, v in task.items() if k.startswith("old_") or k=='status'}} for task in task_list
             ]
            )
try:
    print("Good", (df_res['old_pass@1']==df_res['pass_gen']).mean())
except:
    print("FULL FAIL")

print(df_res)
assert((df_res['old_pass@1']==df_res['pass_gen']).all())