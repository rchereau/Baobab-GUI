"""
Baobab HPC — core logic (no GUI).

SSH connection, SHA-256-verified transfers, SLURM script generation and job
tracking for the UNIGE Baobab cluster. Used by baobab_app.py.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import posixpath
import re
import secrets
import shlex
import socket
import threading
import time
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

import paramiko

# ── Local storage ─────────────────────────────────────────────────────────────
APP_DIR = Path.home() / ".baobab_hpc"
PROFILE_FILE = APP_DIR / "profile.json"
JOBS_FILE = APP_DIR / "jobs.json"
HASH_CACHE_FILE = APP_DIR / "hash_cache.json"
LOG_FILE = APP_DIR / "app.log"
OLD_PROFILE_FILE = Path.home() / ".baobab_profile.json"   # from the web version

DEFAULT_HOST = "login1.baobab.hpc.unige.ch"

# Folders/files never uploaded with code
CODE_EXCLUDE_DIRS = {".git", ".svn", "__pycache__", ".venv", "venv", ".idea",
                     ".vscode", ".ipynb_checkpoints", "slprj"}
CODE_EXCLUDE_FILES = {".DS_Store", "Thumbs.db", "desktop.ini"}
CODE_EXCLUDE_SUFFIXES = {".asv", ".pyc", ".pyo", ".m~"}
# Top-level folder of a project/data folder that holds downloaded results:
# never re-uploaded, otherwise results would travel back to the cluster.
RESULTS_DIRNAME = "results"

FINAL_STATES = {"COMPLETED", "FAILED", "CANCELLED", "TIMEOUT", "OUT_OF_MEMORY",
                "NODE_FAIL", "PREEMPTED", "BOOT_FAIL", "DEADLINE", "UNKNOWN"}
# Worst first: used to summarise the state of a job array
STATE_SEVERITY = ["NODE_FAIL", "BOOT_FAIL", "OUT_OF_MEMORY", "FAILED", "TIMEOUT",
                  "DEADLINE", "PREEMPTED", "CANCELLED", "COMPLETED"]

KEY_REJECTED_MSG = (
    "Baobab rejected your SSH key. Check that the matching public key (.pub) is "
    "registered at https://my-account.unige.ch ('My SSH public key'), then wait "
    "10-15 minutes for the sync.")

BANNED_MSG = (
    "Baobab closed the connection before login. Two usual causes:\n"
    "1. You are outside the UNIGE network (at home, abroad): connect to the UNIGE "
    "VPN, then click Connect.\n"
    "2. Your address is temporarily banned after 3 failed logins in a row: wait "
    "15 minutes without retrying, then click Connect once.")

q = shlex.quote


class BaobabError(Exception):
    """Error with a message meant for the user."""


class PassphraseRequired(BaobabError):
    pass


class UnknownHostKey(BaobabError):
    """A server this app has never seen: the user must confirm its fingerprint once."""

    def __init__(self, host: str, key_type: str, fingerprint: str):
        super().__init__(f"Unknown server {host}")
        self.host, self.key_type, self.fingerprint = host, key_type, fingerprint


# ── Server identity ───────────────────────────────────────────────────────────
# Fingerprints of Baobab's login node. RSA: UNIGE HPC documentation (hpc/access_the_hpc_clusters).
# ED25519: seen when logging in to login1.baobab and confirmed on the node itself with
# `ssh-keygen -lf /etc/ssh/ssh_host_ed25519_key.pub`.
PINNED_HOST_KEYS = {
    "login1.baobab.hpc.unige.ch": {
        "ssh-rsa": "SHA256:tKqp4nljL+EGVKl8T0VF2nS36DkHVFMpLxQOPg/gKvg",
        "ssh-ed25519": "SHA256:R/cy4lk5x8qKwmrIq8R9tiRdneDtorBnqzEynx8OnGI",
    },
}
KNOWN_HOSTS_FILE = APP_DIR / "known_hosts"          # servers the user confirmed
# Only negotiate key types that are pinned, so a pinned server never shows another one
_UNPINNED_KEY_TYPES = ["ecdsa-sha2-nistp256", "ecdsa-sha2-nistp384", "ecdsa-sha2-nistp521",
                       "ssh-dss"]


def fingerprint(key) -> str:
    return "SHA256:" + base64.b64encode(hashlib.sha256(key.asbytes()).digest()).decode().rstrip("=")


class _VerifyHostKey(paramiko.MissingHostKeyPolicy):
    """Pinned servers must match their known fingerprint; others need the user's OK."""

    def __init__(self, accept: str | None):
        self.accept = accept

    def missing_host_key(self, client, hostname, key):
        name = hostname.split("]")[0].lstrip("[") if hostname.startswith("[") else hostname
        fp, ktype = fingerprint(key), key.get_name()
        pinned = PINNED_HOST_KEYS.get(name.lower())
        if pinned is not None:
            if pinned.get(ktype) != fp:
                raise BaobabError(
                    f"SECURITY WARNING: {name} presented an unexpected identity ({ktype} {fp}). "
                    "This can mean that someone is impersonating the cluster, for example on a "
                    "public Wi-Fi. The app did not connect and sent nothing. Try another network, "
                    "and if it persists, contact the HPC team.")
        elif self.accept != fp:
            raise UnknownHostKey(name, ktype, fp)
        client.get_host_keys().add(hostname, key.get_name(), key)
        try:
            KNOWN_HOSTS_FILE.parent.mkdir(parents=True, exist_ok=True)
            client.save_host_keys(str(KNOWN_HOSTS_FILE))
        except OSError:
            pass


# ── Profile ───────────────────────────────────────────────────────────────────
DEFAULT_PROFILE = {
    "username": "",
    "email": "",
    "host": DEFAULT_HOST,
    "key_path": "",
    "matlab_module": "MATLAB/2022a",
    "python_version": "Python/3.12.3",
    "python_modules": "",          # full load line, resolved from Baobab
    "cuda_module": "CUDA",
    "auto_download": True,
    "last_project": "",
    "last_data": "",
}


def default_key_path() -> str:
    for name in ("id_rsa", "id_ed25519", "id_ecdsa"):
        p = Path.home() / ".ssh" / name
        if p.exists():
            return str(p)
    return ""


def load_profile() -> dict:
    prof = dict(DEFAULT_PROFILE)
    src = PROFILE_FILE if PROFILE_FILE.exists() else OLD_PROFILE_FILE
    if src.exists():
        try:
            data = json.loads(src.read_text(encoding="utf-8"))
            prof.update({k: v for k, v in data.items() if k in DEFAULT_PROFILE and v != ""})
        except (OSError, ValueError):
            pass
    if not prof["key_path"]:
        prof["key_path"] = default_key_path()
    if not prof["host"]:
        prof["host"] = DEFAULT_HOST
    return prof


def save_profile(prof: dict) -> None:
    APP_DIR.mkdir(parents=True, exist_ok=True)
    data = {k: prof.get(k, v) for k, v in DEFAULT_PROFILE.items()}   # never a passphrase
    tmp = PROFILE_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
    os.replace(tmp, PROFILE_FILE)


# ── Hashing ───────────────────────────────────────────────────────────────────
def sha256_file(path, chunk=4 * 1024 * 1024) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            b = f.read(chunk)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


class HashCache:
    """Remembers local file hashes by (size, mtime) so unchanged files are not re-read."""

    def __init__(self, path: Path = HASH_CACHE_FILE):
        self.path = path
        self.lock = threading.Lock()
        self.data: dict = {}
        self.dirty = False
        try:
            self.data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            self.data = {}

    def get(self, p: Path) -> str:
        st = p.stat()
        key = str(p.resolve())
        with self.lock:
            e = self.data.get(key)
            if e and e[0] == st.st_size and e[1] == st.st_mtime_ns:
                return e[2]
        h = sha256_file(p)
        with self.lock:
            self.data[key] = [st.st_size, st.st_mtime_ns, h]
            self.dirty = True
        return h

    def save(self):
        with self.lock:
            if not self.dirty:
                return
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(self.data), encoding="utf-8")
            os.replace(tmp, self.path)
            self.dirty = False


# ── Local file listing ────────────────────────────────────────────────────────
def list_local_files(root, kind: str = "code") -> list[tuple[str, Path, int]]:
    """Return sorted (relative posix path, absolute Path, size) for files under root.

    kind="code": skips VCS/IDE/cache folders. kind="data": keeps everything.
    Both skip the top-level 'results' folder (where results are downloaded).
    """
    root = Path(root)
    out = []
    for dirpath, dirnames, filenames in os.walk(root):
        d = Path(dirpath)
        keep = []
        for name in dirnames:
            if d == root and name.lower() == RESULTS_DIRNAME:
                continue
            if kind == "code" and name in CODE_EXCLUDE_DIRS:
                continue
            keep.append(name)
        dirnames[:] = sorted(keep)
        for name in filenames:
            if kind == "code" and (name in CODE_EXCLUDE_FILES
                                   or Path(name).suffix.lower() in CODE_EXCLUDE_SUFFIXES):
                continue
            if name.endswith(".part"):
                continue
            p = d / name
            try:
                size = p.stat().st_size
            except OSError:
                continue
            out.append((p.relative_to(root).as_posix(), p, size))
    out.sort(key=lambda t: t[0])
    return out


def human_size(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} TB"


def safe_name(s: str, default="job") -> str:
    s = re.sub(r"[^A-Za-z0-9_\-]+", "_", s).strip("_")
    return s[:60] or default


_WIN_BAD = re.compile(r'[<>:"|?*\x00-\x1f]')


def windows_safe(rel: str) -> str:
    return "/".join(_WIN_BAD.sub("_", part).rstrip(" .") or "_" for part in rel.split("/"))


# ── SSH connection ────────────────────────────────────────────────────────────
class Connection:
    """One SSH connection to Baobab, usable from several threads
    (each transfer opens its own SFTP channel)."""

    def __init__(self):
        self.client: paramiko.SSHClient | None = None
        self.profile: dict = {}
        self.passphrase: str | None = None
        self.scratch: str = ""
        self.hostname: str = ""
        self._lock = threading.RLock()

    def connect(self, profile: dict, passphrase: str | None = None,
                accept_fingerprint: str | None = None) -> str:
        user = profile.get("username", "").strip()
        host = profile.get("host", "").strip() or DEFAULT_HOST
        if not user:
            raise BaobabError("Enter your ISIS username first.")
        client = paramiko.SSHClient()
        try:
            client.load_system_host_keys()
        except (OSError, paramiko.SSHException):
            pass
        if KNOWN_HOSTS_FILE.exists():
            try:
                client.load_host_keys(str(KNOWN_HOSTS_FILE))
            except (OSError, paramiko.SSHException):
                pass
        client.set_missing_host_key_policy(_VerifyHostKey(accept_fingerprint))
        kw = dict(hostname=host, username=user, port=int(profile.get("port", 22)),
                  timeout=20, banner_timeout=30, auth_timeout=30,
                  allow_agent=True, look_for_keys=True)
        if host.lower() in PINNED_HOST_KEYS:
            kw["disabled_algorithms"] = {"keys": _UNPINNED_KEY_TYPES}
        key_path = profile.get("key_path", "").strip()
        if key_path:
            kp = Path(key_path).expanduser()
            if not kp.exists():
                raise BaobabError(f"SSH key file not found: {kp}")
            kw["key_filename"] = str(kp)
            # Offer ONLY this key: every refused key counts as a failed login, and
            # Baobab bans the address for 15 min after 3 failures in a row.
            kw["allow_agent"] = False
            kw["look_for_keys"] = False
        if passphrase:
            kw["passphrase"] = passphrase
        try:
            client.connect(**kw)
        except BaobabError:
            raise                                   # identity checks (unknown / wrong key)
        except paramiko.BadHostKeyException as e:
            raise BaobabError(
                f"SECURITY WARNING: {host} presented an identity that differs from the one "
                f"recorded earlier ({fingerprint(e.key)}). This can mean that someone is "
                "impersonating the server. The app did not connect. If the HPC team announced a "
                f"change, remove the old entry for {host} from your known_hosts file.") from e
        except paramiko.PasswordRequiredException:
            raise PassphraseRequired("Your SSH key is protected by a passphrase.")
        except paramiko.AuthenticationException:
            raise BaobabError(KEY_REJECTED_MSG)
        except (EOFError, ConnectionResetError) as e:
            raise BaobabError(BANNED_MSG) from e
        except paramiko.SSHException as e:
            if any(w in str(e).lower() for w in ("banner", "closed", "reset", "eof")):
                raise BaobabError(BANNED_MSG) from e
            if passphrase:
                raise BaobabError(f"Could not unlock the SSH key - wrong passphrase? ({e})")
            raise BaobabError(f"SSH error: {e}")
        except (socket.timeout, socket.gaierror, OSError) as e:
            raise BaobabError(f"Cannot reach {host}: {e}")
        client.get_transport().set_keepalive(30)
        with self._lock:
            self.close()
            self.client = client
            self.profile = dict(profile)
            self.passphrase = passphrase        # (the confirmed key is now remembered)
        self.hostname = self.run("hostname")[0].strip()
        self.scratch = self._detect_scratch()
        return self.hostname

    def close(self):
        with self._lock:
            if self.client:
                try:
                    self.client.close()
                except Exception:
                    pass
            self.client = None

    def alive(self) -> bool:
        t = self.client.get_transport() if self.client else None
        return bool(t and t.is_active())

    def ensure(self):
        with self._lock:
            if self.alive():
                return
            if not self.profile:
                raise BaobabError("Not connected to Baobab.")
            self.connect(self.profile, self.passphrase)

    def run(self, cmd: str, timeout: float | None = 60, stdin_data: bytes | None = None,
            check: bool = True) -> tuple[str, str, int]:
        self.ensure()
        stdin, stdout, stderr = self.client.exec_command(cmd, timeout=timeout)
        if stdin_data is not None:
            stdin.write(stdin_data)
            stdin.flush()
        stdin.channel.shutdown_write()
        out = stdout.read().decode("utf-8", errors="replace")
        err = stderr.read().decode("utf-8", errors="replace")
        code = stdout.channel.recv_exit_status()
        if check and code != 0:
            raise BaobabError(f"Remote command failed ({code}): {err.strip() or out.strip()}")
        return out, err, code

    def run_login(self, cmd: str, **kw):
        """Run in a login shell, needed for 'module'."""
        return self.run(f"bash -lc {q(cmd)}", **kw)

    def sftp(self) -> paramiko.SFTPClient:
        self.ensure()
        return self.client.open_sftp()

    def _detect_scratch(self) -> str:
        cmd = ('for d in "$HOME/scratch" "/srv/beegfs/scratch/users/${USER:0:1}/$USER"; do '
               '[ -d "$d" ] && readlink -f "$d" && exit 0; done; '
               'mkdir -p "$HOME/hpc_jobs" && readlink -f "$HOME/hpc_jobs"')
        out, _, _ = self.run(cmd, check=False)
        lines = out.strip().splitlines()
        if not lines:
            raise BaobabError("Could not find your scratch folder on Baobab.")
        return lines[-1].strip()


# ── Remote helpers ────────────────────────────────────────────────────────────
def parse_sha256sum(out: str) -> dict[str, str]:
    res = {}
    for line in out.splitlines():
        esc = line.startswith("\\")
        if esc:
            line = line[1:]
        if len(line) < 67 or line[64:66] not in ("  ", " *"):
            continue
        h, path = line[:64], line[66:]
        if esc:
            path = path.replace("\\n", "\n").replace("\\\\", "\\")
        if path.startswith("./"):
            path = path[2:]
        res[path] = h.lower()
    return res


def remote_hashes(conn: Connection, base: str, rels: list[str] | None = None) -> dict[str, str]:
    """SHA-256 of remote files, keyed by path relative to base."""
    if rels is None:
        cmd = f"cd {q(base)} 2>/dev/null && find . -type f -print0 | xargs -0 -r sha256sum"
        out, _, _ = conn.run(cmd, timeout=None, check=False)
    else:
        if not rels:
            return {}
        cmd = f"cd {q(base)} && xargs -0 -r sha256sum --"
        out, _, _ = conn.run(cmd, timeout=None, check=False,
                             stdin_data="\0".join(rels).encode("utf-8"))
    return parse_sha256sum(out)


def remote_file_list(conn: Connection, base: str) -> list[tuple[str, int]]:
    out, _, _ = conn.run(f"cd {q(base)} 2>/dev/null && find . -type f -printf '%s\\t%P\\n'",
                         timeout=None, check=False)
    res = []
    for line in out.splitlines():
        size, _, rel = line.partition("\t")
        if rel and size.isdigit():
            res.append((rel, int(size)))
    return sorted(res)


def remote_mkdirs(conn: Connection, base: str, rel_dirs) -> None:
    dirs = sorted({base} | {posixpath.join(base, d) for d in rel_dirs if d})
    for i in range(0, len(dirs), 200):
        conn.run("mkdir -p " + " ".join(q(d) for d in dirs[i:i + 200]))


# ── Transfers ─────────────────────────────────────────────────────────────────
@dataclass
class TransferReport:
    label: str
    files: int = 0          # files considered
    transferred: int = 0    # files actually copied
    skipped: int = 0        # unchanged, not copied
    bytes: int = 0          # bytes copied
    mismatches: list = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.mismatches

    def summary(self) -> str:
        if self.files == 0:
            return f"{self.label}: nothing to transfer"
        if self.transferred == 0 and self.skipped:
            return (f"{self.label}: all {self.skipped} file(s) already there and unchanged "
                    "(checksums match) - nothing sent")
        parts = [f"{self.label}: {self.transferred} file(s) copied ({human_size(self.bytes)})"]
        if self.skipped:
            parts.append(f"{self.skipped} unchanged skipped")
        if self.ok:
            parts.append("all SHA-256 checksums match")
        else:
            parts.append(f"{len(self.mismatches)} CHECKSUM MISMATCH(ES): "
                         + ", ".join(self.mismatches[:5]))
        return " - ".join(parts)


class _Progress:
    def __init__(self, cb, phase: str, total_bytes: int, total_files: int):
        self.cb, self.phase = cb, phase
        self.total, self.files_total = max(total_bytes, 1), total_files
        self.done, self.files_done, self.file, self._last = 0, 0, "", 0.0

    def emit(self, force=False):
        now = time.monotonic()
        if self.cb and (force or now - self._last > 0.15):
            self._last = now
            self.cb({"phase": self.phase, "done": self.done, "total": self.total,
                     "files_done": self.files_done, "files_total": self.files_total,
                     "file": self.file})


def _log(cb, msg: str):
    if cb:
        cb({"log": msg})


def _phase(cb, text: str):
    if cb:
        cb({"phase": text, "done": 0, "total": 0, "files_done": 0, "files_total": 0,
            "file": ""})


def upload_tree(conn: Connection, local_root, remote_root: str, *, kind="code",
                skip_unchanged=False, cache: HashCache | None = None,
                progress=None, label="Upload") -> TransferReport:
    local_root = Path(local_root)
    cache = cache or HashCache()
    files = list_local_files(local_root, kind)
    rep = TransferReport(label, files=len(files))
    conn.run(f"mkdir -p {q(remote_root)}")
    if not files:
        return rep

    # 1. local checksums (cached by size+mtime)
    total = sum(s for _, _, s in files)
    pr = _Progress(progress, f"{label}: computing local checksums", total, len(files))
    local_hash = {}
    for rel, p, size in files:
        pr.file = rel
        pr.emit()
        local_hash[rel] = cache.get(p)
        pr.done += size
        pr.files_done += 1
    cache.save()

    # 2. what is already on the cluster and identical?
    remote_mkdirs(conn, remote_root, {posixpath.dirname(r) for r, _, _ in files})
    if skip_unchanged:
        _phase(progress, f"{label}: checking what is already on Baobab")
        existing = remote_hashes(conn, remote_root)
    else:
        existing = {}
    todo = [f for f in files if existing.get(f[0]) != local_hash[f[0]]]
    rep.skipped = len(files) - len(todo)

    # 3. copy, verify, retry failed files once
    def copy(batch):
        pr = _Progress(progress, label, sum(s for _, _, s in batch), len(batch))
        sftp = conn.sftp()
        try:
            for rel, p, size in batch:
                pr.file = rel
                start = pr.done

                def cb(d, t, s=start):
                    pr.done = s + d
                    pr.emit()
                sftp.put(str(p), posixpath.join(remote_root, rel), callback=cb, confirm=True)
                pr.done = start + size
                pr.files_done += 1
                rep.bytes += size
                pr.emit()
        finally:
            sftp.close()
        pr.emit(force=True)

    def verify(batch):
        _phase(progress, f"{label}: verifying checksums on Baobab")
        got = remote_hashes(conn, remote_root, [r for r, _, _ in batch])
        return [f for f in batch if got.get(f[0]) != local_hash[f[0]]]

    if todo:
        copy(todo)
        bad = verify(todo)
        if bad:
            _log(progress, f"{label}: {len(bad)} file(s) failed verification - retrying")
            copy(bad)
            bad = verify(bad)
        rep.transferred = len(todo)
        rep.mismatches = [r for r, _, _ in bad]
    return rep


def download_tree(conn: Connection, remote_root: str, local_root, *, progress=None,
                  label="Download") -> TransferReport:
    local_root = Path(local_root)
    _phase(progress, f"{label}: listing files on Baobab")
    entries = remote_file_list(conn, remote_root)
    rep = TransferReport(label, files=len(entries))
    if not entries:
        return rep
    _phase(progress, f"{label}: computing checksums on Baobab")
    hashes = remote_hashes(conn, remote_root)
    local_root.mkdir(parents=True, exist_ok=True)

    todo = []
    for rel, size in entries:
        lp = local_root / Path(*windows_safe(rel).split("/"))
        if lp.exists() and lp.stat().st_size == size and sha256_file(lp) == hashes.get(rel):
            rep.skipped += 1
        else:
            todo.append((rel, size, lp))

    pr = _Progress(progress, label, sum(s for _, s, _ in todo), len(todo))
    sftp = conn.sftp()
    try:
        for rel, size, lp in todo:
            pr.file = rel
            lp.parent.mkdir(parents=True, exist_ok=True)
            tmp = lp.with_name(lp.name + ".part")
            ok = False
            for _attempt in range(2):
                start = pr.done

                def cb(d, t, s=start):
                    pr.done = s + d
                    pr.emit()
                sftp.get(posixpath.join(remote_root, rel), str(tmp), callback=cb)
                pr.done = start + size
                if sha256_file(tmp) == hashes.get(rel):
                    os.replace(tmp, lp)
                    ok = True
                    break
                pr.done = start
            if not ok:
                tmp.unlink(missing_ok=True)
                rep.mismatches.append(rel)
            rep.bytes += size
            rep.transferred += 1
            pr.files_done += 1
            pr.emit()
    finally:
        sftp.close()
    pr.emit(force=True)
    return rep


# ── SLURM helpers ─────────────────────────────────────────────────────────────
def parse_slurm_time(s: str) -> int | None:
    """Seconds for a SLURM time string; None for unlimited. Raises ValueError if invalid."""
    s = s.strip()
    if s.lower() in ("infinite", "unlimited"):
        return None
    m = re.fullmatch(r"(?:(\d+)-)?(\d+)(?::(\d+))?(?::(\d+))?", s)
    if not m:
        raise ValueError(f"Invalid time '{s}'")
    d, a, b, c = m.groups()
    if d is not None:                        # d-h, d-h:m, d-h:m:s
        return ((int(d) * 24 + int(a)) * 60 + int(b or 0)) * 60 + int(c or 0)
    if b is None:                            # minutes
        return int(a) * 60
    if c is None:                            # minutes:seconds
        return int(a) * 60 + int(b)
    return (int(a) * 60 + int(b)) * 60 + int(c)   # h:m:s


def human_duration(sec: int | None) -> str:
    if sec is None:
        return "unlimited"
    d, r = divmod(sec, 86400)
    h, r = divmod(r, 3600)
    m = r // 60
    parts = ([f"{d} day{'s' if d > 1 else ''}"] if d else []) + ([f"{h} h"] if h else []) \
        + ([f"{m} min"] if m else [])
    return " ".join(parts) or f"{sec} s"


ARRAY_RE = re.compile(r"^\d+(-\d+(:\d+)?)?(,\d+(-\d+(:\d+)?)?)*$")


def get_partitions(conn: Connection) -> list[dict]:
    out, _, _ = conn.run("sinfo -h -s -o '%P|%l|%a|%F'", check=False)
    parts, seen = [], set()
    for line in out.splitlines():
        f = line.strip().split("|")
        if len(f) < 4:
            continue
        name = f[0].rstrip("*")
        if name in seen:
            continue
        seen.add(name)
        try:
            limit = parse_slurm_time(f[1])
        except ValueError:
            limit = None
        nodes = f[3].split("/")
        idle = int(nodes[1]) if len(nodes) == 4 and nodes[1].isdigit() else None
        parts.append({"name": name, "default": f[0].endswith("*"), "timelimit": f[1],
                      "limit_s": limit, "avail": f[2], "idle": idle, "gpu": "gpu" in name})
    return parts


def get_matlab_modules(conn: Connection) -> list[str]:
    out, _, _ = conn.run_login("module -t spider MATLAB 2>&1 || module -t avail MATLAB 2>&1",
                               check=False)
    return sorted(set(re.findall(r"\bMATLAB/[\w.\-]+", out)), reverse=True)


def get_python_versions(conn: Connection) -> list[str]:
    """Python 3 modules available on the cluster, newest first (without '-bare')."""
    out, _, _ = conn.run_login("module -t spider Python 2>&1", check=False)
    return parse_python_versions(out)


def parse_python_versions(out: str) -> list[str]:
    mods = set(re.findall(r"^\s*(Python/3\.\d+\.\d+)\s*$", out, re.M))
    key = lambda m: tuple(int(x) for x in m.split("/")[1].split("."))
    return sorted(mods, key=key, reverse=True)


def parse_spider_prereqs(module: str, out: str) -> str:
    """From 'module spider X/1.2' output, return the full load line ('GCCcore/13.3.0 X/1.2')."""
    lines = out.splitlines()
    for i, line in enumerate(lines):
        if "You will need to load all module(s)" in line:
            for nxt in lines[i + 1:]:
                if nxt.strip():
                    prereq = " ".join(nxt.split())
                    return f"{prereq} {module}"
            break
    return module


def resolve_module_load(conn: Connection, module: str) -> str:
    out, _, _ = conn.run_login(f"module spider {q(module)} 2>&1", check=False)
    return parse_spider_prereqs(module, out)


def find_requirements(project_dir, entry: str) -> Path | None:
    """The requirements.txt nearest to the script: its own folder first, then each
    parent folder up to the project folder."""
    root = Path(project_dir).resolve()
    d = (root / entry).parent.resolve()
    while True:
        f = d / "requirements.txt"
        if f.is_file():
            return f
        if d == root or root not in d.parents:
            return None
        d = d.parent


def third_party_imports(project_dir, entry: str) -> list[str]:
    """Packages a Python script imports that are neither in Python's standard library
    nor part of the project (so they must be installed, e.g. numpy)."""
    import ast
    import sys as _sys
    path = Path(project_dir) / entry
    try:
        tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
    except (OSError, SyntaxError, ValueError):
        return []
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            names.add(node.module.split(".")[0])
    std = set(getattr(_sys, "stdlib_module_names", ())) | {"__future__"}
    roots = {path.parent, Path(project_dir)}

    def local(n):
        return any((r / n).is_dir() or (r / f"{n}.py").is_file() for r in roots)
    return sorted(n for n in names if n not in std and not local(n))


def is_matlab_function(path) -> bool:
    """True if the .m file starts with 'function' (after comments/blank lines)."""
    try:
        text = Path(path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False
    in_block = False
    for line in text.splitlines():
        s = line.strip()
        if s == "%{":
            in_block = True
            continue
        if in_block:
            if s == "%}":
                in_block = False
            continue
        if not s or s.startswith("%"):
            continue
        return bool(re.match(r"function\b", s))
    return False


@dataclass
class JobSpec:
    name: str
    project_dir: str
    entry: str                     # path inside project (posix)
    partition: str
    walltime: str
    cpus: int = 1
    mem_gb: int = 3                # total memory for the job
    gpu: str = ""                  # "", "1", "titan:1", ...
    array_range: str = ""
    array_max: int = 0
    email: str = ""
    data_dir: str = ""
    results_base: str = ""         # local folder; results go to <base>/<name>_<jobid>
    matlab_module: str = "MATLAB/2022a"
    python_modules: str = "Python/3.12.3"
    cuda_module: str = "CUDA"
    continue_runs: int = 0         # >0: continue after a time-out, up to this many runs

    @property
    def language(self) -> str:
        return "matlab" if self.entry.lower().endswith(".m") else "python"

    @property
    def is_array(self) -> bool:
        return bool(self.array_range.strip())


_BAD_SHELL = re.compile(r"[\"'`$\\\n]")


def validate_spec(spec: JobSpec) -> None:
    if not spec.project_dir or not Path(spec.project_dir).is_dir():
        raise BaobabError("Select a project folder.")
    if not spec.entry or not (Path(spec.project_dir) / spec.entry).is_file():
        raise BaobabError("Select the script to run.")
    if _BAD_SHELL.search(spec.entry):
        raise BaobabError("The script path contains quotes, $ or backslashes - please rename it.")
    if spec.language == "matlab":
        fn = posixpath.splitext(posixpath.basename(spec.entry))[0]
        if not re.fullmatch(r"[A-Za-z]\w*", fn):
            raise BaobabError(f"'{fn}' is not a valid MATLAB name: it must start with a letter "
                              "and contain only letters, digits and underscores.")
    try:
        parse_slurm_time(spec.walltime)
    except ValueError:
        raise BaobabError("Wall time must look like 01:30:00 (h:m:s) or 2-00:00:00 (days-h:m:s).")
    if spec.is_array and not ARRAY_RE.match(spec.array_range.strip()):
        raise BaobabError("Array range must look like 1-100, 0-49 or 1,3,5.")
    if spec.data_dir and not Path(spec.data_dir).is_dir():
        raise BaobabError("The data folder does not exist.")
    if spec.continue_runs and spec.is_array:
        raise BaobabError("Automatic continuation is not available for job arrays.")


EXIT_CONTINUE = 3        # a script exits with this code to ask for the next run


def warning_lead(walltime: str) -> int:
    """Seconds of warning before the time limit: 10 % of the wall time, 1-10 minutes."""
    try:
        sec = parse_slurm_time(walltime) or 3600
    except ValueError:
        sec = 3600
    return max(60, min(600, sec // 10))


# Runs the program in the background so the shell can react to SLURM's warning
# signal, then decides whether the job is finished or needs another run.
_RUNNER = r"""
# --- warning before the time limit, automatic continuation ---------------------
CONTINUE={cont}
MAX_RUNS={max_runs}
LEAD={lead}
CHAIN="$BAOBAB_JOB_DIR/.baobab_chain"
DONE="$BAOBAB_JOB_DIR/.baobab_done"
next_id=""
if [ "$CONTINUE" = 1 ] && grep -qs '^cancelled' "$DONE"; then
    echo "[baobab] The job was cancelled: this run stops here"; exit 0
fi
if [ "$CONTINUE" = 1 ] && [ "$BAOBAB_RUN" = 1 ]; then echo "1 $SLURM_JOB_ID" >> "$CHAIN"; fi

queue_next() {{
    [ -n "$next_id" ] && return 0
    grep -qs '^cancelled' "$DONE" && return 1
    if [ "$BAOBAB_RUN" -ge "$MAX_RUNS" ]; then
        echo "[baobab] Run limit ($MAX_RUNS) reached: no further run"; return 1
    fi
    next_id=$(sbatch --parsable --dependency=afterany:$SLURM_JOB_ID \
              --export=ALL,BAOBAB_RUN=$((BAOBAB_RUN + 1)) "$BAOBAB_JOB_DIR/submit.sh" | cut -d';' -f1)
    if [ -n "$next_id" ]; then
        echo "$((BAOBAB_RUN + 1)) $next_id" >> "$CHAIN"
        echo "[baobab] Run $((BAOBAB_RUN + 1)) queued as job $next_id"
    else
        echo "[baobab] Could not queue the next run"; return 1
    fi
}}

on_time_up() {{
    echo "[baobab] $(date +%T) Time limit in about $LEAD s: $BAOBAB_TIME_UP created - save a checkpoint now"
    touch "$BAOBAB_TIME_UP"
    [ "$CONTINUE" = 1 ] && queue_next
}}
trap on_time_up USR1

{command} &
pid=$!
while :; do
    wait $pid; status=$?
    kill -0 $pid 2>/dev/null && continue          # interrupted by the warning: keep waiting
    wait $pid 2>/dev/null; s2=$?; [ $s2 -ne 127 ] && status=$s2
    break
done

if [ "$CONTINUE" = 1 ]; then
    if [ $status -eq 0 ]; then
        if [ -n "$next_id" ]; then
            scancel "$next_id"; echo "cancel $next_id" >> "$CHAIN"
            echo "[baobab] Finished before the limit: run $((BAOBAB_RUN + 1)) cancelled"
        fi
        echo "finished $BAOBAB_RUN" > "$DONE"
    elif [ $status -eq {code} ]; then
        if queue_next; then
            echo "[baobab] Checkpoint saved: continuing in run $((BAOBAB_RUN + 1))"
        else
            echo "limit $BAOBAB_RUN" > "$DONE"
        fi
        status=0
    else
        if [ -n "$next_id" ]; then scancel "$next_id"; echo "cancel $next_id" >> "$CHAIN"; fi
        echo "failed $BAOBAB_RUN $status" > "$DONE"
        echo "[baobab] Stopped: the script failed (exit $status)"
    fi
fi
"""


def build_sbatch(spec: JobSpec, job_dir: str, env_dir: str = "",
                 entry_is_function: bool = True) -> str:
    logpat = "%x-%A_%a" if spec.is_array else "%x-%j"
    lead = warning_lead(spec.walltime)
    L = ["#!/bin/bash",
         f"#SBATCH --job-name={spec.name}",
         f"#SBATCH --partition={spec.partition}",
         f"#SBATCH --time={spec.walltime}",
         "#SBATCH --ntasks=1",
         f"#SBATCH --cpus-per-task={spec.cpus}",
         f"#SBATCH --mem={spec.mem_gb}G",
         f"#SBATCH --output={job_dir}/logs/{logpat}.out",
         f"#SBATCH --error={job_dir}/logs/{logpat}.err"]
    if spec.is_array:
        L.append(f"#SBATCH --array={spec.array_range.strip()}"
                 + (f"%{spec.array_max}" if spec.array_max else ""))
    if spec.gpu:
        L.append(f"#SBATCH --gpus={spec.gpu}")
    if spec.email:
        L += ["#SBATCH --mail-type=END,FAIL", f"#SBATCH --mail-user={spec.email}"]
    L.append(f"#SBATCH --signal=B:USR1@{lead}")
    L += ["",
          "# Folders available to your code",
          f"export BAOBAB_JOB_DIR={q(job_dir)}",
          'export BAOBAB_CODE="$BAOBAB_JOB_DIR/code"',
          'export BAOBAB_DATA="$BAOBAB_JOB_DIR/data"',
          'export BAOBAB_RESULTS="$BAOBAB_JOB_DIR/results"',
          'export BAOBAB_CHECKPOINT_DIR="$BAOBAB_JOB_DIR/checkpoints"',
          'export BAOBAB_TIME_UP="$BAOBAB_JOB_DIR/.baobab_time_up"   # appears shortly before the limit',
          'export BAOBAB_RUN="${BAOBAB_RUN:-1}"',
          'mkdir -p "$BAOBAB_CHECKPOINT_DIR"',
          'rm -f "$BAOBAB_TIME_UP"',
          'cd "$BAOBAB_JOB_DIR"',
          "",
          'echo "Job $SLURM_JOB_ID on $(hostname), run $BAOBAB_RUN - started $(date)"',
          ""]
    if spec.language == "matlab":
        fn = posixpath.splitext(posixpath.basename(spec.entry))[0]
        entry_dir = posixpath.dirname(spec.entry).replace("'", "''")
        cmds = ["addpath(genpath(getenv('BAOBAB_CODE')))"]
        if entry_dir:   # the chosen script wins over same-named files elsewhere
            cmds.append(f"addpath(fullfile(getenv('BAOBAB_CODE'),'{entry_dir}'))")
        cmds.append("maxNumCompThreads(str2double(getenv('SLURM_CPUS_PER_TASK')))")
        if spec.is_array and entry_is_function:
            cmds.append(f"{fn}(str2double(getenv('SLURM_ARRAY_TASK_ID')))")
        else:
            cmds.append(fn)
        L.append(f"module load {spec.matlab_module}")
        command = f'srun matlab -nodisplay -nosplash -batch "{"; ".join(cmds)}"'
    else:
        L.append(f"module load {spec.python_modules}")
        if spec.gpu:
            L.append(f"module load {spec.cuda_module}")
        if env_dir:
            L.append(f"source {q(env_dir)}/bin/activate")
        L.append('export PYTHONPATH="$BAOBAB_CODE${PYTHONPATH:+:$PYTHONPATH}"')
        arg = ' "$SLURM_ARRAY_TASK_ID"' if spec.is_array else ""
        command = f'srun python -u "$BAOBAB_CODE/{spec.entry}"{arg}'
    L.append(_RUNNER.format(cont=1 if spec.continue_runs else 0,
                            max_runs=max(spec.continue_runs, 1), lead=lead,
                            command=command, code=EXIT_CONTINUE))
    L += ['echo "Finished $(date) with exit code $status"',
          "exit $status", ""]
    return "\n".join(L)


def remote_job_dir(conn: Connection, name: str) -> str:
    return (f"{conn.scratch}/baobab_jobs/{name}_{time.strftime('%Y%m%d-%H%M%S')}_"
            f"{secrets.token_hex(2)}")


def create_job_dir(conn: Connection, name: str) -> str:
    """A new, empty job folder. 'mkdir' without -p refuses an existing folder, so two
    jobs can never share one, even when submitted in the same second."""
    conn.run(f"mkdir -p {q(conn.scratch)}/baobab_jobs")
    for _ in range(5):
        d = remote_job_dir(conn, name)
        _, _, code = conn.run(f"mkdir {q(d)}", check=False)
        if code == 0:
            return d
    raise BaobabError("Could not create a job folder on Baobab.")


def remote_data_dir(conn: Connection, data_dir: str) -> str:
    """Persistent location of a dataset on scratch, reused by later jobs."""
    p = Path(data_dir).resolve()
    tag = hashlib.sha1(str(p).lower().encode()).hexdigest()[:8]
    return f"{conn.scratch}/baobab_data/{safe_name(p.name, 'data')}_{tag}"


def default_results_base(data_dir: str, project_dir: str) -> str:
    base = data_dir or project_dir
    return str(Path(base) / RESULTS_DIRNAME) if base else ""


def ensure_python_env(conn: Connection, spec: JobSpec, req_remote: str, req_text: str,
                      progress=None) -> str:
    tag = hashlib.sha256((spec.python_modules + "\n" + req_text).encode()).hexdigest()[:12]
    env = f"{conn.scratch}/baobab_envs/py_{tag}"
    out, _, _ = conn.run(f"[ -x {q(env)}/bin/python ] && echo yes || true", check=False)
    if out.strip() == "yes":
        _log(progress, "Python packages: existing environment reused")
        return env
    _phase(progress, "Installing Python packages on Baobab (first time only)...")
    cmd = (f"module load {spec.python_modules} && mkdir -p {q(posixpath.dirname(env))} && "
           f"python -m venv {q(env)} && {q(env)}/bin/pip install -q --upgrade pip && "
           f"{q(env)}/bin/pip install -q -r {q(req_remote)}")
    out, err, code = conn.run_login(cmd, timeout=None, check=False)
    if code != 0:
        conn.run(f"rm -rf {q(env)}", check=False)
        raise BaobabError("Installing Python packages failed:\n" + (err or out)[-1500:])
    _log(progress, "Python packages: environment created")
    return env


# ── Job registry (local list of submitted jobs) ───────────────────────────────
class JobRegistry:
    def __init__(self, path: Path = JOBS_FILE):
        self.path = path
        self.lock = threading.RLock()
        try:
            self.jobs: list[dict] = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            self.jobs = []

    def save(self):
        with self.lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(self.jobs, indent=2), encoding="utf-8")
            os.replace(tmp, self.path)

    def add(self, rec: dict):
        with self.lock:
            self.jobs.insert(0, rec)
            self.save()

    def get(self, job_id: str) -> dict | None:
        with self.lock:
            return next((j for j in self.jobs if j["job_id"] == job_id), None)

    def update(self, job_id: str, **kw):
        with self.lock:
            j = next((j for j in self.jobs if j["job_id"] == job_id), None)
            if j:
                j.update(kw)
            self.save()

    def remove(self, job_id: str):
        with self.lock:
            self.jobs = [j for j in self.jobs if j["job_id"] != job_id]
            self.save()


def poll_states(conn: Connection, job_ids: list[str]) -> dict[str, tuple[str, str]]:
    """Return {job_id: (STATE, detail)} for the given (array) job ids."""
    if not job_ids:
        return {}
    res = {}
    out, _, _ = conn.run("squeue -h -u $USER -o '%F|%T|%M'", check=False)
    active: dict[str, Counter] = {}
    elapsed: dict[str, str] = {}
    for line in out.splitlines():
        f = line.strip().split("|")
        if len(f) >= 3:
            active.setdefault(f[0], Counter())[f[1]] += 1
            elapsed[f[0]] = f[2]
    for jid in job_ids:
        c = active.get(jid)
        if c:
            state = "RUNNING" if c.get("RUNNING") else c.most_common(1)[0][0]
            if sum(c.values()) > 1:
                detail = ", ".join(f"{n} {s.lower()}" for s, n in c.most_common())
            else:
                detail = f"elapsed {elapsed.get(jid, '')}" if state == "RUNNING" else ""
            res[jid] = (state, detail)
    rest = [j for j in job_ids if j not in res]
    if rest:
        out, _, _ = conn.run("sacct -n -X -P -o JobID,State,ExitCode,Elapsed -j "
                             + ",".join(rest), check=False)
        per: dict[str, Counter] = {}
        info: dict[str, tuple[str, str]] = {}
        for line in out.splitlines():
            f = line.strip().split("|")
            if len(f) < 4:
                continue
            base = f[0].split("_")[0].split(".")[0]
            st = f[1].split()[0] if f[1] else "UNKNOWN"
            per.setdefault(base, Counter())[st] += 1
            info[base] = (f[2], f[3])
        for jid in rest:
            c = per.get(jid)
            if not c:
                res[jid] = ("UNKNOWN", "not found in SLURM accounting")
                continue
            nonfinal = [s for s in c if s not in FINAL_STATES]
            if nonfinal:
                state = "RUNNING" if "RUNNING" in nonfinal else nonfinal[0]
            else:
                state = next((s for s in STATE_SEVERITY if s in c), "UNKNOWN")
            if sum(c.values()) > 1:
                detail = ", ".join(f"{n} {s.lower()}" for s, n in c.most_common())
            else:
                code, el = info[jid]
                detail = f"exit {code}, ran {el}"
            res[jid] = (state, detail)
    return res


def tail_log(conn: Connection, job_dir: str, n: int = 200) -> str:
    d = q(job_dir)
    cmd = (f'f=$(ls -t {d}/logs/*.out 2>/dev/null | head -1); '
           f'[ -n "$f" ] && {{ echo "== $(basename "$f")"; tail -n {n} "$f"; }}; '
           f'e=$(ls -t {d}/logs/*.err 2>/dev/null | head -1); '
           f'[ -s "$e" ] && {{ echo; echo "== $(basename "$e")  (errors)"; tail -n 60 "$e"; }}; true')
    out, _, _ = conn.run(cmd, check=False)
    return out.strip() or "(no log yet - the job has probably not started)"


def read_chain(conn: Connection, job_dir: str) -> dict:
    """Runs of a continuing job: {'ids': [job ids in order], 'done': marker or None}."""
    d = q(job_dir)
    out, _, _ = conn.run(f"cat {d}/.baobab_chain 2>/dev/null; echo '##'; "
                         f"cat {d}/.baobab_done 2>/dev/null", check=False)
    chain, _, done = out.partition("##")
    ids, cancelled = [], set()
    for line in chain.splitlines():
        f = line.split()
        if len(f) == 2 and f[0] == "cancel":
            cancelled.add(f[1])
        elif len(f) == 2 and f[0].isdigit():
            ids.append(f[1])
    return {"ids": [i for i in ids if i not in cancelled], "done": done.strip() or None}


def poll_jobs(conn: Connection, recs: list[dict]) -> dict[str, dict]:
    """State of each job; continuing jobs are followed from run to run."""
    cur = {r["job_id"]: r.get("current_id") or r["job_id"] for r in recs}
    states = poll_states(conn, sorted(set(cur.values())))
    updates = {}
    for r in recs:
        jid, cid = r["job_id"], cur[r["job_id"]]
        state, detail = states.get(cid, ("UNKNOWN", ""))
        if not r.get("continue_runs"):
            updates[jid] = {"state": state, "detail": detail}
            continue
        chain = read_chain(conn, r["job_dir"])
        ids = chain["ids"] or [jid]
        while state in FINAL_STATES and not chain["done"] and cid in ids \
                and ids.index(cid) < len(ids) - 1:
            cid = ids[ids.index(cid) + 1]                 # follow to the next run
            state, detail = poll_states(conn, [cid]).get(cid, ("PENDING", ""))
        run = ids.index(cid) + 1 if cid in ids else len(ids)
        up = {"current_id": cid, "run": run, "chain_ids": ids}
        done = (chain["done"] or "").split()
        if state in FINAL_STATES:
            if done[:1] == ["finished"]:
                state, detail = "COMPLETED", f"finished in {run} run(s)"
            elif done[:1] == ["failed"]:
                state = "FAILED"
                detail = f"run {run} failed (exit {done[2] if len(done) > 2 else '?'})"
            elif done[:1] == ["limit"]:
                state, detail = "TIMEOUT", f"stopped at the limit of {run} runs"
            elif done[:1] == ["cancelled"]:
                state, detail = "CANCELLED", f"cancelled during run {run}"
            elif state == "TIMEOUT":
                detail = f"time limit reached in run {run}, no further run queued"
        else:
            detail = f"run {run} of at most {r['continue_runs']}" + (f" - {detail}" if detail else "")
        up.update(state=state, detail=detail)
        updates[jid] = up
    return updates


def cancel_job(conn: Connection, job_id: str, rec: dict | None = None):
    """Cancel a job; for a continuing job, also its queued next run."""
    ids = {job_id}
    if rec and rec.get("continue_runs"):
        ids |= set(read_chain(conn, rec["job_dir"])["ids"]) | {rec.get("current_id") or job_id}
        conn.run(f"echo cancelled > {q(rec['job_dir'])}/.baobab_done", check=False)
    conn.run("scancel " + " ".join(q(i) for i in sorted(ids)))


# ── High-level operations ─────────────────────────────────────────────────────
def submit_job(conn: Connection, spec: JobSpec, cache: HashCache, progress=None) -> dict:
    validate_spec(spec)
    project = Path(spec.project_dir)
    job_dir = create_job_dir(conn, spec.name)
    _log(progress, f"Job folder on Baobab: {job_dir}")
    conn.run(f"mkdir -p {q(job_dir)}/code {q(job_dir)}/results {q(job_dir)}/logs")

    # 1. code
    rep = upload_tree(conn, project, f"{job_dir}/code", kind="code", cache=cache,
                      progress=progress, label="Code")
    _log(progress, rep.summary())
    if not rep.ok:
        raise BaobabError("Code upload could not be verified - job not submitted.")

    # 2. Python packages
    env_dir = ""
    req = find_requirements(project, spec.entry) if spec.language == "python" else None
    if req:
        rel = req.relative_to(project.resolve()).as_posix()
        _log(progress, f"Python packages from {rel}")
        env_dir = ensure_python_env(conn, spec, f"{job_dir}/code/{rel}",
                                    req.read_text(encoding="utf-8", errors="replace"), progress)

    # 3. data (persistent copy on scratch, unchanged files skipped)
    data_remote = ""
    if spec.data_dir:
        data_remote = remote_data_dir(conn, spec.data_dir)
        rep = upload_tree(conn, spec.data_dir, data_remote, kind="data", skip_unchanged=True,
                          cache=cache, progress=progress, label="Data")
        _log(progress, rep.summary())
        if not rep.ok:
            raise BaobabError("Data upload could not be verified - job not submitted.")
        conn.run(f"ln -sfn {q(data_remote)} {q(job_dir)}/data")
    else:
        conn.run(f"mkdir -p {q(job_dir)}/data")

    # 4. sbatch script + submission
    _phase(progress, "Submitting to SLURM...")
    is_fn = spec.language != "matlab" or is_matlab_function(project / spec.entry)
    script = build_sbatch(spec, job_dir, env_dir, is_fn)
    sftp = conn.sftp()
    try:
        with sftp.open(f"{job_dir}/submit.sh", "w") as f:
            f.write(script)
    finally:
        sftp.close()
    out, _, _ = conn.run(f"cd {q(job_dir)} && sbatch --parsable submit.sh")
    job_id = out.strip().split(";")[0]
    if not job_id.isdigit():
        raise BaobabError(f"Unexpected answer from sbatch: {out.strip()}")

    results_base = spec.results_base or default_results_base(spec.data_dir, spec.project_dir)
    rec = {"job_id": job_id, "name": spec.name, "job_dir": job_dir,
           "data_remote": data_remote, "entry": spec.entry, "partition": spec.partition,
           "project_dir": spec.project_dir, "cpus": spec.cpus, "mem_gb": spec.mem_gb,
           "walltime": spec.walltime, "continue_runs": spec.continue_runs,
           "current_id": job_id, "run": 1, "chain_ids": [job_id],
           "is_array": spec.is_array,
           "results_local": str(Path(results_base) / f"{spec.name}_{job_id}"),
           "submitted": time.strftime("%Y-%m-%d %H:%M"), "state": "PENDING",
           "detail": "", "downloaded": False, "download_note": ""}
    _log(progress, f"Submitted - job id {job_id}")
    return rec


def download_job(conn: Connection, rec: dict, progress=None) -> list[TransferReport]:
    local = Path(rec["results_local"])
    reps = [download_tree(conn, f"{rec['job_dir']}/results", local, progress=progress,
                          label="Results"),
            download_tree(conn, f"{rec['job_dir']}/logs", local / "_logs", progress=progress,
                          label="Logs")]
    (local / "_logs").mkdir(parents=True, exist_ok=True)
    sftp = conn.sftp()
    try:
        sftp.get(f"{rec['job_dir']}/submit.sh", str(local / "_logs" / "submit.sh"))
    except OSError:
        pass
    finally:
        sftp.close()
    info = {k: rec.get(k) for k in ("job_id", "name", "entry", "partition", "submitted",
                                    "state", "detail", "job_dir")}
    (local / "_logs" / "job_info.json").write_text(json.dumps(info, indent=2), encoding="utf-8")
    for r in reps:
        _log(progress, r.summary())
    return reps


# ── Cluster availability ──────────────────────────────────────────────────────
_KV = re.compile(r"(\w+)=(\S*)")
_UNUSABLE = ("DOWN", "DRAIN", "FAIL", "MAINT", "RESERVED", "NOT_RESPONDING", "POWER",
             "INVAL", "UNKNOWN", "REBOOT", "FUTURE")


def parse_scontrol(text: str) -> list[dict]:
    """'scontrol show ... -o' output: one record per line, Key=Value pairs."""
    return [dict(_KV.findall(line)) for line in text.splitlines() if "=" in line]


def _tres(s: str) -> dict:
    """'cpu=4,mem=12000M,gres/gpu=3,gres/gpu:titan=3' -> {'cpu': '4', ...}"""
    out = {}
    for part in (s or "").split(","):
        k, _, v = part.partition("=")
        if k:
            out[k] = v
    return out


def _mem_mb(v: str) -> int:
    m = re.fullmatch(r"([\d.]+)([KMGT]?)", v or "")
    if not m:
        return 0
    return int(float(m.group(1)) * {"": 1, "K": 1 / 1024, "M": 1, "G": 1024, "T": 1024 ** 2}[m.group(2)])


def parse_gpu_request(gpu: str) -> tuple[str, int]:
    """'' -> ('', 0); '1' -> ('', 1); 'titan:2' -> ('titan', 2)"""
    if not gpu:
        return "", 0
    if ":" in gpu:
        t, _, n = gpu.partition(":")
        return t, int(n or 1)
    return "", int(gpu)


def summarize_cluster(nodes_txt: str, parts_txt: str, queue_txt: str,
                      groups: set[str] | None = None, accounts: set[str] | None = None) -> list[dict]:
    """Per-partition availability, only for partitions this user may use."""
    nodes = []
    for r in parse_scontrol(nodes_txt):
        if "NodeName" not in r:
            continue
        state = r.get("State", "UNKNOWN").upper()
        cpus = int(r.get("CPUEfctv") or r.get("CPUTot") or 0)
        mem = int(r.get("RealMemory") or 0)
        alloc = _tres(r.get("AllocTRES", ""))
        cfg = _tres(r.get("CfgTRES", ""))
        gpus_total, gpus_used = {}, {}
        for k, v in cfg.items():
            if k.startswith("gres/gpu:") and v.isdigit():
                gpus_total[k.split(":", 1)[1]] = int(v)
        if not gpus_total and cfg.get("gres/gpu", "").isdigit():
            gpus_total["gpu"] = int(cfg["gres/gpu"])
        for k, v in alloc.items():
            if k.startswith("gres/gpu:") and v.isdigit():
                gpus_used[k.split(":", 1)[1]] = int(v)
        if not gpus_used and alloc.get("gres/gpu", "").isdigit() and len(gpus_total) == 1:
            gpus_used[next(iter(gpus_total))] = int(alloc["gres/gpu"])
        usable = not any(w in state for w in _UNUSABLE)
        nodes.append({
            "name": r["NodeName"], "state": state, "usable": usable,
            "partitions": set(filter(None, r.get("Partitions", "").split(","))),
            "cpus": cpus, "free_cpus": max(cpus - int(r.get("CPUAlloc") or 0), 0) if usable else 0,
            "mem_mb": mem,
            "free_mem_mb": max(mem - int(r.get("AllocMem") or 0), 0) if usable else 0,
            "gpus_total": gpus_total,
            "gpus_free": {t: max(n - gpus_used.get(t, 0), 0) if usable else 0
                          for t, n in gpus_total.items()},
            "idle": usable and state.startswith("IDLE"),
        })

    waiting, running = Counter(), Counter()
    for line in queue_txt.splitlines():
        f = line.strip().split("|")
        if len(f) >= 2:
            for p in f[0].split(","):
                (running if f[1] == "RUNNING" else waiting if f[1] == "PENDING" else Counter())[p] += 1

    groups = groups or set()
    accounts = accounts or set()
    out = []
    for r in parse_scontrol(parts_txt):
        name = r.get("PartitionName")
        if not name or r.get("Hidden") == "YES":
            continue
        ag = set(r.get("AllowGroups", "ALL").split(","))
        aa = set(r.get("AllowAccounts", "ALL").split(","))
        if ("ALL" not in ag and not ag & groups) or ("ALL" not in aa and not aa & accounts):
            continue                                   # not allowed for this user
        pn = [n for n in nodes if name in n["partitions"]]
        try:
            limit = parse_slurm_time(r.get("MaxTime", "UNLIMITED"))
        except ValueError:
            limit = None
        gpu_free, gpu_total = Counter(), Counter()
        for n in pn:
            for t, k in n["gpus_total"].items():
                gpu_total[t] += k
                gpu_free[t] += n["gpus_free"][t]
        kind = ("debug" if name.startswith("debug") else "private" if name.startswith("private")
                else "shared" if name.startswith("shared") else "public" if name.startswith("public")
                else "other")
        out.append({
            "name": name, "kind": kind, "default": r.get("Default") == "YES",
            "up": r.get("State", "UP") == "UP", "timelimit": r.get("MaxTime", ""),
            "limit_s": limit, "nodes": pn,
            "nodes_total": len(pn), "nodes_usable": sum(n["usable"] for n in pn),
            "nodes_idle": sum(n["idle"] for n in pn),
            "cpus_total": sum(n["cpus"] for n in pn),
            "cpus_free": sum(n["free_cpus"] for n in pn),
            "max_node_cpus": max((n["cpus"] for n in pn if n["usable"]), default=0),
            "max_node_mem_gb": max((n["mem_mb"] for n in pn if n["usable"]), default=0) // 1024,
            "gpu_total": dict(gpu_total), "gpu_free": dict(gpu_free),
            "gpu": bool(gpu_total) or "gpu" in name,
            "waiting": waiting[name], "running": running[name],
        })
    order = {"debug": 0, "shared": 1, "public": 2, "private": 3, "other": 4}

    def flavour(name):          # cpu, then gpu, then big memory, then long runs
        return (2 if "bigmem" in name else 1 if "gpu" in name else 3 if "longrun" in name
                else 0)
    out.sort(key=lambda p: (order[p["kind"]], flavour(p["name"]), p["name"]))
    return out


def check_fit(part: dict, walltime_s: int | None, cpus: int, mem_gb: int,
              gpu: str) -> tuple[str, str]:
    """('now' | 'wait' | 'never', reason) for a request on a partition."""
    if not part["up"]:
        return "never", "partition is down"
    if part["limit_s"] and walltime_s and walltime_s > part["limit_s"]:
        return "never", f"wall time over the {human_duration(part['limit_s'])} limit"
    gtype, gn = parse_gpu_request(gpu)
    if gn and not part["gpu_total"]:
        return "never", "no GPUs in this partition"
    need_mem = mem_gb * 1024

    def gpu_ok(counts):
        if not gn:
            return True
        if gtype:
            return counts.get(gtype, 0) >= gn
        return any(v >= gn for v in counts.values())

    possible = [n for n in part["nodes"]
                if n["usable"] and n["cpus"] >= cpus and n["mem_mb"] >= need_mem
                and gpu_ok(n["gpus_total"])]
    if not possible:
        what = f"{cpus} CPUs and {mem_gb} GB" + (f" with {gpu} GPU" if gn else "")
        return "never", f"no node offers {what}"
    if any(n["free_cpus"] >= cpus and n["free_mem_mb"] >= need_mem and gpu_ok(n["gpus_free"])
           for n in possible):
        return "now", "resources free now"
    return "wait", "resources busy - the job will queue"


def get_cluster_status(conn: Connection) -> list[dict]:
    nodes, _, _ = conn.run("scontrol show node -o", check=False)
    parts, _, _ = conn.run("scontrol show partition -o", check=False)
    queue, _, _ = conn.run("squeue -h -o '%P|%T'", timeout=120, check=False)
    ident, _, _ = conn.run("id -Gn; echo '##'; "
                           "sacctmgr -nP show assoc user=$USER format=account 2>/dev/null",
                           check=False)
    g, _, a = ident.partition("##")
    return summarize_cluster(nodes, parts, queue, set(g.split()), set(a.split()))


def estimate_start(conn: Connection, spec: "JobSpec") -> dict:
    """Ask SLURM when this request would start, without submitting anything."""
    cmd = (f"date +%s; sbatch --test-only -p {q(spec.partition)} -t {q(spec.walltime)} -n 1 "
           f"-c {int(spec.cpus)} --mem={int(spec.mem_gb)}G"
           + (f" --gpus={q(spec.gpu)}" if spec.gpu else "") + " --wrap=hostname 2>&1")
    out, _, _ = conn.run(cmd, check=False)
    lines = out.strip().splitlines()
    now = int(lines[0]) if lines and lines[0].isdigit() else None
    text = "\n".join(lines[1:])
    m = re.search(r"to start at (\S+) using \d+ processors on nodes (\S+)", text)
    if not m:
        msg = re.sub(r"^sbatch: (error: )?", "", text.strip(), flags=re.M) or "no answer from SLURM"
        raise BaobabError(msg)
    start_s, nodes = m.group(1), m.group(2)
    wait = None
    if now:
        out2, _, _ = conn.run(f"date -d {q(start_s)} +%s", check=False)
        if out2.strip().isdigit():
            wait = max(int(out2.strip()) - now, 0)
    return {"start": start_s.replace("T", " "), "wait_s": wait, "nodes": nodes}


# ── What a finished job really used ───────────────────────────────────────────
def _hms(t: str) -> float:
    """sacct durations: [DD-][HH:]MM:SS[.mmm] -> seconds"""
    t = t.strip()
    if not t:
        return 0.0
    days = 0
    if "-" in t:
        d, t = t.split("-", 1)
        days = int(d)
    parts = [float(x) for x in t.split(":")]
    while len(parts) < 3:
        parts.insert(0, 0.0)
    h, m, sec = parts[-3:]
    return days * 86400 + h * 3600 + m * 60 + sec


def parse_usage(out: str) -> dict | None:
    """sacct -P -n -o JobID,AllocCPUS,Elapsed,TotalCPU,MaxRSS,State --units=M"""
    tasks: dict[str, dict] = {}
    for line in out.splitlines():
        f = line.strip().split("|")
        if len(f) < 5:
            continue
        jid, cpus, el, tot, rss = f[:5]
        task = jid.split(".")[0]                # 123 or 123_4 ; steps 123.batch, 123_4.0
        t = tasks.setdefault(task, {"cpus": 0, "elapsed": 0.0, "cpu_s": 0.0, "rss_mb": 0.0})
        if "." not in jid:                      # allocation line: CPUs, wall clock, CPU time
            t["cpus"] = int(cpus) if cpus.isdigit() else t["cpus"]
            t["elapsed"] = _hms(el)
            t["cpu_s"] = _hms(tot)
        m = re.fullmatch(r"([\d.]+)([KMGT]?)", rss.strip())
        if m:
            mb = float(m.group(1)) * {"": 1 / 1024 ** 2, "K": 1 / 1024, "M": 1, "G": 1024,
                                       "T": 1024 ** 2}[m.group(2)]
            t["rss_mb"] = max(t["rss_mb"], mb)
    tasks = {k: v for k, v in tasks.items() if v["elapsed"] > 0}
    if not tasks:
        return None
    cpus = max(v["cpus"] for v in tasks.values()) or 1
    eff = [v["cpu_s"] / (v["elapsed"] * max(v["cpus"], 1)) for v in tasks.values()]
    return {"cpus": cpus, "peak_mem_gb": round(max(v["rss_mb"] for v in tasks.values()) / 1024, 2),
            "cpu_eff": round(min(max(sum(eff) / len(eff), 0.0), 1.0), 2),
            "elapsed_s": int(max(v["elapsed"] for v in tasks.values())), "tasks": len(tasks)}


def job_usage(conn: Connection, job_id: str) -> dict | None:
    out, _, _ = conn.run(f"sacct -P -n -j {q(job_id)} --units=M "
                         "-o JobID,AllocCPUS,Elapsed,TotalCPU,MaxRSS,State", check=False)
    return parse_usage(out)


def suggest_resources(usage: dict) -> dict:
    """Settings for the next run: CPUs that were really busy, memory = peak + 30 % margin."""
    cpus = usage["cpus"]
    busy = max(1, round(cpus * usage["cpu_eff"] + 0.3))
    s_cpus = cpus if usage["cpu_eff"] >= 0.7 else min(cpus, busy)
    s_mem = max(1, int(-(-usage["peak_mem_gb"] * 1.3 // 1)))          # ceil
    s_time = max(300, int(usage["elapsed_s"] * 1.5))
    return {"cpus": s_cpus, "mem_gb": s_mem, "walltime_s": s_time}


def format_walltime(sec: int) -> str:
    d, r = divmod(int(sec), 86400)
    h, r = divmod(r, 3600)
    m = -(-r // 60)                            # round minutes up
    if m == 60:
        h, m = h + 1, 0
    return f"{d}-{h:02d}:{m:02d}:00" if d else f"{h:02d}:{m:02d}:00"
