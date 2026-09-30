# Demo projects

Everything needed to try Baobab HPC end to end, and to check that a new install works.

```
examples\
├── demo_data\            synthetic dataset (1.4 MB)
│   ├── session_01.csv … session_04.csv   20 cells, 30 Hz, 60 s of fluorescence
│   ├── stimulus_onsets.csv               stimulus times (s)
│   └── info.json                         description of the data
├── matlab_demo\          MATLAB project (no toolbox needed)
│   ├── demo_matlab.m     entry script (a function)
│   └── utils\            helper functions, found through the MATLAB path
├── python_demo\          Python project
│   ├── demo_python.py    entry script
│   ├── requirements.txt  numpy, matplotlib - installed on Baobab the first time
│   └── utils\            helper package, imported by the script
└── make_demo_data.py     regenerates demo_data (same seed, same files)
```

Both demos do the same analysis: dF/F, event detection, event rates and stimulus-triggered responses. For each session they write `<session>_summary.csv` and `<session>_overview.png`. Cells 1–8 were built to respond to the stimulus, so a correct run reports about 8 responsive cells per session.

## Try it

In the app, on the **New job** page:

| | MATLAB demo | Python demo |
|---|---|---|
| Project folder | `examples\matlab_demo` | `examples\python_demo` |
| Script to run | `demo_matlab.m` | `demo_python.py` |
| Data folder | `examples\demo_data` | `examples\demo_data` |
| Where to run | `debug-cpu` | `debug-cpu` |
| Resources | 1 CPU, 3 GB, `00:10:00` | 1 CPU, 3 GB, `00:10:00` |

The results arrive in `examples\demo_data\results\<job name>_<job id>\`. Git ignores that folder.

**Job array.** Tick **Job array** with range `1-4`: each task analyses one session. MATLAB calls `demo_matlab(task_id)`, and Python receives the task number as `sys.argv[1]`. Both use the shorter `debug-cpu` or `shared-cpu`.

**First Python run.** It takes a few extra minutes while numpy and matplotlib are installed on Baobab. Later runs reuse that environment.

**Automatic continuation.** Both demos save a checkpoint after each session: the list of sessions already done. When Baobab warns that the time limit is close, they stop and exit with code 3. To watch it work, set `SECONDS_PER_SESSION = 120` near the top of `demo_python.py`, or in `demo_matlab.m`, so that each session takes 2 minutes. Then submit on `debug-cpu` with a wall time of `00:05:00` and **Continue automatically** ticked. Two sessions fit in each run before the warning (1 minute before the end), so the job needs two runs: each run's log shows the warning, the queued next run, and the sessions skipped because they were already done. The Jobs page follows along ("run 2 of at most 10"), and the results are downloaded once, after the last run.

**Resource suggestions.** After a demo job ends, the Jobs page shows what it really used, and the New job page offers those settings for the next run of the same script.

## Run locally

Both scripts also run on your own computer, reading `..\demo_data` and writing `.\results`:

```
cd examples\python_demo
python demo_python.py          (all sessions)
python demo_python.py 3        (session 3 only, like array task 3)
```

In MATLAB: `cd examples\matlab_demo`, then `demo_matlab` or `demo_matlab(3)`.
