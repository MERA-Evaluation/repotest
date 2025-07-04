import fire
from repotest.manager.liveswebench_task_manager import LiveSWEBenchTaskManager
import pandas as pd
import json

def main_cli_entry_point(fn_input, 
                         fn_output, 
                         column_patch,
                         mode: str = 'docker',
                         n_jobs: int = 1,
                         raise_exception: bool = True,
                         verbose_all: bool = False,
                         time_scale_factor: str = 'auto'
                        ):
    # Load task list from JSONL
    # ToDo: change this to use hg dataset
    # It will cause proplem with types for PASS_TO_PASS, FAIL_TO_PASS
    task_list = list(pd.read_json(fn_input, lines=True).T.to_dict().values())
    
    # Instantiate the manager with explicit args
    manager = LiveSWEBenchTaskManager(
        column_patch=column_patch,
        mode=mode,
        n_jobs=n_jobs,
        raise_exception=raise_exception,
        verbose_all=verbose_all,
        time_scale_factor=time_scale_factor
    )

    manager.inplace_build_and_eval(task_list)
    n = len(task_list)
    n_critical_fail = sum(['solved' not in task for task in task_list])
    n_solved = sum([task.get('solved', 0) for task in task_list])

    print("Critical fail: %2.2f %d/%d"%(n_critical_fail/n, n_critical_fail, n))
    print("Solved:        %2.2f %d/%d"%(n_solved/n, n_solved, n))

    # Save result
    with open(fn_output, "w") as f:
        for task in task_list:
            task['PASS_TO_PASS'] = json.dumps(list(task['PASS_TO_PASS']))
            task['FAIL_TO_PASS'] = json.dumps(list(task['FAIL_TO_PASS']))
            task['created_at'] = str(task['created_at'])
            f.write(json.dumps(task) + "\n")
    print("results saved at %s"%fn_output)

def main_fire_entry_point():
    fire.Fire(main_cli_entry_point)

if __name__ == "__main__":
    main_fire_entry_point()


