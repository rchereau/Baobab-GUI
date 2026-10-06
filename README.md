# Baobab HPC — setup and user guide

> **Not an official UNIGE tool.** Baobab HPC is an independent project and is not developed, endorsed or supported by the University of Geneva or its HPC team. For questions about the cluster itself, see the [official documentation](https://doc.eresearch.unige.ch/hpc/start); for questions about this app, open an issue in this repository.

A Windows desktop app to run MATLAB and Python jobs on the UNIGE **Baobab** cluster. You choose your code, your data and the resources; the app copies everything to the cluster, submits the job, follows it, and brings the results back next to your data. Every transferred file is verified with a SHA-256 checksum.

---

## What you need

- **A UNIGE HPC account.** Request it at <https://dw.unige.ch/openentry.html?tid=hpc>. You'll receive an email once it's active.
- **Windows 10 or 11.** The built-in SSH tools are used.
- **This folder:**

```
Baobab GUI\
├── Baobab_Launcher.bat   ← double-click this
├── find_python.ps1       finds Python on your PC (used by the launcher)
├── make_shortcut.ps1     creates the "Baobab HPC" shortcuts (used by the launcher)
├── baobab.ico / .png     the app icon
├── baobab_app.py         the window
├── baobab_core.py        transfers, checksums, SLURM
├── baobab_nas.py         NAS copies, run on Baobab by the staging and upload jobs
├── requirements.txt
├── README.md
├── LICENSE               MIT licence
└── examples\           demo dataset + MATLAB and Python demo projects
```

**From home or abroad, connect to the UNIGE VPN first.** The official documentation says Baobab is reachable from outside UNIGE, but connections from home, especially outside Switzerland, can be refused before login. The symptom is `Connection closed by … port 22`.

---

## Step 1 — First launch

Double-click **`Baobab_Launcher.bat`**. The first time, it:

1. Looks for Python 3.9 or newer: registered installs (python.org, Anaconda, Miniconda), the PATH, conda environments and the usual folders. If none is found, it lists what it saw and lets you drag `python.exe` into the window. If Python is really missing, it installs Python with `winget`, or opens python.org. After a Python install, **close the window and double-click the launcher again**.
2. Creates a private Python environment in a `.venv` subfolder and installs PySide6 and Paramiko. This takes a few minutes and happens only once.
3. Checks for an SSH key. If there is none, it offers to create one (see Step 2).
4. Creates a **Baobab HPC** shortcut with the app's icon on your desktop, in the Start menu (type "Baobab" to find it), and in the app folder. A `.bat` file can't carry an icon of its own, hence the shortcut.
5. Opens the app.

From then on, open the app with the shortcut. It runs the same launcher, which now goes straight to the window.

---

## Step 2 — Create and register your SSH key

Baobab **only accepts SSH-key logins**.

> ⚠️ **Using Baobab from several computers?** my-account.unige.ch stores **one key only**: registering a new key replaces the old one, and your other computer loses access. On your second computer, **don't create a new key**. Copy `id_rsa` and `id_rsa.pub` from the first computer's `C:\Users\<you>\.ssh\` folder, via a USB stick for example, into the same folder on the new one. Then answer **N** when the launcher offers to create a key.

On your first computer:

### Option A — let the launcher do it

When asked *"Generate an SSH key now [Y,N]?"*, press **Y**.

1. For the passphrase, press **Enter twice** for none, or choose one. The app then asks for it at each start.
2. Your **public** key is copied to the clipboard and the UNIGE account page opens.
3. Under **"My SSH public key"**, paste with Ctrl+V and save.
4. **Wait 10–15 minutes** for the key to reach the cluster.

### Option B — by hand

In **cmd** or **PowerShell**:

```bat
ssh-keygen -t rsa -b 4096
type %USERPROFILE%\.ssh\id_rsa.pub | clip
```

Then paste at <https://my-account.unige.ch> → **"My SSH public key"**, save, and wait 10–15 minutes.

> ⚠️ **Only ever share the `.pub` file.** `id_rsa` (without `.pub`) is your private key and must stay on your computer. If you create a new key, upload its `.pub` again; the old one stops working.

---

## Step 3 — Test the connection once in a terminal

This confirms the key works and records the cluster's identity:

```bat
ssh <your_isis_username>@login1.baobab.hpc.unige.ch
```

- The first time, you're asked to confirm the server fingerprint. The official one is `SHA256:tKqp4nljL+EGVKl8T0VF2nS36DkHVFMpLxQOPg/gKvg`. If it matches, type `yes`.
- A prompt like `(baobab)-[username@login1 ~]$` means it works. Type `exit` to leave.

**The app checks the server's identity too.** It has Baobab's fingerprints built in: the RSA one above, from the official documentation, and the ED25519 one. If the server ever presents a different identity, the app refuses to connect and shows a security warning. This protects you against someone impersonating the cluster, for example on a public Wi-Fi. For any other server, the app shows its fingerprint and asks you to confirm it once.

> Three failed logins in a row ban you for 15 minutes. If the key is refused, wait for the sync instead of retrying.

---

## Step 4 — Connect in the app

On the **Settings** page:

| Field | Value |
|---|---|
| ISIS username | your UNIGE login, e.g. `jdoe` |
| Email | your UNIGE address, for end-of-job emails |
| Cluster | `login1.baobab.hpc.unige.ch` (prefilled) |
| SSH key | `C:\Users\<you>\.ssh\id_rsa` (prefilled if found) |

Click **Connect**. The status line turns green and shows your scratch folder. The MATLAB and Python version lists are then read from Baobab; pick the versions you want. For Python, the app finds the extra modules each version needs (e.g. `GCCcore/...`) and shows the exact `module load` line.

You enter this only once: from then on, the app connects by itself at start-up.

---

## Step 5 — Submit a job

On the **New job** page, five cards:

1. **Code.** Choose your **project folder**, the folder with your scripts and helper functions. Then choose the **script to run** in the list. The whole folder is uploaded with its subfolders; `.git`, `__pycache__`, `.asv` backups and the `results` folder are left out.
2. **Data and results.** Optionally choose a **data folder** anywhere on your disk. Results go by default to `<data folder>\results\<jobname>_<jobid>\`, or to `<project folder>\results\...` without data. Use **Choose folder…** to send them elsewhere.
3. **Where to run.** Each partition your account can use is shown as a tile with its time limit, its free cores and idle nodes, free GPUs by type, and how many jobs are waiting. The badge tells you whether **your** request, with the resources below, **can start now**, **will queue**, or is **not possible** there (with the reason). Click anywhere on a tile to choose it. Private partitions of your group, if any, are behind **Show private partitions**.
4. **Resources.** The partition you picked sets the limits: the CPU and memory fields stop at its largest node, and a wall time over its maximum is brought down to it. Your own values come back if you then pick a partition that allows them.
   - **CPUs:** the help line tells you what helps for MATLAB or Python. Plain Python uses one core; MATLAB often benefits from 4–8.
   - **Memory** is the **total** for the job. It follows the CPUs (3 GB each, the cluster default) until you set it yourself. The help line estimates a sensible amount from your largest data file.
   - **After a run**, the app reads from SLURM what the job really used: peak memory, how busy its CPUs were, and how long it ran. The next time you pick the same script, it proposes matching settings with a margin; click **Use these settings**. A job that ran out of memory or time gets that limit doubled.
   - **Estimate start time** asks SLURM when this exact request would start, without submitting anything. Its estimates are cautious.
   - Tick **Job array** to run the script many times.
   - **Time limit:** tick **Continue automatically** if your script saves checkpoints: when a run reaches its time limit, Baobab starts the next one from the last checkpoint, until the work is done. See *Checkpoints and automatic continuation* below.
5. **Submit.** **Preview script…** shows the exact SLURM script. **Upload and submit** starts the transfers, with a progress bar and a log. A request that can't run on the chosen partition is refused before anything is uploaded.

Then follow the job on the **Jobs** page. When it ends, successfully or not, the results and logs are **downloaded automatically and verified**. If you close the app while a job runs, the download happens the next time you open it.

### A first test

The `examples` folder has a demo dataset and a MATLAB and a Python project that analyse it. Choose `examples\matlab_demo` or `examples\python_demo` as the project, `examples\demo_data` as the data folder and `debug-cpu` as the partition, then submit. A few minutes later, a summary table and a figure per session appear in `examples\demo_data\results\`. See `examples\README.md` for details, including a job-array version.

---

## How to write scripts for the cluster

Your code runs from its job folder on Baobab:

```
~/scratch/baobab_jobs/<jobname>_<date-time>/
├── code/        your project folder
├── data/        your dataset (./data/)
├── results/     ← write your outputs here (./results/)
├── checkpoints/ ← save your checkpoints here (BAOBAB_CHECKPOINT_DIR), kept between runs
├── logs/        output and error messages, one file per run
└── submit.sh    the SLURM script that ran
```

- **Read from `./data/` and write to `./results/`.** These folders are also available as the environment variables `BAOBAB_DATA` and `BAOBAB_RESULTS`, e.g. `getenv('BAOBAB_RESULTS')` in MATLAB.
- **MATLAB.** All subfolders of the project are on the path. MATLAB runs with `-batch`, so an error in your code marks the job as FAILED and the message appears in the log. The number of MATLAB threads matches the CPUs you requested.
- **Python.** The project folder is on `PYTHONPATH`, so your own modules import normally. Put a `requirements.txt` in the project folder to get extra packages: they're installed on Baobab the first time and reused afterwards.
- **Job arrays.** A MATLAB *function* receives the task number as its first argument, e.g. `function analyse_session(task_id)`. In a MATLAB *script*, use `str2double(getenv('SLURM_ARRAY_TASK_ID'))`. A Python script receives it as `sys.argv[1]`. All tasks share `./results/`, so include the task number in your file names.
- **MEX files.** Windows `.mexw64` files don't run on Baobab. Recompile them once on the cluster to get `.mexa64` files and keep those in your project:

```bash
salloc -n1 -c2 --partition=debug-cpu --time=15:00
module load MATLAB/2022a
matlab -nodisplay -r "cd ~/mex_src; mex my_function.c; exit"
```

---

## Checkpoints and automatic continuation

It is hard to know in advance how long a job will take. Asking for much more time than needed makes the job wait longer before it starts: SLURM plans as if the whole requested time will be used, and short requests fit into more gaps. Asking for too little gets the job killed at the limit (`TIMEOUT`). Checkpoints remove that dilemma.

**Every job is warned before its time limit.** A few minutes before the end (10 % of the wall time, between 1 and 10 minutes), the file whose path is in the environment variable `BAOBAB_TIME_UP` appears. Your script checks for it regularly, for example once per loop iteration, and when it appears, saves its state and stops.

**With "Continue automatically" ticked**, stopping is not the end:

- When the warning arrives, Baobab immediately queues the next run, which starts as soon as the current one ends, in the **same job folder**. `BAOBAB_CHECKPOINT_DIR` keeps your checkpoints, and `BAOBAB_RUN` tells your script which run it is (1, 2, 3…).
- Your script ends each run with an **exit code**: **3** means "checkpoint saved, continue", and **0** means "finished". On 0, a run queued in advance is cancelled.
- If the script runs out of time without stopping, it is killed at the limit, and the queued run continues from the last checkpoint anyway.
- **Any other exit code stops everything**, so a script with a bug can't loop, and the number of runs is capped anyway (10 by default).
- Continuation is handled on Baobab itself, so it keeps going with your computer switched off. The Jobs page shows the progress ("run 2 of at most 10"), and the results are downloaded once, after the last run.
- It is not available for job arrays.

**The pattern in Python:**

```python
import os, sys
from pathlib import Path

ckpt = Path(os.environ.get("BAOBAB_CHECKPOINT_DIR", ".")) / "state.npz"
time_up = lambda: os.path.exists(os.environ.get("BAOBAB_TIME_UP", "/nonexistent"))

state = load(ckpt) if ckpt.exists() else start_fresh()   # resume if a checkpoint exists
while not state.finished:
    state = do_one_step(state)                           # a few minutes of work at most
    if time_up():
        save(state, ckpt)
        sys.exit(3)                                      # run me again
save_results(state)                                      # exit code 0: finished
```

**The pattern in MATLAB:**

```matlab
ckpt = fullfile(getenv('BAOBAB_CHECKPOINT_DIR'), 'state.mat');
flag = getenv('BAOBAB_TIME_UP');
if exist(ckpt, 'file'), load(ckpt, 'state'); else, state = start_fresh(); end
while ~state.finished
    state = do_one_step(state);                          % a few minutes of work at most
    if ~isempty(flag) && exist(flag, 'file') == 2
        save(ckpt, 'state');
        exit(3);                                         % run me again
    end
end
save_results(state);                                     % returning normally = finished
```

Save checkpoints often enough that a lost run costs little, and make each step shorter than the warning: 1 minute for short jobs, up to 10 minutes for long ones. For deep learning, the checkpoint is the model and optimiser state saved every epoch or every N steps. Both demos in `examples` use this pattern; `examples\README.md` explains how to watch it work.

---

## Transfers and checksums

- **Data is sent once.** Your data folder is copied to `~/scratch/baobab_data/<name>_<id>/` and reused by later jobs: only new or modified files are sent again. A file changed or damaged on the cluster is detected and re-sent.
- **Everything is verified.** Each file's SHA-256 is computed on your computer and on Baobab and compared. A file that doesn't match is transferred again; if it still doesn't match, the job is **not submitted** (or the download is flagged on the Jobs page) and the file is named.
- **Results arrive complete or not at all.** Downloads are written to a temporary `.part` file and only kept once the checksum matches. Each results folder also contains `_logs\` with the output logs, the exact `submit.sh`, and `job_info.json`.
- **Downloaded results are never uploaded again**, because the `results` folder is excluded from uploads.

---

## Data and results on the lab NAS

Datasets of tens or hundreds of GB shouldn't travel through your PC. Baobab can read and write the lab NAS (`//nasac-m2.isis.unige.ch/m-gholtmaat`) directly, inside the UNIGE network, at about 80 MB/s, roughly 290 GB per hour.

**Logging in.** The first time the app needs the NAS, it asks for your ISIS password and hands it to Kerberos on Baobab. Baobab then holds a ticket that lasts 10 hours, which the app renews automatically for up to a week. The password itself is never stored, neither on your PC nor on Baobab; the ticket is a file in your Baobab home folder that only you can read. The **Settings** page shows until when you're logged in.

**Data from the NAS.** In *Data and results*, choose **A folder on the lab NAS** and pick it with **Browse NAS…**. The app shows its size and how long the first copy takes. When you submit:

1. A **staging job** copies the folder to your scratch space on Baobab, without going through your PC. Your laptop can be closed.
2. Your **job** starts once staging has succeeded. If staging fails (a file unreadable on the NAS, for example), SLURM cancels the job by itself, and the Jobs page says which file.
3. Later jobs on the same folder **only copy new or changed files**, and files deleted from the NAS are removed from the copy.
4. A top-level `results` folder inside the data folder is never copied as data.

**Results to the NAS.** In *Results go to*, choose **This PC**, **The lab NAS** or **Both**. With the NAS, after the job an **upload job** copies the results and the logs into a new folder `<name>_<job id>` in the NAS folder you chose. The default is the `results` folder next to your data. A continuing job sends its results once, after its last run. If a copy to the NAS fails, for instance because the ticket expired while a job waited in the queue for days, select the job and click **Copy results to the NAS**.

**Checks.** Each file copied from the NAS is checked against the size listed on the NAS, and its SHA-256 is recorded. Results sent to the NAS are checked against their size on the NAS. Tick **Full verification** to also re-read every file from the NAS and compare checksums. That doubles the copy time, so it's off by default.

**Datasets on scratch.** The Cluster page lists the datasets copied to Baobab (from your PC or the NAS) with their size and last use. Delete those you no longer need: scratch is shared, not backed up, and deleting never touches the originals.

---

## Seeing what is free

The **Cluster** page shows, for every partition your account can use, the free cores, idle nodes, free GPUs and waiting jobs, plus a summary of free GPUs by type. It refreshes every 2 minutes, or with **Refresh**. The same information feeds the tiles on the New job page.

---

## Deep learning on GPUs

The app handles Python GPU jobs:

1. In your project folder, add a `requirements.txt` listing your packages, for example `torch`, `torchvision`, `numpy`. They are installed once into an environment on your scratch space, then reused by later jobs. PyTorch's pip packages include their own CUDA libraries, so they only need the GPU driver present on the node.
2. In the app, choose `shared-gpu`, a GPU type, and a wall time of at most 12 hours.
3. **Save checkpoints regularly** (model and optimiser state) to `BAOBAB_CHECKPOINT_DIR`, make your script resume from the latest one, and tick **Continue automatically**. A long training then runs as a chain of 12-hour runs, each starting from the last checkpoint. See *Checkpoints and automatic continuation* above.

Alternatives, if pip isn't enough: ready-made modules, which you can look for with `module spider PyTorch` on Baobab, or containers, with `module spider Apptainer`. Keep large environments on scratch, not in your home folder, which has a quota.

---

## Choosing a partition

| Partition | Max time | Use for |
|---|---|---|
| `debug-cpu` | 15 min | testing a script |
| `shared-cpu` | 12 h | most jobs; starts fastest |
| `public-cpu` | 4 days | long jobs |
| `public-longrun-cpu` | 14 days | very long jobs, max 2 cores |
| `shared-gpu` | 12 h | GPU jobs (Baobab's GPU nodes are shared) |

Ask only for the time and memory you need: smaller requests start sooner. After a job, `seff <jobid>` on the cluster shows how much was actually used.

---

## Troubleshooting

| Message | Cause and fix |
|---|---|
| *Baobab rejected your SSH key* | The public key isn't registered or not synced yet. Check my-account.unige.ch and wait 15 minutes. |
| *SSH key file not found* | Wrong key path in Settings. Check with `dir %USERPROFILE%\.ssh`. |
| *Baobab closed the connection before login* / `Connection closed by … port 22` | You're outside the UNIGE network: connect to the UNIGE VPN. Otherwise your address is banned for 15 minutes after 3 failed logins; wait without retrying. |
| *SECURITY WARNING: … presented an unexpected identity* | The server did not prove it is Baobab. Don't force it: switch to another network, such as the UNIGE VPN or your phone's connection, and if it persists, contact the HPC team. The app has sent nothing, neither key nor data. |
| *The NAS refused the login* | Your NAS ticket expired. Log in again (Settings → Log in to the NAS), then click **Copy results to the NAS** on the job, or resubmit. |
| *copy from the NAS failed: not verified: …* | A file on the NAS could not be read completely, for example because of permissions or because it was being written. Fix it on the NAS and resubmit: files already copied are not copied again. |
| *Cannot reach login1…* | No network, or the Wi-Fi blocks SSH. Try another network. |
| *This request cannot run on …* | The tile says why: wall time over the limit, no node with that many CPUs or that much memory, or no GPU. Change the resources or pick a tile marked **Can start now** or **Will queue**. |
| Job stuck in `PENDING` | The requested resources are busy. A shorter wall time or fewer CPUs helps. |
| `OUT_OF_MEMORY` | Increase memory per CPU. |
| `FAILED` | Select the job and click **Show log**; the error is at the bottom. |
| *CHECKSUM MISMATCH* | Rare network problem. Click **Download results now** to retry. |
| *Installing Python packages failed* | A package in `requirements.txt` doesn't install with that Python version. The message shows pip's error. |
| The app doesn't open | Run `Baobab_Launcher.bat`; if it shows an error, delete the `.venv` folder and relaunch. |

**Where the app keeps its files:** `C:\Users\<you>\.baobab_hpc\` holds your profile, the job list, the checksum cache, and `app.log` for diagnostics.

**On the cluster:** scratch is **not backed up**, so keep your originals locally. Jobs are in `~/scratch/baobab_jobs/` and datasets in `~/scratch/baobab_data/`; delete old ones there when you no longer need them. Accounts inactive for a year are deleted along with their data.

**Official documentation:** <https://doc.eresearch.unige.ch/hpc/start> · HPC community forum: <https://hpc-community.unige.ch>

---

## Licence

MIT, see [LICENSE](LICENSE). You may use, modify and share this app freely, including in other labs, as long as the licence notice is kept.
