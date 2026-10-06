#!/usr/bin/env python3
"""
Baobab HPC - transfers between the lab NAS (SMB) and Baobab's scratch space.

Runs ON BAOBAB (login or compute node), inside the staging and upload jobs the
app submits. Needs only Python's standard library and smbclient.

  baobab_nas.py ls   --share //host/share --path DIR [--recursive]   -> JSON
  baobab_nas.py pull --share //host/share --path DIR --dest LOCAL [--full]
  baobab_nas.py push --share //host/share --path DIR --src LOCAL [--full]

Authentication: the Kerberos ticket in KRB5CCNAME (default), or a credentials
file given in BAOBAB_SMB_AUTHFILE.

pull mirrors DIR into LOCAL (except a top-level "results" folder, which holds
results of earlier jobs): only new or changed files (size or date) are copied,
files gone from the NAS are removed, and LOCAL/.baobab_dataset.json
records what was copied. Every copied file is checked: its size against the
NAS listing, and its SHA-256 recorded; --full also re-reads it from the NAS and
compares checksums. Exit code 0 = done, 1 = error, 2 = verification failed.
"""
import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

MANIFEST = ".baobab_dataset.json"     # per-file sizes, dates and checksums
INFO = ".baobab_info.json"             # one-line summary shown in the app
RESULTS_DIR = "results"                # never copied as data (results of earlier jobs)
BATCH = 200                      # files per smbclient session
ENTRY = re.compile(r"^  (.*?)\s+([A-Za-z]*)\s+(\d+)\s+"
                   r"(\w{3} \w{3}\s+\d{1,2} \d\d:\d\d:\d\d \d{4})$")


class NasError(Exception):
    pass


# ── smbclient ────────────────────────────────────────────────────────────────
def smb_cmd(share: str, directory: str = "") -> list:
    cmd = ["smbclient", share]
    authfile = os.environ.get("BAOBAB_SMB_AUTHFILE")
    cmd += ["-A", authfile] if authfile else ["--use-kerberos=required"]
    if directory:
        cmd += ["-D", directory.replace("/", "\\")]
    return cmd


def smb_run(share: str, directory: str, commands: list, stdout=subprocess.PIPE,
            check: bool = True) -> subprocess.CompletedProcess:
    """Run smbclient commands (one per line, read from stdin)."""
    p = subprocess.run(smb_cmd(share, directory), input="\n".join(commands + ["exit"]) + "\n",
                       stdout=stdout, stderr=subprocess.PIPE, text=stdout is subprocess.PIPE,
                       encoding="utf-8" if stdout is subprocess.PIPE else None,
                       errors="replace" if stdout is subprocess.PIPE else None)
    if check and p.returncode != 0:
        # smbclient prints most of its errors on stdout
        out = p.stdout if isinstance(p.stdout, str) else ""
        err = p.stderr if isinstance(p.stderr, str) else p.stderr.decode("utf-8", "replace")
        raise NasError(explain(out + "\n" + err) or f"smbclient failed ({p.returncode})")
    return p


def explain(err: str) -> str:
    err = "\n".join(l for l in err.splitlines() if l.strip()).strip()
    if "NT_STATUS_OBJECT_NAME_NOT_FOUND" in err or "NT_STATUS_OBJECT_PATH_NOT_FOUND" in err:
        return "Folder or file not found on the NAS: " + err.splitlines()[-1]
    if "NT_STATUS_ACCESS_DENIED" in err:
        return "Access denied on the NAS (no permission for this folder)."
    if "Kerberos" in err or "NT_STATUS_LOGON_FAILURE" in err or "krb5" in err.lower() \
            or "NT_STATUS_INVALID_PARAMETER" in err:
        return ("The NAS refused the login: the Kerberos ticket is missing or expired. "
                "Log in to the NAS again from the app. (" + err.splitlines()[-1] + ")")
    return err.splitlines()[-1] if err else ""


def quote(path: str) -> str:
    if '"' in path:
        raise NasError(f'Unsupported character " in name: {path}')
    return '"' + path + '"'


def parse_listing(out: str, base: str, recursive: bool):
    """smbclient 'ls' output -> files [(rel, size, mtime)], dirs [rel]."""
    prefix = "\\" + base.strip("/").replace("/", "\\") if base.strip("/") else ""
    files, dirs, cur = [], [], ""
    for line in out.splitlines():
        if line.startswith("\\"):                   # recursive section header
            p = line.rstrip()
            cur = p[len(prefix):].lstrip("\\").replace("\\", "/") if p.startswith(prefix) else p
            continue
        m = ENTRY.match(line)
        if not m:
            continue
        name, attr, size, date = m.groups()
        if name in (".", ".."):
            continue
        rel = f"{cur}/{name}" if cur else name
        if "D" in attr:
            dirs.append(rel)
        else:
            try:
                mtime = int(time.mktime(time.strptime(date, "%a %b %d %H:%M:%S %Y")))
            except ValueError:
                mtime = 0
            files.append((rel, int(size), mtime))
    if not recursive:
        dirs = [d for d in dirs if "/" not in d]
    return files, dirs


def listing(share: str, path: str, recursive: bool):
    cmds = ["recurse ON", "ls"] if recursive else ["ls"]
    out = smb_run(share, path, cmds).stdout
    return parse_listing(out, path, recursive)


# ── helpers ──────────────────────────────────────────────────────────────────
def sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(8 * 1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def sha256_remote(share: str, path: str, rel: str) -> str:
    """Stream one NAS file through SHA-256 without storing it."""
    p = subprocess.Popen(smb_cmd(share, path) + ["-c", f'get {quote(rel.replace("/", chr(92)))} -'],
                         stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    h = hashlib.sha256()
    for chunk in iter(lambda: p.stdout.read(8 * 1024 * 1024), b""):
        h.update(chunk)
    if p.wait() != 0:
        raise NasError(f"Could not re-read {rel} from the NAS")
    return h.hexdigest()


def human(n: float) -> str:
    for u in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or u == "TB":
            return f"{n:.0f} {u}" if u == "B" else f"{n:.1f} {u}"
        n /= 1024
    return f"{n:.1f} TB"


class Progress:
    def __init__(self, total_files: int, total_bytes: int, what: str, progress_file: str):
        self.tf, self.tb, self.what, self.pf = total_files, max(total_bytes, 1), what, progress_file
        self.files = self.bytes = 0
        self.t0 = time.time()

    def add(self, n_files: int, n_bytes: int):
        self.files += n_files
        self.bytes += n_bytes
        rate = self.bytes / max(time.time() - self.t0, 1e-6)
        left = (self.tb - self.bytes) / rate if rate > 0 else 0
        msg = (f"progress: {self.what} {self.files}/{self.tf} files, {human(self.bytes)} of "
               f"{human(self.tb)} ({100 * self.bytes / self.tb:.0f}%), {human(rate)}/s, "
               f"about {int(left // 60)} min left")
        print(msg, flush=True)
        if self.pf:
            Path(self.pf).write_text(json.dumps({"what": self.what, "files": self.files,
                                                 "total_files": self.tf, "bytes": self.bytes,
                                                 "total_bytes": self.tb, "rate": rate,
                                                 "left_s": left, "time": time.time()}))


# ── pull: NAS -> scratch ─────────────────────────────────────────────────────
def pull(share, path, dest, full=False, progress_file=""):
    dest = Path(dest)
    dest.mkdir(parents=True, exist_ok=True)
    mpath = dest / MANIFEST
    try:
        manifest = json.loads(mpath.read_text())
    except (OSError, ValueError):
        manifest = {}
    known = manifest.get("files", {})
    remote, rdirs = listing(share, path, True)
    # the top-level "results" folder holds results of earlier jobs, not data: skip it
    remote = [f for f in remote if f[0].split("/")[0].lower() != RESULTS_DIR]
    rdirs = [d for d in rdirs if d.split("/")[0].lower() != RESULTS_DIR]
    names = {r for r, _, _ in remote}
    for r, _, _ in remote:
        if '"' in r:
            raise NasError(f'A file name contains ", which smbclient cannot handle: {r}')

    # files gone from the NAS: remove the local copy (the dataset mirrors the NAS)
    removed = 0
    for p in sorted(dest.rglob("*"), reverse=True):
        rel = p.relative_to(dest).as_posix()
        if p.is_file() and rel not in (MANIFEST, INFO) and rel not in names \
                and not rel.endswith(".part"):
            p.unlink()
            known.pop(rel, None)
            removed += 1
        elif p.is_file() and rel.endswith(".part"):
            p.unlink()
    for d in rdirs:
        (dest / d).mkdir(parents=True, exist_ok=True)

    todo = []
    for rel, size, mtime in remote:
        k = known.get(rel)
        lp = dest / rel
        if k and k[0] == size and k[1] == mtime and lp.is_file() and lp.stat().st_size == size:
            continue
        todo.append((rel, size, mtime))
    skipped = len(remote) - len(todo)
    total = sum(s for _, s, _ in todo)
    print(f"plan: {len(remote)} file(s) on the NAS, {len(todo)} to copy ({human(total)}), "
          f"{skipped} unchanged, {removed} removed locally", flush=True)

    def fetch(batch, pr):
        for i in range(0, len(batch), BATCH):
            chunk = batch[i:i + BATCH]
            cmds = [f'get {quote(r.replace("/", chr(92)))} {quote(str(dest / (r + ".part")))}'
                    for r, _, _ in chunk]
            smb_run(share, path, cmds, check=False)
            bad = []
            for rel, size, mtime in chunk:
                part = dest / (rel + ".part")
                if part.is_file() and part.stat().st_size == size:
                    digest = sha256_file(part)
                    os.replace(part, dest / rel)
                    os.utime(dest / rel, (mtime, mtime))
                    known[rel] = [size, mtime, digest]
                else:
                    part.unlink(missing_ok=True)
                    bad.append((rel, size, mtime))
            pr.add(len(chunk) - len(bad), sum(s for _, s, _ in chunk) -
                   sum(s for _, s, _ in bad))
            manifest.update(files=known)
            mpath.write_text(json.dumps(manifest))        # resumable if interrupted
            yield from bad

    pr = Progress(len(todo), total, "copying from the NAS", progress_file)
    failed = list(fetch(todo, pr))
    if failed:
        print(f"retry: {len(failed)} file(s) incomplete, copying them again", flush=True)
        failed = list(fetch(failed, pr))

    mismatched = []
    if full and todo:
        vp = Progress(len(todo), total, "re-reading from the NAS to verify", progress_file)
        for rel, size, mtime in todo:
            if rel in [f[0] for f in failed]:
                continue
            if sha256_remote(share, path, rel) != known[rel][2]:
                mismatched.append(rel)
            vp.add(1, size)
        if mismatched:
            print(f"retry: {len(mismatched)} file(s) differ from the NAS, copying them again",
                  flush=True)
            again = [t for t in todo if t[0] in mismatched]
            failed += list(fetch(again, pr))
            mismatched = [r for r in mismatched
                          if sha256_remote(share, path, r) != known.get(r, [0, 0, ""])[2]]

    manifest.update(source=f"NAS {share}/{path}", files=known, complete=not failed and not
                    mismatched, total_bytes=sum(v[0] for v in known.values()),
                    last_used=time.time())
    mpath.write_text(json.dumps(manifest))
    (dest / INFO).write_text(json.dumps({                 # small summary for the app
        "source": f"NAS: {path}", "total_bytes": manifest["total_bytes"],
        "files": len(known), "last_used": time.time(), "complete": manifest["complete"]}))
    if failed or mismatched:
        for r in [f[0] for f in failed] + mismatched:
            print(f"error: not verified: {r}", flush=True)
        raise SystemExit(2)
    print(f"summary: {len(todo)} file(s) copied ({human(total)}), {skipped} unchanged, "
          f"{removed} removed; checks: sizes + SHA-256 recorded"
          + (", re-read from the NAS: all match" if full else ""), flush=True)


# ── push: scratch -> NAS ─────────────────────────────────────────────────────
def push(share, path, src, full=False, progress_file=""):
    src = Path(src)
    files = [(p.relative_to(src).as_posix(), p.stat().st_size, p)
             for p in sorted(src.rglob("*")) if p.is_file() and not p.name.endswith(".part")]
    for rel, _, _ in files:
        quote(rel)
    # create the destination folder, component by component (existing ones are fine)
    parts = [x for x in path.strip("/").split("/") if x]
    mk = ["mkdir " + quote("\\".join(parts[:i + 1])) for i in range(len(parts))]
    sub = sorted({str(Path(r).parent).replace("\\", "/") for r, _, _ in files} - {"."},
                 key=lambda d: d.count("/"))
    smb_run(share, "", mk, check=False)
    smb_run(share, path, ["mkdir " + quote(d.replace("/", "\\")) for d in sub], check=False)
    total = sum(s for _, s, _ in files)
    print(f"plan: {len(files)} file(s) to send ({human(total)})", flush=True)
    pr = Progress(len(files), total, "copying to the NAS", progress_file)

    def send(batch):
        for i in range(0, len(batch), BATCH):
            chunk = batch[i:i + BATCH]
            smb_run(share, path, [f'put {quote(str(p))} {quote(r.replace("/", chr(92)))}'
                                  for r, _, p in chunk], check=False)
            pr.add(len(chunk), sum(s for _, s, _ in chunk))

    send(files)
    remote = {r: s for r, s, _ in listing(share, path, True)[0]}
    bad = [f for f in files if remote.get(f[0]) != f[1]]
    if bad:
        print(f"retry: {len(bad)} file(s) incomplete on the NAS, sending them again", flush=True)
        send(bad)
        remote = {r: s for r, s, _ in listing(share, path, True)[0]}
        bad = [f for f in files if remote.get(f[0]) != f[1]]
    if full and not bad:
        vp = Progress(len(files), total, "re-reading from the NAS to verify", progress_file)
        for rel, size, p in files:
            if sha256_remote(share, path, rel) != sha256_file(p):
                bad.append((rel, size, p))
            vp.add(1, size)
    if bad:
        for r, _, _ in bad:
            print(f"error: not verified on the NAS: {r}", flush=True)
        raise SystemExit(2)
    print(f"summary: {len(files)} file(s) sent ({human(total)}); checks: sizes on the NAS"
          + (" + SHA-256 re-read from the NAS: all match" if full else ""), flush=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("action", choices=["ls", "pull", "push"])
    ap.add_argument("--share", required=True)
    ap.add_argument("--path", default="")
    ap.add_argument("--dest")
    ap.add_argument("--src")
    ap.add_argument("--recursive", action="store_true")
    ap.add_argument("--full", action="store_true")
    ap.add_argument("--progress-file", default="")
    a = ap.parse_args()
    try:
        if a.action == "ls":
            files, dirs = listing(a.share, a.path, a.recursive)
            print(json.dumps({"path": a.path, "dirs": sorted(dirs, key=str.lower),
                              "files": [{"name": r, "size": s, "mtime": m} for r, s, m in files],
                              "total_bytes": sum(s for _, s, _ in files)}))
        elif a.action == "pull":
            pull(a.share, a.path, a.dest, a.full, a.progress_file)
        else:
            push(a.share, a.path, a.src, a.full, a.progress_file)
    except NasError as e:
        print(f"error: {e}", flush=True)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
