"""
Baobab HPC — desktop app (PySide6).

Submit MATLAB / Python jobs to the UNIGE Baobab cluster, with checksummed
transfers of code, data and results. Start it with Baobab_Launcher.bat.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

# A Qt path set by another program (Anaconda, QGIS, ...) makes PySide6 look for
# its plugins in the wrong place and quit silently. Ignore such settings.
for _var in ("QT_PLUGIN_PATH", "QT_QPA_PLATFORM_PLUGIN_PATH"):
    os.environ.pop(_var, None)

_APP_DIR = Path.home() / ".baobab_hpc"
_APP_DIR.mkdir(parents=True, exist_ok=True)
import faulthandler                                    # noqa: E402
_crash_file = open(_APP_DIR / "crash.log", "a", encoding="utf-8")
faulthandler.enable(_crash_file)                       # records hard crashes


def native_error_box(text: str):
    """Show an error even when Qt itself cannot start (the app has no console)."""
    try:
        _crash_file.write(text + "\n")
        _crash_file.flush()
    except Exception:
        pass
    if os.name == "nt":
        import ctypes
        ctypes.windll.user32.MessageBoxW(None, text[-3000:], "Baobab HPC - error", 0x10)
    else:
        print(text, file=sys.stderr)


import logging                                         # noqa: E402
import logging.handlers                                # noqa: E402
import time                                            # noqa: E402
import traceback                                       # noqa: E402

from PySide6.QtCore import (QLockFile, QObject, QPointF, QRunnable, QSize, QThreadPool, QTime,  # noqa: E402
                            QTimer, QUrl, Qt, QtMsgType, Signal, qInstallMessageHandler)
from PySide6.QtGui import (QColor, QDesktopServices, QFont, QFontDatabase, QIcon, QPainter,  # noqa: E402
                           QPen, QPixmap)
from PySide6.QtWidgets import (  # noqa: E402
    QAbstractItemView, QApplication, QButtonGroup, QCheckBox, QComboBox, QDialog,
    QDialogButtonBox, QFileDialog, QFormLayout, QFrame, QGraphicsDropShadowEffect,
    QGridLayout, QHBoxLayout, QHeaderView, QInputDialog, QLabel, QLineEdit, QMainWindow,
    QMessageBox, QPlainTextEdit, QProgressBar, QPushButton, QScrollArea, QSizePolicy,
    QListWidget, QListWidgetItem, QSpinBox, QStackedWidget, QTableWidget, QTableWidgetItem,
    QVBoxLayout, QWidget)

import baobab_core as core  # noqa: E402

APP_TITLE = "Baobab HPC"
APP_DIR_CODE = Path(__file__).resolve().parent
ICON_FILE = APP_DIR_CODE / "baobab.ico"
POLL_MS = 60_000
STATUS_MS = 120_000
log = logging.getLogger("baobab")

# ── Look ──────────────────────────────────────────────────────────────────────
C = {"bg": "#f4f6fb", "card": "#ffffff", "line": "#e3e8f0", "field": "#d6dce6",
     "text": "#1f2937", "muted": "#6b7280", "accent": "#3b6fe0", "accent_soft": "#e8efff",
     "ok": "#15803d", "ok_soft": "#e6f6ec", "warn": "#b45309", "warn_soft": "#fff4e0",
     "err": "#c62828", "err_soft": "#fdecec", "grey_soft": "#eef1f6"}

STYLE = f"""
QMainWindow, QWidget#page, QScrollArea, QScrollArea > QWidget > QWidget#pagebody {{
    background: {C['bg']}; }}
QWidget {{ color: {C['text']}; font-size: 10pt; }}
QFrame#sidebar {{ background: {C['card']}; border-right: 1px solid {C['line']}; }}
QLabel#brand {{ font-size: 13pt; font-weight: 700; }}
QLabel#brandsub {{ color: {C['muted']}; font-size: 8.5pt; }}
QPushButton#nav {{ text-align: left; padding: 9px 14px; border: none; border-radius: 8px;
                   background: transparent; color: {C['text']}; font-size: 10.5pt; }}
QPushButton#nav:hover {{ background: {C['grey_soft']}; }}
QPushButton#nav:checked {{ background: {C['accent_soft']}; color: {C['accent']}; font-weight: 600; }}
QLabel#pill {{ border-radius: 12px; padding: 5px 10px; font-size: 9pt; }}
QLabel#h1 {{ font-size: 17pt; font-weight: 700; }}
QLabel#sub {{ color: {C['muted']}; font-size: 10pt; }}
QFrame#card {{ background: {C['card']}; border: 1px solid {C['line']}; border-radius: 12px; }}
QLabel#cardtitle {{ font-size: 11.5pt; font-weight: 600; }}
QLabel#cardnum {{ background: {C['accent_soft']}; color: {C['accent']}; border-radius: 11px;
                  font-weight: 700; min-width: 22px; max-width: 22px; min-height: 22px;
                  max-height: 22px; qproperty-alignment: AlignCenter; }}
QLabel#hint {{ color: {C['muted']}; }}
QLabel#warn {{ color: {C['err']}; }}
QLabel#ok {{ color: {C['ok']}; }}
QLineEdit, QComboBox, QSpinBox, QPlainTextEdit {{
    background: white; border: 1px solid {C['field']}; border-radius: 8px; padding: 5px 9px;
    selection-background-color: {C['accent']}; }}
QLineEdit:focus, QComboBox:focus, QSpinBox:focus {{ border: 1px solid {C['accent']}; }}
QLineEdit:read-only {{ background: {C['bg']}; }}
QLineEdit:disabled, QComboBox:disabled, QSpinBox:disabled {{ color: #a0a7b4; background: {C['bg']}; }}
QComboBox::drop-down {{ border: none; width: 22px; }}
QPushButton {{ background: white; border: 1px solid {C['field']}; border-radius: 8px;
               padding: 6px 14px; }}
QPushButton:hover {{ background: {C['grey_soft']}; }}
QPushButton:disabled {{ color: #a0a7b4; }}
QPushButton#primary {{ background: {C['accent']}; color: white; border: none; font-weight: 600;
                       padding: 8px 22px; }}
QPushButton#primary:hover {{ background: #3160cc; }}
QPushButton#primary:disabled {{ background: #a9bde9; }}
QPushButton#link {{ border: none; background: transparent; color: {C['accent']}; padding: 2px 4px; }}
QPushButton#link:hover {{ text-decoration: underline; }}
QProgressBar {{ background: {C['grey_soft']}; border: none; border-radius: 5px; height: 10px;
                text-align: center; font-size: 8pt; }}
QProgressBar::chunk {{ background: {C['accent']}; border-radius: 5px; }}
QTableWidget {{ background: white; border: none; gridline-color: {C['line']};
                selection-background-color: {C['accent_soft']}; selection-color: {C['text']}; }}
QHeaderView::section {{ background: white; border: none; border-bottom: 1px solid {C['line']};
                        padding: 6px; color: {C['muted']}; font-weight: 600; }}
QFrame#tile {{ background: white; border: 1px solid {C['line']}; border-radius: 10px; }}
QFrame#tile:hover {{ border: 1px solid #b9c6de; }}
QFrame#tile[selected="true"] {{ border: 2px solid {C['accent']}; background: #f7f9ff; }}
QLabel#tilename {{ font-weight: 700; font-size: 10.5pt; }}
QLabel#badge {{ border-radius: 9px; padding: 2px 8px; font-size: 8.5pt; font-weight: 600; }}
QCheckBox {{ spacing: 8px; }}
"""

def _arrow_png(path: Path, up: bool, color: str):
    pm = QPixmap(20, 12)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    pen = QPen(QColor(color))
    pen.setWidthF(2.2)
    pen.setCapStyle(Qt.RoundCap)
    pen.setJoinStyle(Qt.RoundJoin)
    p.setPen(pen)
    ys = (9, 3, 9) if up else (3, 9, 3)
    p.drawPolyline([QPointF(4, ys[0]), QPointF(10, ys[1]), QPointF(16, ys[2])])
    p.end()
    pm.save(str(path))


def build_style() -> str:
    """Full style sheet, with arrow images drawn for combo and spin boxes
    (styled boxes lose their native arrows). Needs a QApplication."""
    d = core.APP_DIR / "ui"
    d.mkdir(parents=True, exist_ok=True)
    files = {"down": (False, C["muted"]), "up": (True, C["muted"]),
             "down_off": (False, "#c3c9d4"), "up_off": (True, "#c3c9d4")}
    url = {}
    for name, (up, col) in files.items():
        f = d / f"{name}.png"
        _arrow_png(f, up, col)
        url[name] = f.as_posix()
    return STYLE + f"""
QComboBox {{ padding-right: 26px; }}
QComboBox::drop-down {{ subcontrol-origin: padding; subcontrol-position: center right;
                        width: 26px; border: none; }}
QComboBox::down-arrow {{ image: url("{url['down']}"); width: 10px; height: 6px; }}
QComboBox::down-arrow:disabled {{ image: url("{url['down_off']}"); }}
QSpinBox {{ padding-right: 26px; }}
QSpinBox::up-button, QSpinBox::down-button {{ subcontrol-origin: border; width: 24px;
    border: none; border-left: 1px solid {C['line']}; background: transparent; }}
QSpinBox::up-button {{ subcontrol-position: top right; border-top-right-radius: 8px; }}
QSpinBox::down-button {{ subcontrol-position: bottom right; border-bottom-right-radius: 8px; }}
QSpinBox::up-button:hover, QSpinBox::down-button:hover {{ background: {C['grey_soft']}; }}
QSpinBox::up-arrow {{ image: url("{url['up']}"); width: 9px; height: 6px; }}
QSpinBox::down-arrow {{ image: url("{url['down']}"); width: 9px; height: 6px; }}
QSpinBox::up-arrow:disabled {{ image: url("{url['up_off']}"); }}
QSpinBox::down-arrow:disabled {{ image: url("{url['down_off']}"); }}
"""


BADGES = {"now": ("Can start now", C["ok"], C["ok_soft"]),
          "wait": ("Will queue", C["warn"], C["warn_soft"]),
          "never": ("Not possible", C["err"], C["err_soft"]),
          "unknown": ("", C["muted"], C["grey_soft"])}
STATE_COLORS = {"STAGING": C["accent_soft"], "UPLOADING": C["accent_soft"], "RUNNING": C["ok_soft"], "PENDING": C["warn_soft"], "COMPLETED": C["grey_soft"],
                "FAILED": C["err_soft"], "TIMEOUT": C["err_soft"], "OUT_OF_MEMORY": C["err_soft"],
                "CANCELLED": "#f3e8fb", "NODE_FAIL": C["err_soft"], "UNKNOWN": C["grey_soft"]}
GPU_LABELS = {"ampere": "Ampere - multipurpose", "titan": "Titan - single precision / ML",
              "pascal": "Pascal - double precision", "rtx": "RTX - ML"}


def mono_font() -> QFont:
    f = QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont)
    f.setPointSize(max(f.pointSize(), 9))
    return f


def label(text="", kind="hint", wrap=True) -> QLabel:
    lab = QLabel(text)
    lab.setObjectName(kind)
    lab.setWordWrap(wrap)
    lab.setTextInteractionFlags(Qt.TextSelectableByMouse)
    sp = QSizePolicy(QSizePolicy.Preferred, QSizePolicy.Minimum)
    sp.setHeightForWidth(True)            # wrapped text gets the height it needs
    lab.setSizePolicy(sp)
    return lab


hint = label


def relayout(w: QWidget):
    """Make the layouts above w take a new text height into account (needed when a
    wrapped label changes after the window was laid out)."""
    if isinstance(w, QLabel) and w.wordWrap() and w.width() > 50:
        w.setMinimumHeight(w.heightForWidth(w.width()))     # room for every wrapped line
    while w is not None:
        w.updateGeometry()
        if w.layout() is not None:
            w.layout().invalidate()
        w = w.parentWidget()


def set_kind(w: QWidget, kind: str):
    w.setObjectName(kind)
    w.style().unpolish(w)
    w.style().polish(w)


def set_badge(lab: QLabel, kind: str, text: str | None = None):
    t, fg, bg = BADGES[kind]
    lab.setText(text if text is not None else t)
    lab.setStyleSheet(f"color:{fg}; background:{bg}; border-radius: 8px; padding: 0px 9px;"
                      " font-size: 8.5pt; font-weight: 600;")
    lab.setVisible(bool(lab.text()))


def row(*widgets, stretch_first=True) -> QHBoxLayout:
    lay = QHBoxLayout()
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(8)
    for i, w in enumerate(widgets):
        lay.addWidget(w, 1 if (i == 0 and stretch_first) else 0)
    return lay


def stack(top, below: QLabel) -> QWidget:
    w = QWidget()
    v = QVBoxLayout(w)
    v.setContentsMargins(0, 0, 0, 2)
    v.setSpacing(3)
    v.addWidget(top) if isinstance(top, QWidget) else v.addLayout(top)
    v.addWidget(below)
    return w


def error_text(e: BaseException) -> str:
    if isinstance(e, core.BaobabError):
        return str(e)
    return f"{type(e).__name__}: {e}\n\nDetails are in {core.LOG_FILE}"


def fmt_int(n: int) -> str:
    return f"{n:,}".replace(",", "\u2009")


class Card(QFrame):
    """White rounded card with an optional step number, title and subtitle."""

    def __init__(self, title: str, subtitle: str = "", number: str = ""):
        super().__init__()
        self.setObjectName("card")
        sh = QGraphicsDropShadowEffect(self)
        sh.setBlurRadius(18)
        sh.setOffset(0, 2)
        sh.setColor(QColor(15, 23, 42, 18))
        self.setGraphicsEffect(sh)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(20, 16, 20, 18)
        outer.setSpacing(10)
        head = QHBoxLayout()
        head.setSpacing(10)
        if number:
            n = QLabel(number)
            n.setObjectName("cardnum")
            head.addWidget(n)
        t = QLabel(title)
        t.setObjectName("cardtitle")
        head.addWidget(t)
        head.addStretch(1)
        self.head = head
        outer.addLayout(head)
        if subtitle:
            outer.addWidget(label(subtitle))
        self.body = QVBoxLayout()
        self.body.setSpacing(8)
        outer.addLayout(self.body)

    def add(self, w):
        self.body.addWidget(w) if isinstance(w, QWidget) else self.body.addLayout(w)
        return w


class Page(QScrollArea):
    """Scrollable page with a big title."""

    def __init__(self, title: str, subtitle: str):
        super().__init__()
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.NoFrame)
        body = QWidget()
        body.setObjectName("pagebody")
        self.setWidget(body)
        self.lay = QVBoxLayout(body)
        self.lay.setContentsMargins(28, 22, 28, 22)
        self.lay.setSpacing(14)
        t = QLabel(title)
        t.setObjectName("h1")
        self.lay.addWidget(t)
        self.subtitle = label(subtitle, "sub")
        self.lay.addWidget(self.subtitle)
        self.lay.addSpacing(4)

    def add(self, w):
        self.lay.addWidget(w)
        return w

    def finish(self):
        self.lay.addStretch(1)


# ── Background work ───────────────────────────────────────────────────────────
class WorkerSignals(QObject):
    progress = Signal(dict)
    done = Signal(object)
    failed = Signal(object)


class Worker(QRunnable):
    """Runs fn(progress_callback) in the thread pool."""

    def __init__(self, fn):
        super().__init__()
        self.fn = fn
        self.signals = WorkerSignals()

    def run(self):
        try:
            result = self.fn(self.signals.progress.emit)
        except Exception as e:           # reported to the UI
            log.exception("Background task failed")
            self.signals.failed.emit(e)
        else:
            self.signals.done.emit(result)


# ── Partition tile ────────────────────────────────────────────────────────────
class PartitionTile(QFrame):
    clicked = Signal(str)

    def __init__(self, part: dict):
        super().__init__()
        self.setObjectName("tile")
        self.setCursor(Qt.PointingHandCursor)
        self.name = part["name"]
        v = QVBoxLayout(self)
        v.setContentsMargins(12, 10, 12, 10)
        v.setSpacing(5)
        top = QHBoxLayout()
        n = QLabel(part["name"])
        n.setObjectName("tilename")
        top.addWidget(n)
        top.addStretch(1)
        self.badge = QLabel()
        self.badge.setObjectName("badge")
        self.badge.setFixedHeight(20)
        self.badge.setAlignment(Qt.AlignCenter)
        top.addWidget(self.badge, 0, Qt.AlignVCenter)
        v.addLayout(top)
        meta = [f"max {core.human_duration(part['limit_s'])}"]
        if part["kind"] == "private":
            meta.append("your group's nodes, higher priority")
        if part["waiting"]:
            meta.append(f"{part['waiting']} job(s) waiting")
        v.addWidget(label("  ·  ".join(meta)))
        bar = QProgressBar()
        bar.setTextVisible(False)
        bar.setFixedHeight(6)
        total = max(part["cpus_total"], 1)
        bar.setRange(0, total)
        bar.setValue(part["cpus_free"])
        v.addWidget(bar)
        cores = (f"{fmt_int(part['cpus_free'])} of {fmt_int(part['cpus_total'])} cores free  ·  "
                 f"{part['nodes_idle']} idle node(s)")
        if part["nodes_usable"] < part["nodes_total"]:
            cores += f"  ·  {part['nodes_total'] - part['nodes_usable']} unavailable"
        v.addWidget(label(cores))
        if part["gpu_total"]:
            g = "  ·  ".join(f"{t} {part['gpu_free'].get(t, 0)}/{n}"
                             for t, n in sorted(part["gpu_total"].items()))
            v.addWidget(label("GPUs free: " + g))
        self.reason = label("")
        v.addWidget(self.reason)
        v.addStretch(1)
        # selectable labels would swallow clicks on their text: let the tile get them all
        for w in self.findChildren(QWidget):
            w.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.set_selected(False)
        self.set_fit("unknown", "")

    def set_selected(self, on: bool):
        self.setProperty("selected", "true" if on else "false")
        self.style().unpolish(self)
        self.style().polish(self)

    def set_fit(self, fit: str, reason: str, note: str = ""):
        set_badge(self.badge, fit)
        text = reason if fit == "never" else note
        self.reason.setText(text)
        set_kind(self.reason, "warn" if fit == "never" else "hint")
        self.reason.setVisible(bool(text))

    def mouseReleaseEvent(self, ev):
        if ev.button() == Qt.LeftButton and self.rect().contains(ev.position().toPoint()):
            self.clicked.emit(self.name)
        super().mouseReleaseEvent(ev)


# ── NAS folder browser ────────────────────────────────────────────────────────
class NasBrowser(QDialog):
    """Browse the lab NAS through Baobab and pick a folder."""

    def __init__(self, win: "MainWindow", start: str, title: str):
        super().__init__(win)
        self.win = win
        self.setWindowTitle(title)
        self.resize(640, 520)
        self.path = start.strip("/")
        v = QVBoxLayout(self)
        top = QHBoxLayout()
        self.up_btn = QPushButton("Up")
        self.up_btn.clicked.connect(self.go_up)
        self.where = QLabel()
        self.where.setWordWrap(True)
        top.addWidget(self.up_btn)
        top.addWidget(self.where, 1)
        v.addLayout(top)
        self.list = QListWidget()
        self.list.itemDoubleClicked.connect(self.open_item)
        v.addWidget(self.list, 1)
        self.status = hint("")
        v.addWidget(self.status)
        bb = QDialogButtonBox()
        self.ok_btn = bb.addButton("Select this folder", QDialogButtonBox.AcceptRole)
        bb.addButton(QDialogButtonBox.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        v.addWidget(bb)
        self.load()

    def load(self):
        self.where.setText(f"<b>{self.win.profile['nas_share']}</b> / {self.path or '(top)'}")
        self.list.clear()
        self.status.setText("Reading the NAS through Baobab...")
        self.ok_btn.setEnabled(False)
        conn, prof, path = self.win.conn, self.win.profile, self.path

        def done(d):
            if path != self.path:
                return
            self.list.clear()
            for name in d["dirs"]:
                it = QListWidgetItem("\U0001F4C1  " + name)
                it.setData(Qt.UserRole, name)
                self.list.addItem(it)
            for f in sorted(d["files"], key=lambda f: f["name"].lower()):
                it = QListWidgetItem(f"      {f['name']}   ({core.human_size(f['size'])})")
                it.setFlags(Qt.NoItemFlags)
                self.list.addItem(it)
            self.status.setText(f"{len(d['dirs'])} folder(s), {len(d['files'])} file(s). "
                                "Double-click a folder to open it.")
            self.ok_btn.setEnabled(bool(path))

        def failed(e):
            self.status.setText(error_text(e))
            set_kind(self.status, "warn")

        set_kind(self.status, "hint")
        self.win.run_task(lambda _p: core.nas_ls(conn, prof["nas_share"], path, False,
                                                 prof.get("python_modules") or "Python"),
                          on_done=done, on_fail=failed)

    def open_item(self, it):
        name = it.data(Qt.UserRole)
        if name:
            self.path = f"{self.path}/{name}".strip("/")
            self.load()

    def go_up(self):
        self.path = "/".join(self.path.split("/")[:-1])
        self.load()


# ── Page: settings / connection ───────────────────────────────────────────────
class SettingsPage(Page):
    def __init__(self, win: "MainWindow"):
        super().__init__("Settings", "Your details are stored on this computer, so you only enter "
                                     "them once. The app connects automatically at start-up.")
        self.win = win
        p = win.profile

        acc = self.add(Card("Your UNIGE account"))
        f = QFormLayout()
        f.setVerticalSpacing(10)
        f.setHorizontalSpacing(16)
        self.user = QLineEdit(p["username"])
        self.user.setPlaceholderText("ISIS username, e.g. jdoe")
        self.email = QLineEdit(p["email"])
        self.email.setPlaceholderText("firstname.lastname@unige.ch")
        f.addRow("ISIS username", self.user)
        f.addRow("Email", stack(self.email, hint("Receives a message when a job ends or fails.")))
        acc.add(f)

        con = self.add(Card("SSH connection",
                            "From home or abroad, connect to the UNIGE VPN first."))
        f = QFormLayout()
        f.setVerticalSpacing(10)
        f.setHorizontalSpacing(16)
        self.host = QLineEdit(p["host"])
        self.key = QLineEdit(p["key_path"])
        b = QPushButton("Browse...")
        b.clicked.connect(self.pick_key)
        self.key_hint = hint()
        f.addRow("Cluster", self.host)
        f.addRow("SSH key", stack(row(self.key, b), self.key_hint))
        con.add(f)
        self.connect_btn = QPushButton("Connect")
        self.connect_btn.setObjectName("primary")
        self.connect_btn.clicked.connect(lambda: win.connect_cluster())
        self.status = hint("Not connected.")
        con.add(row(self.status, self.connect_btn))

        sw = self.add(Card("Software on Baobab",
                           "Version lists are read from Baobab when you connect."))
        f = QFormLayout()
        f.setVerticalSpacing(10)
        f.setHorizontalSpacing(16)
        self.matlab = QComboBox()
        self.matlab.setEditable(True)
        self.matlab.addItem(p["matlab_module"])
        self.python = QComboBox()
        self.python.setEditable(True)
        self.python.addItem(p["python_version"])
        self.python_line = hint()
        self.cuda = QLineEdit(p["cuda_module"])
        f.addRow("MATLAB version", self.matlab)
        f.addRow("Python version", stack(self.python, self.python_line))
        f.addRow("CUDA module", stack(self.cuda, hint("Loaded for Python GPU jobs.")))
        sw.add(f)

        nas = self.add(Card("Lab NAS",
                            "Data and results can live on the lab NAS: Baobab copies them "
                            "directly, without going through this PC."))
        f = QFormLayout()
        f.setVerticalSpacing(10)
        f.setHorizontalSpacing(16)
        self.nas_share = QLineEdit(p["nas_share"])
        self.realm = QLineEdit(p["kerberos_realm"])
        f.addRow("NAS share", self.nas_share)
        f.addRow("Kerberos realm", stack(self.realm, hint(
            "Baobab logs in to the NAS with a Kerberos ticket: you give your ISIS password "
            "once, the ticket lasts 10 hours and the app renews it for up to a week. The "
            "password is never stored.")))
        nas.add(f)
        self.nas_btn = QPushButton("Log in to the NAS")
        self.nas_btn.clicked.connect(lambda: win.nas_login())
        self.nas_status = hint("Connect to Baobab first.")
        nas.add(row(self.nas_status, self.nas_btn))

        files = self.add(Card("Files and logs"))
        b = QPushButton("Open the app's data folder")
        b.clicked.connect(lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(core.APP_DIR))))
        files.add(row(hint(f"Profile, job list and diagnostics (app.log) are in {core.APP_DIR}"), b))
        self.finish()

        self.key.textChanged.connect(self.update_key_hint)
        self.python.currentTextChanged.connect(self.python_changed)
        self.update_key_hint()
        self.show_python_line()

    def pick_key(self):
        path, _ = QFileDialog.getOpenFileName(self, "Choose your PRIVATE SSH key (not the .pub)",
                                              str(Path.home() / ".ssh"), "All files (*)")
        if path:
            self.key.setText(str(Path(path)))

    def update_key_hint(self):
        k = self.key.text().strip()
        if not k:
            self.key_hint.setText("No SSH key found. Double-click Baobab_Launcher.bat to create "
                                  "one, or follow README.md.")
            set_kind(self.key_hint, "warn")
        elif k.endswith(".pub"):
            self.key_hint.setText("This is the PUBLIC key. Select the file without .pub.")
            set_kind(self.key_hint, "warn")
        elif not Path(k).expanduser().exists():
            self.key_hint.setText("File not found.")
            set_kind(self.key_hint, "warn")
        else:
            self.key_hint.setText("Its .pub twin must be registered at my-account.unige.ch.")
            set_kind(self.key_hint, "hint")

    def show_python_line(self):
        line = self.win.profile.get("python_modules", "")
        ver = self.python.currentText().strip()
        if line and line.endswith(ver):
            self.python_line.setText(f"Loads: module load {line}")
        else:
            self.python_line.setText("Requirements are checked on Baobab when connected.")

    def python_changed(self, ver):
        ver = ver.strip()
        if not ver or (ver == self.win.profile.get("python_version")
                       and self.win.profile.get("python_modules", "").endswith(ver)):
            return
        self.win.profile["python_version"] = ver
        self.win.profile["python_modules"] = ""
        self.show_python_line()
        self.win.resolve_python()

    def read_into_profile(self):
        p = self.win.profile
        p["username"] = self.user.text().strip()
        p["email"] = self.email.text().strip()
        p["host"] = self.host.text().strip() or core.DEFAULT_HOST
        p["key_path"] = self.key.text().strip()
        p["matlab_module"] = self.matlab.currentText().strip() or "MATLAB/2022a"
        p["python_version"] = self.python.currentText().strip() or "Python/3.12.3"
        p["cuda_module"] = self.cuda.text().strip() or "CUDA"
        p["nas_share"] = self.nas_share.text().strip() or core.DEFAULT_PROFILE["nas_share"]
        p["kerberos_realm"] = self.realm.text().strip().upper() or "ISIS.UNIGE.CH"

    def fill_versions(self, matlab: list[str], python: list[str]):
        for combo, items, key in ((self.matlab, matlab, "matlab_module"),
                                  (self.python, python, "python_version")):
            if not items:
                continue
            cur = self.win.profile[key]
            combo.blockSignals(True)
            combo.clear()
            combo.addItems(items)
            combo.setCurrentText(cur if cur in items else items[0])
            combo.blockSignals(False)
        self.win.profile["python_version"] = self.python.currentText()


# ── Page: new job ─────────────────────────────────────────────────────────────
class NewJobPage(Page):
    def __init__(self, win: "MainWindow"):
        super().__init__("New job", "Choose your code, your data and the resources. Everything "
                                    "is copied to Baobab with checksum verification, and the "
                                    "results come back by themselves.")
        self.win = win
        self.name_edited = False
        self.selected_partition: str | None = None
        self.tiles: dict[str, PartitionTile] = {}

        # 1 · code
        card = self.add(Card("Code", number="1"))
        f = QFormLayout()
        f.setVerticalSpacing(10)
        f.setHorizontalSpacing(16)
        self.project = QLineEdit()
        self.project.setReadOnly(True)
        self.project.setPlaceholderText("Folder containing your scripts and helper functions")
        b = QPushButton("Choose folder...")
        b.clicked.connect(self.pick_project)
        self.project_info = hint()
        f.addRow("Project folder", stack(row(self.project, b), self.project_info))
        self.entry = QComboBox()
        self.entry.currentTextChanged.connect(self.entry_changed)
        self.entry_info = hint()
        f.addRow("Script to run", stack(self.entry, self.entry_info))
        card.add(f)

        # 2 · data & results
        card = self.add(Card("Data and results", number="2"))
        f = QFormLayout()
        f.setVerticalSpacing(10)
        f.setHorizontalSpacing(16)
        self.data_src = QComboBox()
        self.data_src.addItems(["A folder on this PC", "A folder on the lab NAS"])
        self.data_src.setMaximumWidth(260)
        f.addRow("Data from", self.data_src)
        self.data = QLineEdit()
        self.data.setReadOnly(True)
        self.data.setPlaceholderText("Optional - folder with the data your script reads")
        b1 = QPushButton("Choose folder...")
        b1.clicked.connect(self.pick_data)
        b2 = QPushButton("Clear")
        b2.clicked.connect(lambda: self.set_data(""))
        self.data_info = hint()
        self.pc_data_row = stack(row(self.data, b1, b2), self.data_info)
        f.addRow("Data folder", self.pc_data_row)
        self.nas_data = QLineEdit()
        self.nas_data.setReadOnly(True)
        self.nas_data.setPlaceholderText("Folder on the NAS, e.g. GHoltmaat/USERS/me/DATASETS/exp1")
        b5 = QPushButton("Browse NAS...")
        b5.clicked.connect(self.pick_nas_data)
        b6 = QPushButton("Clear")
        b6.clicked.connect(lambda: self.set_nas_data(""))
        self.nas_info = hint()
        self.nas_data_row = stack(row(self.nas_data, b5, b6), self.nas_info)
        f.addRow("NAS folder", self.nas_data_row)
        self.res_dest = QComboBox()
        self.res_dest.addItems(["This PC", "The lab NAS", "Both"])
        self.res_dest.setMaximumWidth(260)
        f.addRow("Results go to", self.res_dest)
        self.results = QLineEdit()
        b3 = QPushButton("Choose folder...")
        b3.clicked.connect(self.pick_results)
        b4 = QPushButton("Default")
        b4.clicked.connect(lambda: self.results.clear())
        self.results_info = hint()
        self.pc_res_row = stack(row(self.results, b3, b4), self.results_info)
        f.addRow("On this PC", self.pc_res_row)
        self.nas_results = QLineEdit()
        b7 = QPushButton("Browse NAS...")
        b7.clicked.connect(self.pick_nas_results)
        self.nas_res_info = hint()
        self.nas_res_row = stack(row(self.nas_results, b7), self.nas_res_info)
        f.addRow("On the NAS", self.nas_res_row)
        self.full_verify = QCheckBox("Full verification of NAS copies: re-read every file "
                                     "from the NAS (about twice as long)")
        f.addRow("", self.full_verify)
        self.data_form = f
        self.results.textChanged.connect(self.update_results_info)
        self.nas_results.textChanged.connect(self.update_results_info)
        self.data_src.currentIndexChanged.connect(lambda _: self.update_data_rows())
        self.res_dest.currentIndexChanged.connect(lambda _: self.update_data_rows())
        card.add(f)
        self.nas_listing_total = None

        # 3 · where to run
        card = self.add(Card("Where to run", number="3"))
        rb = QPushButton("Refresh")
        rb.clicked.connect(lambda: win.refresh_status())
        self.status_time = hint("")
        card.head.addWidget(self.status_time)
        card.head.addWidget(rb)
        self.parts_note = hint("Connect to Baobab to see the partitions and what is free right now.")
        card.add(self.parts_note)
        self.tile_grid = QGridLayout()
        self.tile_grid.setSpacing(10)
        card.add(self.tile_grid)
        self.private_btn = QPushButton("Show private partitions")
        self.private_btn.setObjectName("link")
        self.private_btn.setCheckable(True)
        self.private_btn.toggled.connect(lambda _: self.layout_tiles())
        self.private_btn.hide()
        card.add(row(self.private_btn, stretch_first=False))
        card.body.itemAt(card.body.count() - 1).layout().addStretch(1)

        # 4 · resources
        card = self.add(Card("Resources", number="4"))
        f = QFormLayout()
        f.setVerticalSpacing(10)
        f.setHorizontalSpacing(16)
        self.walltime = QLineEdit("01:00:00")
        self.walltime.setMaximumWidth(160)
        self.time_info = hint()
        f.addRow("Wall time", stack(self.walltime, self.time_info))
        self.cpus = QSpinBox()
        self.cpus.setRange(1, 128)
        self.cpus.setMaximumWidth(160)
        self.cpu_info = hint()
        f.addRow("CPUs", stack(self.cpus, self.cpu_info))
        self.mem = QSpinBox()
        self.mem.setRange(1, 4000)
        self.mem.setValue(3)
        self.mem.setSuffix(" GB")
        self.mem.setMaximumWidth(160)
        self.mem_info = hint()
        f.addRow("Memory (total)", stack(self.mem, self.mem_info))
        self.gpu = QComboBox()
        f.addRow("GPU", self.gpu)
        self.array = QCheckBox("Job array - run the script many times")
        self.array_range = QLineEdit("1-10")
        self.array_range.setMaximumWidth(160)
        self.array_max = QSpinBox()
        self.array_max.setRange(1, 1000)
        self.array_max.setValue(10)
        self.array_max.setPrefix("at most ")
        self.array_max.setSuffix(" at once")
        self.array_info = hint()
        arr = QHBoxLayout()
        arr.setSpacing(8)
        arr.addWidget(self.array)
        arr.addWidget(self.array_range)
        arr.addWidget(self.array_max)
        arr.addStretch(1)
        f.addRow("Repeat", stack(arr, self.array_info))
        self.cont = QCheckBox("Continue automatically in a new run, from the last checkpoint")
        self.cont_runs = QSpinBox()
        self.cont_runs.setRange(2, 50)
        self.cont_runs.setValue(10)
        self.cont_runs.setPrefix("up to ")
        self.cont_runs.setSuffix(" runs")
        self.cont_info = hint()
        cr = QHBoxLayout()
        cr.setSpacing(8)
        cr.addWidget(self.cont)
        cr.addWidget(self.cont_runs)
        cr.addStretch(1)
        f.addRow("Time limit", stack(cr, self.cont_info))
        card.add(f)

        # measured usage of an earlier run of the same script
        self.suggest_box = QFrame()
        self.suggest_box.setStyleSheet(f"QFrame {{ background: {C['accent_soft']}; border-radius: 8px; }}")
        sb = QHBoxLayout(self.suggest_box)
        sb.setContentsMargins(12, 8, 12, 8)
        self.suggest_label = QLabel()
        self.suggest_label.setWordWrap(True)
        self.suggest_label.setStyleSheet("background: transparent;")
        self.suggest_apply = QPushButton("Use these settings")
        self.suggest_apply.clicked.connect(self.apply_suggestion)
        sb.addWidget(self.suggest_label, 1)
        sb.addWidget(self.suggest_apply)
        self.suggest_box.hide()
        self.suggestion: dict | None = None
        card.add(self.suggest_box)

        est = QPushButton("Estimate start time")
        est.clicked.connect(self.estimate)
        self.est_label = hint("SLURM's estimate for your exact request, without submitting.")
        card.add(row(self.est_label, est))

        # submit
        card = self.add(Card("Submit", number="5"))
        self.name = QLineEdit("my_job")
        self.name.textEdited.connect(lambda _: setattr(self, "name_edited", True))
        self.name.textChanged.connect(self.update_results_info)
        pv = QPushButton("Preview script...")
        pv.clicked.connect(self.preview)
        self.submit_btn = QPushButton("Upload and submit")
        self.submit_btn.setObjectName("primary")
        self.submit_btn.clicked.connect(self.submit)
        h = QHBoxLayout()
        h.setSpacing(10)
        h.addWidget(QLabel("Job name"))
        h.addWidget(self.name, 1)
        h.addWidget(pv)
        h.addWidget(self.submit_btn)
        card.add(h)
        self.phase = hint("")
        self.bar = QProgressBar()
        self.bar.setVisible(False)
        self.file_label = hint("")
        self.logbox = QPlainTextEdit()
        self.logbox.setReadOnly(True)
        self.logbox.setFont(mono_font())
        self.logbox.setMinimumHeight(110)
        self.logbox.setPlaceholderText("Transfer and submission messages appear here.")
        for w in (self.phase, self.bar, self.file_label, self.logbox):
            card.add(w)
        for w in (self.phase, self.bar, self.file_label):
            w.setVisible(False)
        self.finish()

        # what the user asked for; a partition may cap it, another restores it
        self.req = {"time": "01:00:00", "cpus": 1, "mem": 3}
        self.mem_edited = False
        self._auto = False
        self.clamp_note = ""
        self.largest_data_file = 0
        self.walltime.textEdited.connect(self.time_edited)
        self.cpus.valueChanged.connect(self.cpus_changed)
        self.mem.valueChanged.connect(self.mem_changed)
        for sig in (self.walltime.textChanged, self.cpus.valueChanged, self.mem.valueChanged,
                    self.gpu.currentIndexChanged):
            sig.connect(self.update_fits)
        self.array.toggled.connect(self.array_toggled)
        self.cont.toggled.connect(lambda _: self.update_cont_info())
        self.walltime.textChanged.connect(lambda _: self.update_cont_info())
        self.array_toggled(False)
        self.fill_gpu_choices(None)
        p = win.profile
        if p.get("last_project") and Path(p["last_project"]).is_dir():
            self.set_project(p["last_project"])
        if p.get("last_data") and Path(p["last_data"]).is_dir():
            self.set_data(p["last_data"])
        self.update_data_rows()
        self.update_results_info()
        self.update_resource_hints()
        self.update_fits()

    # data source and results destination
    def update_data_rows(self):
        nas = self.data_src.currentIndex() == 1
        dest = self.res_dest.currentIndex()            # 0 PC, 1 NAS, 2 both
        self.data_form.setRowVisible(self.pc_data_row, not nas)
        self.data_form.setRowVisible(self.nas_data_row, nas)
        self.data_form.setRowVisible(self.pc_res_row, dest in (0, 2))
        self.data_form.setRowVisible(self.nas_res_row, dest in (1, 2))
        self.data_form.setRowVisible(self.full_verify, nas or dest in (1, 2))
        if dest in (1, 2) and not self.nas_results.text() and self.nas_data.text():
            self.nas_results.setText(self.nas_data.text().rstrip("/") + "/results")
        self.update_results_info()
        self.update_resource_hints()

    def pick_nas_data(self):
        if not self.win.require_nas(self.pick_nas_data):
            return
        start = self.nas_data.text() or self.win.profile.get("nas_last_path") or "GHoltmaat/USERS"
        dlg = NasBrowser(self.win, start, "Data folder on the NAS")
        if dlg.exec():
            self.set_nas_data(dlg.path)

    def pick_nas_results(self):
        if not self.win.require_nas(self.pick_nas_results):
            return
        start = self.nas_results.text() or self.nas_data.text() or \
            self.win.profile.get("nas_last_path") or "GHoltmaat/USERS"
        dlg = NasBrowser(self.win, start.rsplit("/results", 1)[0], "Results folder on the NAS")
        if dlg.exec():
            self.nas_results.setText(dlg.path)

    def set_nas_data(self, path: str):
        self.nas_data.setText(path)
        self.nas_listing_total = None
        if not path:
            self.nas_info.setText("")
            return
        self.win.profile["nas_last_path"] = path
        if self.res_dest.currentIndex() in (1, 2) and not self.nas_results.text():
            self.nas_results.setText(path.rstrip("/") + "/results")
        self.nas_info.setText("Measuring the folder on the NAS...")
        conn, prof = self.win.conn, self.win.profile

        def done(d):
            if self.nas_data.text() != path:
                return
            files = core.nas_data_files(d)
            total = sum(f["size"] for f in files)
            self.nas_listing_total = total
            self.largest_data_file = max((f["size"] for f in files), default=0)
            first = total / (80 * 1024 ** 2)
            skipped = len(d["files"]) - len(files)
            self.nas_info.setText(
                f"{len(files)} file(s), {core.human_size(total)}"
                + (" (its 'results' folder is not copied)" if skipped else "")
                + f". Copied to Baobab before your job: about "
                f"{core.human_duration(max(60, int(first)))} the first time, then only changes.")
            self.nas_info.setToolTip(
                "A staging job copies the folder to your scratch space on Baobab, directly from "
                "the NAS, then your job starts. Later jobs on the same folder only copy new or "
                "changed files. Your script finds the data in ./data/."
                + (f" The folder's 'results' subfolder ({skipped} file(s)) holds results of "
                   "earlier jobs and is not copied." if skipped else ""))
            relayout(self.nas_info)
            self.update_resource_hints()

        def failed(e):
            self.nas_info.setText(error_text(e))
            set_kind(self.nas_info, "warn")
            relayout(self.nas_info)
        set_kind(self.nas_info, "hint")
        self.win.run_task(lambda _p: core.nas_ls(conn, prof["nas_share"], path, True,
                                                 prof.get("python_modules") or "Python"),
                          on_done=done, on_fail=failed)

    # resources: user edits vs automatic adjustments
    def time_edited(self, text: str):
        self.req["time"] = text.strip()
        self.clamp_note = ""

    def cpus_changed(self, v: int):
        if self._auto:
            return
        self.req["cpus"] = v
        if not self.mem_edited:                    # memory follows: 3 GB per CPU
            self._auto = True
            self.mem.setValue(min(3 * v, self.mem.maximum()))
            self._auto = False
        self.update_resource_hints()

    def mem_changed(self, v: int):
        if self._auto:
            return
        self.req["mem"] = v
        self.mem_edited = True
        self.update_resource_hints()

    def apply_limits(self):
        """Fit the requested resources into the selected partition's largest node."""
        part = self.current_partition()
        if not part:
            return
        self._auto = True
        self.cpus.setMaximum(part["max_node_cpus"] or 128)
        self.cpus.setValue(min(self.req["cpus"], self.cpus.maximum()))
        self.mem.setMaximum(max(part["max_node_mem_gb"], 1) if part["max_node_mem_gb"] else 4000)
        want_mem = self.req["mem"] if self.mem_edited else 3 * self.cpus.value()
        self.mem.setValue(min(want_mem, self.mem.maximum()))
        self._auto = False
        self.clamp_note = ""
        try:
            want = core.parse_slurm_time(self.req["time"])
        except ValueError:
            want = None
        limit = part["limit_s"]
        if want and limit and want > limit:
            self.walltime.setText(core.format_walltime(limit))
            self.clamp_note = (f"Set to the {core.human_duration(limit)} maximum of "
                               f"{part['name']} (you asked for {core.human_duration(want)}).")
        elif self.walltime.text().strip() != self.req["time"]:
            self.walltime.setText(self.req["time"])
        self.update_resource_hints()

    def update_resource_hints(self):
        part = self.current_partition()
        entry = self.entry.currentText().lower()
        if entry.endswith(".m"):
            cpu = ("MATLAB spreads matrix maths, FFTs and many image functions over several "
                   "cores: 4-8 CPUs often speed up an analysis. A parfor loop needs one CPU "
                   "per worker.")
        elif entry.endswith(".py"):
            cpu = ("Plain Python runs on 1 core. More CPUs only help with numpy/scipy maths "
                   "on large arrays, multiprocessing, joblib or PyTorch data loaders.")
        else:
            cpu = "1 CPU is enough for a first test."
        if part and part["max_node_cpus"]:
            cpu += f" Largest node here: {part['max_node_cpus']} CPUs."
        self.cpu_info.setText(cpu)
        mem = ("Total for the job. Set by you: it no longer follows the CPUs."
               if self.mem_edited else
               "Total for the job. It follows the CPUs (3 GB each) until you change it.")
        if self.largest_data_file:
            big = self.largest_data_file / 1024 ** 3
            need = max(1, int(-(-3 * big // 1)))
            mem += (f" Largest data file: {core.human_size(self.largest_data_file)}. A script "
                    f"that loads one file at a time typically needs 2-3 times that: about "
                    f"{need} GB.")
        if part and part["max_node_mem_gb"]:
            mem += f" Largest node here: {part['max_node_mem_gb']} GB."
        self.mem_info.setText(mem)

    def update_suggestion(self):
        entry, proj = self.entry.currentText(), self.project.text()
        rec = next((j for j in self.win.registry.jobs
                    if j.get("entry") == entry and j.get("usage")
                    and j.get("project_dir", proj) == proj), None)
        if not rec:
            self.suggestion = None
            self.suggest_box.hide()
            return
        u = rec["usage"]
        sug = core.suggest_resources(u)
        state = rec.get("state", "")
        extra = ""
        if state == "OUT_OF_MEMORY" and rec.get("mem_gb"):
            sug["mem_gb"] = max(sug["mem_gb"], 2 * int(rec["mem_gb"]))
            extra = " It ran out of memory, so the suggestion doubles it."
        if state == "TIMEOUT" and rec.get("walltime"):
            try:
                sug["walltime_s"] = 2 * core.parse_slurm_time(rec["walltime"])
                extra = " It ran out of time, so the suggestion doubles the wall time."
            except ValueError:
                pass
        if rec.get("continue_runs") and rec.get("walltime"):
            try:
                sug["walltime_s"] = core.parse_slurm_time(rec["walltime"])
            except ValueError:
                pass
        self.suggestion = sug
        runs = f"{u['tasks']} runs, " if u.get("tasks", 1) > 1 else ""
        self.suggest_label.setText(
            f"<b>Last run of {Path(entry).name}</b> (job {rec['job_id']}, {state.lower()}, "
            f"{runs}longest {core.human_duration(u['elapsed_s'])}): peak memory "
            f"{u['peak_mem_gb']:g} GB, {u['cpu_eff']:.0%} of {u['cpus']} CPU(s) busy.{extra}"
            f"<br>Suggested: <b>{sug['cpus']} CPU(s), {sug['mem_gb']} GB, "
            f"{core.format_walltime(sug['walltime_s'])}</b>")
        self.suggest_box.show()

    def apply_suggestion(self):
        s = self.suggestion
        if not s:
            return
        self.req.update(cpus=s["cpus"], mem=s["mem_gb"], time=core.format_walltime(s["walltime_s"]))
        self.mem_edited = True
        self.apply_limits()

    # folders
    def pick_project(self):
        d = QFileDialog.getExistingDirectory(self, "Project folder (your code)",
                                             self.project.text() or str(Path.home()))
        if d:
            self.set_project(d)

    def set_project(self, d: str):
        d = str(Path(d))
        self.project.setText(d)
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            files = core.list_local_files(d, "code")
        finally:
            QApplication.restoreOverrideCursor()
        size = sum(s for _, _, s in files)
        scripts = [r for r, _, _ in files if r.lower().endswith((".m", ".py"))]
        scripts.sort(key=lambda r: (r.count("/"), r.lower()))
        big = size > 500 * 1024 ** 2
        msg = f"{len(files)} file(s), {core.human_size(size)} - the whole folder is uploaded."
        if big:
            msg += " This is large for code: put datasets in the Data folder below instead."
        self.project_info.setText(msg)
        set_kind(self.project_info, "warn" if big else "hint")
        self.entry.blockSignals(True)
        self.entry.clear()
        self.entry.addItems(scripts)
        self.entry.blockSignals(False)
        if not scripts:
            self.entry_info.setText("No .m or .py file in this folder.")
            set_kind(self.entry_info, "warn")
        else:
            self.entry_changed(self.entry.currentText())
        self.win.profile["last_project"] = d
        self.update_results_info()

    def pick_data(self):
        d = QFileDialog.getExistingDirectory(self, "Data folder", self.data.text()
                                             or self.project.text() or str(Path.home()))
        if d:
            self.set_data(d)

    def set_data(self, d: str):
        d = str(Path(d)) if d else ""
        self.data.setText(d)
        self.win.profile["last_data"] = d
        if d:
            QApplication.setOverrideCursor(Qt.WaitCursor)
            try:
                files = core.list_local_files(d, "data")
            finally:
                QApplication.restoreOverrideCursor()
            size = sum(s for _, _, s in files)
            self.largest_data_file = max((s for _, _, s in files), default=0)
            self.data_info.setText(
                f"{len(files)} file(s), {core.human_size(size)}. Copied once to your scratch "
                "space and checksum-verified; later jobs only send new or changed files. "
                "Your script finds it in ./data/.")
        else:
            self.largest_data_file = 0
            self.data_info.setText("No data folder: ./data/ will be empty on Baobab.")
        self.update_results_info()
        if hasattr(self, "mem_info"):
            self.update_resource_hints()

    def pick_results(self):
        d = QFileDialog.getExistingDirectory(self, "Where to put results",
                                             self.results.text() or self.default_results())
        if d:
            self.results.setText(str(Path(d)))

    def default_results(self) -> str:
        data = self.data.text() if self.data_src.currentIndex() == 0 else ""
        return core.default_results_base(data, self.project.text())

    def update_results_info(self, *_):
        base = self.results.text().strip() or self.default_results()
        self.results.setPlaceholderText(base or "Choose a project folder first")
        name = core.safe_name(self.name.text(), "job")
        self.results_info.setText(
            f"Each job gets its own folder: {Path(base) / (name + '_<job id>')}. Your script "
            "writes to ./results/; files are downloaded and verified when the job ends."
            if base else "")
        if hasattr(self, "nas_res_info"):
            nb = self.nas_results.text().strip().rstrip("/")
            self.nas_res_info.setText(
                f"After the job, Baobab copies the results and logs into a new folder there: "
                f"{name}_<job id>" if nb else "Choose a folder on the NAS.")

    def entry_changed(self, rel: str):
        if not rel:
            return
        proj = Path(self.project.text())
        if not self.name_edited:
            self.name.setText(core.safe_name(Path(rel).stem))
        if rel.lower().endswith(".m"):
            if core.is_matlab_function(proj / rel):
                txt = ("MATLAB function. In a job array it receives the task number as its "
                       "first argument.")
            else:
                txt = ("MATLAB script (not a function). In a job array, read the task number "
                       "with str2double(getenv('SLURM_ARRAY_TASK_ID')).")
            txt += " All subfolders are added to the MATLAB path."
        else:
            txt = "Python script. The project folder is on PYTHONPATH, so your modules import."
            req = core.find_requirements(proj, rel)
            missing = [] if req else core.third_party_imports(proj, rel)
            if req:
                where = req.relative_to(proj.resolve()).as_posix()
                txt += (f" Packages from {where} are installed on Baobab the first time, "
                        "then reused.")
            elif missing:
                txt = (f"This script imports {', '.join(missing)}, but no requirements.txt was "
                       "found next to it or in a parent folder of the project, so the job would "
                       "fail. Add a requirements.txt listing them, or choose the folder that "
                       "contains it as the project.")
            else:
                txt += " Add a requirements.txt to install extra packages."
        self.entry_info.setText(txt)
        set_kind(self.entry_info, "warn" if rel.lower().endswith(".py") and not
                 core.find_requirements(proj, rel) and core.third_party_imports(proj, rel)
                 else "hint")
        self.array_toggled(self.array.isChecked())
        self.update_resource_hints()
        self.update_suggestion()

    # partitions
    def fill_partitions(self, parts: list[dict]):
        for t in self.tiles.values():
            t.setParent(None)
            t.deleteLater()
        self.tiles = {}
        for p in parts:
            t = PartitionTile(p)
            t.clicked.connect(self.select_partition)
            self.tiles[p["name"]] = t
        names = [p["name"] for p in parts]
        has_private = any(p["kind"] == "private" for p in parts)
        self.private_btn.setVisible(has_private)
        self.parts_note.setText("Click a partition. The badge tells whether your request, with "
                                "the resources below, could start right now." if parts else
                                "No partition available to your account.")
        if self.selected_partition not in names:
            pick = "shared-cpu" if "shared-cpu" in names else \
                next((p["name"] for p in parts if p["default"]), names[0] if names else None)
            self.selected_partition = pick
        self.fill_gpu_choices(self.current_partition())
        self.layout_tiles()
        self.select_partition(self.selected_partition)
        self.status_time.setText("updated " + QTime.currentTime().toString("HH:mm"))

    def layout_tiles(self):
        while self.tile_grid.count():
            self.tile_grid.takeAt(0)
        show_private = self.private_btn.isChecked()
        self.private_btn.setText("Hide private partitions" if show_private
                                 else "Show private partitions")
        i = 0
        for p in self.win.partitions:
            t = self.tiles.get(p["name"])
            if not t:
                continue
            visible = p["kind"] != "private" or show_private or p["name"] == self.selected_partition
            t.setVisible(visible)
            if visible:
                self.tile_grid.addWidget(t, i // 2, i % 2)
                i += 1

    def select_partition(self, name: str | None):
        if not name:
            return
        self.selected_partition = name
        for n, t in self.tiles.items():
            t.set_selected(n == name)
        self.fill_gpu_choices(self.current_partition())
        self.apply_limits()
        self.update_fits()

    def current_partition(self) -> dict | None:
        return next((p for p in self.win.partitions if p["name"] == self.selected_partition), None)

    def fill_gpu_choices(self, part: dict | None):
        cur = self.gpu.currentData()
        self.gpu.blockSignals(True)
        self.gpu.clear()
        if part and part["gpu_total"]:
            free = sum(part["gpu_free"].values())
            self.gpu.addItem(f"Any GPU  ({free} free)", "1")
            for t, n in sorted(part["gpu_total"].items()):
                self.gpu.addItem(f"{GPU_LABELS.get(t, t)}  ({part['gpu_free'].get(t, 0)} of {n} "
                                 "free)", f"{t}:1")
            self.gpu.setEnabled(True)
            idx = self.gpu.findData(cur)
            self.gpu.setCurrentIndex(idx if idx >= 0 else 0)
        else:
            self.gpu.addItem("No GPU on this partition" if part else "No GPU", "")
            self.gpu.setEnabled(False)
        self.gpu.blockSignals(False)

    def update_fits(self, *_):
        try:
            sec = core.parse_slurm_time(self.walltime.text())
            self.time_info.setText(self.clamp_note or
                                   f"= {core.human_duration(sec)}. Shorter requests start sooner.")
            set_kind(self.time_info, "hint")
        except ValueError:
            sec = None
            self.time_info.setText("Use h:m:s (01:30:00) or days-h:m:s (2-00:00:00).")
            set_kind(self.time_info, "warn")
        gpu = self.gpu.currentData() or ""
        # Judge every tile with the request as it would become there: choosing a
        # partition caps wall time, CPUs and memory to what it allows.
        try:
            want_s = core.parse_slurm_time(self.req["time"])
        except ValueError:
            want_s = sec
        for p in self.win.partitions:
            t = self.tiles.get(p["name"])
            if not t:
                continue
            if sec is None:
                t.set_fit("unknown", "")
                continue
            if p["name"] == self.selected_partition:     # fields already adapted to it
                w_s, cpus, mem = sec, self.cpus.value(), self.mem.value()
            else:
                w_s = want_s or sec
                cpus = self.req["cpus"]
                mem = self.req["mem"] if self.mem_edited else 3 * cpus
            notes = []
            if p["limit_s"] and w_s and w_s > p["limit_s"]:
                w_s = p["limit_s"]
                notes.append(f"wall time would be set to {core.human_duration(w_s)}")
            if p["max_node_cpus"] and cpus > p["max_node_cpus"]:
                cpus = p["max_node_cpus"]
                notes.append(f"CPUs limited to {cpus}")
            if p["max_node_mem_gb"] and mem > p["max_node_mem_gb"]:
                mem = p["max_node_mem_gb"]
                notes.append(f"memory limited to {mem} GB")
            # a GPU choice only applies to GPU partitions; CPU tiles judge the CPU request
            fit, why = core.check_fit(p, w_s, cpus, mem, gpu if p["gpu_total"] else "")
            note = ("If chosen: " + ", ".join(notes) + ".") if notes else ""
            t.set_fit(fit, why, note)
        self.est_label.setText("SLURM's estimate for your exact request, without submitting.")
        set_kind(self.est_label, "hint")

    def update_cont_info(self):
        lead = core.warning_lead(self.walltime.text())
        warn = (f"About {core.human_duration(lead)} before the limit, the file named by "
                "BAOBAB_TIME_UP appears: save a checkpoint (in BAOBAB_CHECKPOINT_DIR) and exit "
                f"with code {core.EXIT_CONTINUE}.")
        if self.array.isChecked():
            txt = "Not available for job arrays. " + warn
        elif self.cont.isChecked():
            txt = (warn + " The next run then starts in the same job folder and continues from "
                   "your checkpoint; exit code 0 means finished. Results are downloaded after the "
                   "last run. Your script must be able to resume - see the demos.")
        else:
            txt = ("Every job is warned before its limit: " + warn[0].lower() + warn[1:] +
                   " Tick this to have Baobab run it again from there, until it is done.")
        self.cont_info.setText(txt)
        self.cont_runs.setEnabled(self.cont.isChecked() and not self.array.isChecked())

    def array_toggled(self, on: bool):
        self.array_range.setEnabled(on)
        self.array_max.setEnabled(on)
        self.cont.setEnabled(not on)
        if on:
            self.cont.setChecked(False)
        if hasattr(self, "cont_info"):
            self.update_cont_info()
        if not on:
            self.array_info.setText("")
            self.array_info.hide()
            return
        self.array_info.show()
        how = ("Your Python script receives the task number as sys.argv[1]."
               if self.entry.currentText().lower().endswith(".py")
               else "Each run receives its task number (see the script note above).")
        self.array_info.setText(f"Runs the script once per number in the range, e.g. 1-10 or "
                                f"1,5,7. {how} Write results to per-task file names.")

    # submission
    def collect_spec(self) -> core.JobSpec:
        p = self.win.profile
        part = self.current_partition()
        if not part:
            raise core.BaobabError("Connect to Baobab first, then choose where to run.")
        spec = core.JobSpec(
            name=core.safe_name(self.name.text(), "job"),
            project_dir=self.project.text(),
            entry=self.entry.currentText(),
            partition=part["name"],
            walltime=self.walltime.text().strip(),
            cpus=self.cpus.value(),
            mem_gb=self.mem.value(),
            gpu=self.gpu.currentData() if self.gpu.isEnabled() else "",
            array_range=self.array_range.text().strip() if self.array.isChecked() else "",
            array_max=self.array_max.value() if self.array.isChecked() else 0,
            email=p["email"],
            data_dir=self.data.text() if self.data_src.currentIndex() == 0 else "",
            results_base=self.results.text().strip(),
            nas_share=p["nas_share"],
            nas_data=self.nas_data.text().strip() if self.data_src.currentIndex() == 1 else "",
            nas_results=(self.nas_results.text().strip()
                         if self.res_dest.currentIndex() in (1, 2) else ""),
            results_to_pc=self.res_dest.currentIndex() in (0, 2),
            nas_full_verify=self.full_verify.isChecked(),
            matlab_module=p["matlab_module"],
            python_modules=p.get("python_modules") or p["python_version"],
            cuda_module=p["cuda_module"],
            continue_runs=self.cont_runs.value() if self.cont.isChecked() else 0)
        if self.data_src.currentIndex() == 1 and not spec.nas_data:
            raise core.BaobabError("Choose the data folder on the NAS, or switch to 'A folder on "
                                   "this PC'.")
        if self.res_dest.currentIndex() in (1, 2) and not spec.nas_results:
            raise core.BaobabError("Choose the results folder on the NAS.")
        core.validate_spec(spec)
        fit, why = core.check_fit(part, core.parse_slurm_time(spec.walltime), spec.cpus,
                                  spec.mem_gb, spec.gpu)
        if fit == "never":
            raise core.BaobabError(f"This request cannot run on {part['name']}: {why}. "
                                   "Change the resources or choose another partition.")
        return spec

    def estimate(self):
        if not self.win.conn.alive():
            QMessageBox.warning(self, APP_TITLE, "Not connected to Baobab.")
            return
        part = self.current_partition()
        if not part:
            return
        try:
            core.parse_slurm_time(self.walltime.text())
        except ValueError:
            QMessageBox.warning(self, APP_TITLE, "Enter a valid wall time first.")
            return
        spec = core.JobSpec(name="estimate", project_dir="", entry="", partition=part["name"],
                            walltime=self.walltime.text().strip(), cpus=self.cpus.value(),
                            mem_gb=self.mem.value(),
                            gpu=self.gpu.currentData() if self.gpu.isEnabled() else "")
        self.est_label.setText(f"Asking SLURM about {part['name']}...")
        set_kind(self.est_label, "hint")
        conn = self.win.conn

        def done(r):
            if r["wait_s"] is None:
                when = f"at {r['start']}"
            elif r["wait_s"] < 60:
                when = "right away"
            else:
                when = f"in about {core.human_duration(r['wait_s'])} ({r['start']})"
            self.est_label.setText(f"{part['name']}: expected to start {when}. SLURM's estimates "
                                   "are cautious; jobs often start earlier.")
            set_kind(self.est_label, "ok")

        def failed(e):
            self.est_label.setText(f"{part['name']}: {error_text(e)}")
            set_kind(self.est_label, "warn")

        self.win.run_task(lambda _p: core.estimate_start(conn, spec), on_done=done, on_fail=failed)

    def preview(self):
        try:
            spec = self.collect_spec()
        except core.BaobabError as e:
            QMessageBox.warning(self, APP_TITLE, str(e))
            return
        scratch = self.win.conn.scratch or "~/scratch"
        env = ("<python environment>" if spec.language == "python"
               and core.find_requirements(spec.project_dir, spec.entry) else "")
        is_fn = spec.language != "matlab" or core.is_matlab_function(
            Path(spec.project_dir) / spec.entry)
        text = core.build_sbatch(spec, f"{scratch}/baobab_jobs/{spec.name}_<date-time>", env, is_fn)
        dlg = QDialog(self)
        dlg.setWindowTitle("Script that will be submitted")
        v = QVBoxLayout(dlg)
        t = QPlainTextEdit(text)
        t.setReadOnly(True)
        t.setFont(mono_font())
        v.addWidget(t)
        bb = QDialogButtonBox(QDialogButtonBox.Close)
        bb.rejected.connect(dlg.reject)
        v.addWidget(bb)
        dlg.resize(820, 560)
        dlg.exec()

    def submit(self):
        if not self.win.conn.alive():
            QMessageBox.warning(self, APP_TITLE, "Not connected to Baobab. Connect in Settings.")
            return
        try:
            spec = self.collect_spec()
        except core.BaobabError as e:
            QMessageBox.warning(self, APP_TITLE, str(e))
            return
        if spec.language == "python" and not core.find_requirements(spec.project_dir, spec.entry):
            missing = core.third_party_imports(spec.project_dir, spec.entry)
            if missing and QMessageBox.question(
                    self, APP_TITLE,
                    f"This script imports {', '.join(missing)}, but there is no requirements.txt "
                    "to install them on Baobab, so the job will probably fail.\n\n"
                    "Submit anyway?") != QMessageBox.Yes:
                return
        if spec.uses_nas and not self.win.nas_ok:
            self.win.nas_login(then=self.submit)
            return
        self.win.save_profile()
        self.logbox.clear()
        self.set_busy(True)
        conn, cache = self.win.conn, self.win.cache
        self.win.run_task(lambda prog: core.submit_job(conn, spec, cache, prog),
                          on_done=self.submitted, on_fail=self.submit_failed,
                          on_progress=self.on_progress)

    def set_busy(self, busy: bool):
        self.win.submitting = busy
        self.submit_btn.setEnabled(not busy)
        self.submit_btn.setText("Working..." if busy else "Upload and submit")
        for w in (self.phase, self.bar, self.file_label):
            w.setVisible(busy)

    def on_progress(self, d: dict):
        if "log" in d:
            self.logbox.appendPlainText(d["log"])
            return
        show_progress(d, self.phase, self.bar, self.file_label)

    def submitted(self, rec: dict):
        self.set_busy(False)
        self.win.registry.add(rec)
        self.win.jobs_page.refresh_table()
        self.logbox.appendPlainText(f"Results will be downloaded to {rec['results_local']}")
        self.win.statusBar().showMessage(f"Job {rec['job_id']} submitted", 10_000)
        QTimer.singleShot(5_000, self.win.poll)
        box = QMessageBox(self)
        box.setWindowTitle(APP_TITLE)
        box.setIcon(QMessageBox.Information)
        box.setText(f"Job {rec['job_id']} submitted.")
        box.setInformativeText("You can follow it on the Jobs page. Results are downloaded "
                               f"automatically when it ends, to:\n{rec['results_local']}")
        go = box.addButton("Go to Jobs", QMessageBox.AcceptRole)
        box.addButton("Stay here", QMessageBox.RejectRole)
        box.exec()
        if box.clickedButton() is go:
            self.win.go("jobs")

    def submit_failed(self, e):
        self.set_busy(False)
        self.logbox.appendPlainText("ERROR: " + error_text(e))
        QMessageBox.critical(self, APP_TITLE, "The job was not submitted.\n\n" + error_text(e))


def show_progress(d: dict, phase: QLabel, bar: QProgressBar, file_label: QLabel):
    phase.setText(d.get("phase", ""))
    phase.setVisible(True)
    file_label.setVisible(True)
    bar.setVisible(True)
    total = d.get("total", 0)
    if total:
        bar.setRange(0, 1000)
        bar.setValue(int(1000 * min(d["done"], total) / total))
        bar.setFormat(f"%p%  -  {core.human_size(d['done'])} of {core.human_size(total)}")
    else:
        bar.setRange(0, 0)       # busy indicator
    if d.get("files_total"):
        file_label.setText(f"File {min(d['files_done'] + 1, d['files_total'])} of "
                           f"{d['files_total']}: {d.get('file', '')}")
    else:
        file_label.setText("")


# ── Page: interactive sessions ────────────────────────────────────────────────
class CopyRow(QWidget):
    """A read-only text with a Copy button."""

    def __init__(self, text: str = ""):
        super().__init__()
        h = QHBoxLayout(self)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(8)
        self.edit = QLineEdit(text)
        self.edit.setReadOnly(True)
        self.edit.setFont(mono_font())
        self.btn = QPushButton("Copy")
        self.btn.clicked.connect(self.copy)
        h.addWidget(self.edit, 1)
        h.addWidget(self.btn)

    def set(self, text: str):
        self.edit.setText(text)
        self.edit.setCursorPosition(0)

    def copy(self):
        QApplication.clipboard().setText(self.edit.text())
        self.btn.setText("Copied")
        QTimer.singleShot(1500, lambda: self.btn.setText("Copy"))


class InteractivePage(Page):
    def __init__(self, win: "MainWindow"):
        super().__init__("Interactive session",
                         "A Linux desktop on a compute node, in your browser, for work that needs "
                         "a graphical interface: MATLAB's editor and figures, image viewers... It "
                         "runs while you use it, unlike the jobs submitted from New job.")
        self.win = win
        self.info: dict = {}

        card = self.add(Card("Remote desktop on Baobab (Open OnDemand)"))
        self.open_btn = QPushButton("Open the remote desktop")
        self.open_btn.setObjectName("primary")
        self.open_btn.clicked.connect(self.open_ood)
        card.add(row(hint("Opens Open OnDemand in your browser. Log in with your UNIGE account; "
                          "from home, connect to the UNIGE VPN first."), self.open_btn))
        self.url = QLineEdit(win.profile.get("ood_url") or core.DEFAULT_PROFILE["ood_url"])
        self.url.editingFinished.connect(self.save_url)
        card.add(row(QLabel("Address"), self.url, stretch_first=False))
        card.body.itemAt(card.body.count() - 1).layout().setStretch(1, 1)

        card = self.add(Card("Start a session", number="1"))
        steps = label(
            "<ol style='margin-left:-20px'>"
            "<li>In Open OnDemand, open <b>Interactive Apps &rarr; Desktop</b>.</li>"
            "<li>Desktop environment: <b>XFCE</b>, lighter and more reliable than GNOME.</li>"
            "<li>Partition: <b>public-interactive-cpu</b> for up to 8 hours and 6 cores; "
            "<b>shared-cpu</b> (12 h) or <b>public-cpu</b> (4 days) for more.</li>"
            "<li>Hours, cores and memory: ask for what you need. The session ends at its time "
            "limit, so save your work before.</li>"
            "<li><b>Launch</b>, wait until the session is <i>Running</i>, then click "
            "<b>Launch Desktop</b>.</li>"
            "<li>When you're done, <b>Delete</b> the session in Open OnDemand to free the node.</li>"
            "</ol>")
        steps.setTextFormat(Qt.RichText)
        steps.setStyleSheet(f"color: {C['text']};")
        card.add(steps)

        card = self.add(Card("MATLAB with its interface", number="2"))
        card.add(label("In the desktop, open a terminal (right-click on the desktop, "
                       "<i>Open Terminal Here</i>) and run:"))
        self.matlab_cmd = CopyRow()
        card.add(self.matlab_cmd)
        card.add(label("-softwareopengl draws MATLAB's graphics without the node's graphics card, "
                       "which avoids blank or crashing windows in a remote desktop."))

        card = self.add(Card("Your files in the session", number="3"))
        card.add(QLabel("<b>Your scratch space</b>, with the jobs and datasets of this app:"))
        self.scratch_row = CopyRow()
        card.add(self.scratch_row)
        self.jobs_label = QLabel("<b>Results of your latest jobs</b>, to open them without "
                                 "downloading anything:")
        card.add(self.jobs_label)
        self.job_rows = [CopyRow() for _ in range(3)]
        for r_ in self.job_rows:
            card.add(r_)
        card.add(QLabel("<b>The lab NAS</b>: in the file manager, type this in the address bar "
                        "(log in with your ISIS account if asked):"))
        self.smb_row = CopyRow()
        card.add(self.smb_row)
        card.add(label("MATLAB can't open smb:// addresses. Once the share is open in the file "
                       "manager, MATLAB reaches the same folder through this Linux path, which "
                       "exists only during that session:"))
        self.gvfs_row = CopyRow()
        card.add(self.gvfs_row)
        self.gvfs_example = label("")
        card.add(self.gvfs_example)
        self.finish()
        self.refresh()

    def save_url(self):
        self.win.profile["ood_url"] = self.url.text().strip() or core.DEFAULT_PROFILE["ood_url"]
        self.win.save_profile()

    def open_ood(self):
        self.save_url()
        QDesktopServices.openUrl(QUrl(self.win.profile["ood_url"]))

    def refresh(self):
        p = self.win.profile
        self.matlab_cmd.set(f"module load {p['matlab_module']} && matlab -softwareopengl")
        scratch = self.info.get("scratch") or self.win.conn.scratch
        self.scratch_row.set(scratch or "(connect to Baobab to see your path)")
        jobs = [j for j in self.win.registry.jobs if j.get("job_dir")][:3]
        self.jobs_label.setVisible(bool(jobs))
        for r_, j in zip(self.job_rows, jobs + [None] * 3):
            r_.setVisible(j is not None)
            if j:
                r_.set(f"{j['job_dir']}/results")
                r_.edit.setToolTip(f"Job {j['job_id']} - {j['name']} ({j['state']})")
        where = (p.get("nas_last_path") or "").strip("/")
        self.smb_row.set(core.smb_url(p["nas_share"], where))
        uid = self.info.get("uid")
        if uid:
            path = core.gvfs_path(uid, p["nas_share"], where)
            self.gvfs_row.set(path)
            self.gvfs_example.setText(f"In MATLAB: cd('{path}')")
        else:
            self.gvfs_row.set("(connect to Baobab to compute your path)")
            self.gvfs_example.setText("")

    def load_info(self):
        if not self.win.conn.alive():
            return
        conn = self.win.conn

        def done(info):
            self.info = info
            self.refresh()
        self.win.run_task(lambda _p: core.session_info(conn), on_done=done,
                          on_fail=lambda e: log.warning("session info: %s", e))


# ── Page: cluster ─────────────────────────────────────────────────────────────
class ClusterPage(Page):
    def __init__(self, win: "MainWindow"):
        super().__init__("Cluster", "What Baobab has free right now, for the partitions your "
                                    "account can use. Refreshed every 2 minutes.")
        self.win = win
        card = self.add(Card("Partitions"))
        self.updated = hint("")
        rb = QPushButton("Refresh")
        rb.clicked.connect(lambda: win.refresh_status())
        card.head.addWidget(self.updated)
        card.head.addWidget(rb)
        self.table = self._table(["Partition", "Max time", "Cores free", "Idle nodes",
                                  "GPUs free", "Jobs waiting"])
        card.add(self.table)
        card = self.add(Card("GPUs by type", "Free now, over all your GPU partitions."))
        self.gpu_table = self._table(["GPU type", "Good for", "Free", "Total", "Partitions"])
        card.add(self.gpu_table)
        card = self.add(Card("Your datasets on scratch",
                             "Data copied to Baobab (from this PC or the NAS) stays on scratch so "
                             "later jobs start without copying it again. Scratch is shared and "
                             "not backed up: delete what you no longer need."))
        self.ds_info = label("", wrap=False)
        rb2 = QPushButton("Refresh")
        rb2.clicked.connect(self.load_datasets)
        card.head.addWidget(self.ds_info)
        card.head.addWidget(rb2)
        self.ds_table = self._table(["Dataset", "Source", "Size", "Files", "Last used"])
        self.ds_table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.ds_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.ds_table.setFocusPolicy(Qt.StrongFocus)
        card.add(self.ds_table)
        self.ds_del = QPushButton("Delete selected dataset")
        self.ds_del.clicked.connect(self.delete_dataset)
        card.add(row(QWidget(), self.ds_del))
        self.datasets: list[dict] = []

        card = self.add(Card("Which partition should I use?"))
        guide = label(
            "<b>debug-cpu</b> - a quick test of your script, 15 minutes at most.<br>"
            "<b>shared-cpu / shared-gpu</b> - most jobs, up to 12 hours. They include every "
            "node of the cluster, so they usually start soonest.<br>"
            "<b>public-cpu / public-bigmem</b> - jobs from 12 hours to 4 days.<br>"
            "<b>public-longrun-cpu</b> - small jobs (2 cores) that need up to 14 days.<br>"
            "<b>*-bigmem</b> - when you need more than about 10 GB per CPU.<br>"
            "<b>private-*</b> - your group's own nodes, if it has some: higher priority, up to "
            "7 days.")
        guide.setTextFormat(Qt.RichText)
        guide.setStyleSheet(f"color: {C['text']}; line-height: 150%;")
        card.add(guide)
        self.finish()

    @staticmethod
    def _table(cols):
        t = QTableWidget(0, len(cols))
        t.setHorizontalHeaderLabels(cols)
        t.verticalHeader().setVisible(False)
        t.setEditTriggers(QAbstractItemView.NoEditTriggers)
        t.setSelectionMode(QAbstractItemView.NoSelection)
        t.setFocusPolicy(Qt.NoFocus)
        t.setShowGrid(False)
        hh = t.horizontalHeader()
        hh.setDefaultAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        for i in range(len(cols)):
            hh.setSectionResizeMode(i, QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(len(cols) - 1, QHeaderView.Stretch)
        t.setMinimumHeight(120)
        return t

    def load_datasets(self):
        if not self.win.conn.alive():
            return
        self.ds_info.setText("reading...")
        conn = self.win.conn

        def done(ds):
            self.datasets = ds
            t = self.ds_table
            t.setRowCount(len(ds))
            for r, d in enumerate(ds):
                used = (time.strftime("%Y-%m-%d", time.localtime(d["last_used"]))
                        if d.get("last_used") else "")
                vals = [d["name"], d.get("source", ""), core.human_size(d.get("total_bytes") or 0),
                        "" if d.get("files") is None else str(d["files"]), used]
                for c, v in enumerate(vals):
                    t.setItem(r, c, QTableWidgetItem(v))
            t.setFixedHeight(t.horizontalHeader().height() + 6
                             + sum(t.rowHeight(i) for i in range(t.rowCount())) + 2)
            total = sum(d.get("total_bytes") or 0 for d in ds)
            self.ds_info.setText(f"{len(ds)} dataset(s), {core.human_size(total)}")
        self.win.run_task(lambda _p: core.list_datasets(conn), on_done=done,
                          on_fail=lambda e: self.ds_info.setText(error_text(e)))

    def delete_dataset(self):
        rows = self.ds_table.selectionModel().selectedRows()
        if not rows:
            QMessageBox.information(self, APP_TITLE, "Select a dataset in the list first.")
            return
        d = self.datasets[rows[0].row()]
        busy = [j["job_id"] for j in self.win.registry.jobs
                if j.get("data_remote") == d["path"] and j["state"] not in core.FINAL_STATES]
        if busy:
            QMessageBox.warning(self, APP_TITLE, f"This dataset is used by job(s) "
                                f"{', '.join(busy)}, which have not finished.")
            return
        if QMessageBox.question(
                self, APP_TITLE,
                f"Delete {d['name']} ({core.human_size(d.get('total_bytes') or 0)}) from your "
                f"scratch space on Baobab?\n\nSource: {d.get('source', '?')}\nYour original data "
                "(on this PC or the NAS) is not touched; a later job copies it again if "
                "needed.") != QMessageBox.Yes:
            return
        conn = self.win.conn
        self.win.run_task(lambda _p: core.delete_dataset(conn, d["path"]),
                          on_done=lambda _r: self.load_datasets())

    def fill(self, parts: list[dict]):
        t = self.table
        t.setRowCount(len(parts))
        for r, p in enumerate(parts):
            ratio = p["cpus_free"] / max(p["cpus_total"], 1)
            gpus = ", ".join(f"{k} {p['gpu_free'].get(k, 0)}/{n}"
                             for k, n in sorted(p["gpu_total"].items())) or "-"
            vals = [p["name"] + ("  (private)" if p["kind"] == "private" else ""),
                    core.human_duration(p["limit_s"]),
                    f"{fmt_int(p['cpus_free'])} / {fmt_int(p['cpus_total'])}  ({ratio:.0%})",
                    f"{p['nodes_idle']} / {p['nodes_total']}", gpus, str(p["waiting"])]
            for c, v in enumerate(vals):
                it = QTableWidgetItem(v)
                if c == 2:
                    it.setBackground(QColor(C["ok_soft"] if ratio > 0.25 else
                                            C["warn_soft"] if ratio > 0.05 else C["err_soft"]))
                t.setItem(r, c, it)
        t.setFixedHeight(t.horizontalHeader().height() + 4
                         + sum(t.rowHeight(i) for i in range(t.rowCount())))
        per_type: dict[str, list] = {}
        for p in parts:
            for k, n in p["gpu_total"].items():
                e = per_type.setdefault(k, [0, 0, []])
                if p["kind"] != "private":        # shared partitions include every node
                    e[0] = max(e[0], p["gpu_free"].get(k, 0))
                    e[1] = max(e[1], n)
                e[2].append(p["name"])
        g = self.gpu_table
        g.setRowCount(len(per_type))
        for r, (k, (free, total, names)) in enumerate(sorted(per_type.items())):
            vals = [k, GPU_LABELS.get(k, "").split(" - ")[-1], str(free), str(total),
                    ", ".join(names)]
            for c, v in enumerate(vals):
                it = QTableWidgetItem(v)
                if c == 2:
                    it.setBackground(QColor(C["ok_soft"] if free else C["err_soft"]))
                g.setItem(r, c, it)
        g.setFixedHeight(g.horizontalHeader().height() + 4
                         + sum(g.rowHeight(i) for i in range(g.rowCount())))
        self.updated.setText("updated " + QTime.currentTime().toString("HH:mm"))


# ── Page: jobs ────────────────────────────────────────────────────────────────
class JobsPage(Page):
    COLS = ["Job ID", "Name", "State", "Details", "Used", "Submitted", "Results"]

    def __init__(self, win: "MainWindow"):
        super().__init__("Jobs", "Your submitted jobs. Results are downloaded and verified "
                                 "automatically when a job ends.")
        self.win = win
        card = self.add(Card("Your jobs"))
        self.updated = hint("")
        rb = QPushButton("Refresh")
        rb.clicked.connect(lambda: self.win.poll(force=True))
        card.head.addWidget(self.updated)
        card.head.addWidget(rb)
        self.auto = QCheckBox("Download results automatically when a job ends")
        self.auto.setChecked(bool(win.profile.get("auto_download", True)))
        self.auto.toggled.connect(self.auto_toggled)
        card.add(self.auto)
        self.table = QTableWidget(0, len(self.COLS))
        self.table.setHorizontalHeaderLabels(self.COLS)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.setShowGrid(False)
        self.table.setMinimumHeight(220)
        hh = self.table.horizontalHeader()
        hh.setDefaultAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        for i in range(len(self.COLS)):
            hh.setSectionResizeMode(i, QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(3, QHeaderView.Stretch)
        self.table.itemSelectionChanged.connect(self.selection_changed)
        self.table.doubleClicked.connect(lambda _: self.show_log())
        card.add(self.table)
        self.b_log = QPushButton("Show log")
        self.b_log.clicked.connect(self.show_log)
        self.b_dl = QPushButton("Download results now")
        self.b_dl.clicked.connect(lambda: self.download_selected())
        self.b_open = QPushButton("Open results folder")
        self.b_open.clicked.connect(self.open_results)
        self.b_cancel = QPushButton("Cancel job")
        self.b_cancel.clicked.connect(self.cancel_selected)
        self.b_nas = QPushButton("Copy results to the NAS")
        self.b_nas.clicked.connect(self.retry_nas)
        self.b_remove = QPushButton("Remove from list")
        self.b_remove.clicked.connect(self.remove_selected)
        btns = QHBoxLayout()
        for b in (self.b_log, self.b_dl, self.b_open, self.b_nas, self.b_cancel):
            btns.addWidget(b)
        btns.addStretch(1)
        btns.addWidget(self.b_remove)
        card.add(btns)
        self.phase = hint("")
        self.bar = QProgressBar()
        self.file_label = hint("")
        for w in (self.phase, self.bar, self.file_label):
            card.add(w)
            w.setVisible(False)

        card = self.add(Card("Log"))
        self.view = QPlainTextEdit()
        self.view.setReadOnly(True)
        self.view.setFont(mono_font())
        self.view.setMinimumHeight(220)
        self.view.setPlaceholderText("Select a job and click 'Show log' to see its output.")
        card.add(self.view)
        self.finish()
        self.refresh_table()

    def auto_toggled(self, on):
        self.win.profile["auto_download"] = on
        self.win.save_profile()
        if on:
            self.win.download_finished_jobs()

    def refresh_table(self):
        sel = self.selected_id()
        jobs = self.win.registry.jobs
        self.table.setRowCount(len(jobs))
        for r, j in enumerate(jobs):
            if j["job_id"] in self.win.downloading:
                res = "downloading..."
            elif j.get("downloaded") and j.get("results_to_pc") is False:
                res = {"done": "on the NAS", "failed": "NAS copy failed",
                       "missing": "not on the NAS yet"}.get(j.get("upload_state"), "on the NAS")
            elif j.get("downloaded"):
                res = "downloaded, verified" + (" + on the NAS" if j.get("upload_state") == "done"
                                                else "")
            elif j.get("download_note"):
                res = j["download_note"]
            elif j["state"] in core.FINAL_STATES:
                res = "not downloaded"
            else:
                res = "waiting for the job"
            u = j.get("usage")
            used = (f"{u['peak_mem_gb']:g} GB peak · {u['cpu_eff']:.0%} of {u['cpus']} CPU"
                    if u else "")
            vals = [j["job_id"], j["name"], j["state"], j.get("detail", ""), used,
                    j.get("submitted", ""), res]
            for c, v in enumerate(vals):
                it = QTableWidgetItem(str(v))
                if c == 2:
                    it.setBackground(QColor(STATE_COLORS.get(j["state"], "#ffffff")))
                if c == 4 and u:
                    it.setToolTip(f"Requested {j.get('cpus', '?')} CPU(s) and "
                                  f"{j.get('mem_gb', '?')} GB; ran "
                                  f"{core.human_duration(u['elapsed_s'])}.")
                if c == 6:
                    it.setToolTip(j.get("results_local", ""))
                self.table.setItem(r, c, it)
            if j["job_id"] == sel:
                self.table.selectRow(r)
        self.selection_changed()

    def selected_id(self) -> str | None:
        sm = self.table.selectionModel()
        rows = sm.selectedRows() if sm else []
        if not rows:
            return None
        it = self.table.item(rows[0].row(), 0)
        return it.text() if it else None

    def selected(self) -> dict | None:
        jid = self.selected_id()
        return self.win.registry.get(jid) if jid else None

    def selection_changed(self):
        j = self.selected()
        for b in (self.b_log, self.b_dl, self.b_open, self.b_remove):
            b.setEnabled(j is not None)
        self.b_cancel.setEnabled(bool(j and j["state"] not in core.FINAL_STATES))
        self.b_nas.setVisible(bool(j and j.get("nas_dest")))
        self.b_nas.setEnabled(bool(j and j["state"] in core.FINAL_STATES
                                   and j.get("upload_state") in ("failed", "missing")))
        self.b_dl.setEnabled(bool(j and j.get("results_to_pc") is not False))

    def show_log(self):
        j = self.selected()
        if not j:
            return
        if not self.win.conn.alive():
            self.view.setPlainText("Not connected.")
            return
        self.view.setPlainText(f"Loading the log of job {j['job_id']}...")
        conn = self.win.conn
        self.win.run_task(lambda _p: core.tail_log(conn, j["job_dir"]),
                          on_done=lambda text: self.view.setPlainText(
                              f"Job {j['job_id']} - {j['name']}\n{j['job_dir']}\n\n{text}"),
                          on_fail=lambda e: self.view.setPlainText("Error: " + error_text(e)))

    def download_selected(self):
        j = self.selected()
        if j:
            self.win.start_download(j["job_id"], manual=True)

    def open_results(self):
        j = self.selected()
        if not j:
            return
        p = Path(j["results_local"])
        if not p.exists():
            QMessageBox.information(self, APP_TITLE, f"Nothing downloaded yet.\n\n{p}")
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(p)))

    def retry_nas(self):
        j = self.selected()
        if not j or not self.win.require_nas(self.retry_nas):
            return
        conn = self.win.conn

        def done(uid):
            self.win.registry.update(j["job_id"], upload_id=uid, upload_state="running",
                                     state="UPLOADING")
            self.refresh_table()
            QTimer.singleShot(3_000, lambda: self.win.poll(True))
        self.win.run_task(lambda _p: core.retry_upload(conn, j), on_done=done)

    def cancel_selected(self):
        j = self.selected()
        if not j:
            return
        if QMessageBox.question(self, APP_TITLE, f"Cancel job {j['job_id']} ({j['name']})?") \
                != QMessageBox.Yes:
            return
        conn = self.win.conn
        self.win.run_task(lambda _p: core.cancel_job(conn, j["job_id"], j),
                          on_done=lambda _r: QTimer.singleShot(2_000, lambda: self.win.poll(True)))

    def remove_selected(self):
        j = self.selected()
        if not j:
            return
        if QMessageBox.question(
                self, APP_TITLE,
                f"Remove job {j['job_id']} from this list?\n\nNothing is deleted: files on Baobab "
                "and downloaded results stay where they are.") != QMessageBox.Yes:
            return
        self.win.registry.remove(j["job_id"])
        self.refresh_table()


# ── Main window ───────────────────────────────────────────────────────────────
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(APP_TITLE)
        if ICON_FILE.exists():
            self.setWindowIcon(QIcon(str(ICON_FILE)))
        self.resize(1180, 860)
        self.profile = core.load_profile()
        self.conn = core.Connection()
        self.registry = core.JobRegistry()
        self.cache = core.HashCache()
        self.partitions: list[dict] = []
        self.pool = QThreadPool.globalInstance()
        self.pool.setMaxThreadCount(6)
        self._signals: set = set()
        self.submitting = False
        self.downloading: set[str] = set()
        self.polling = False
        self.status_busy = False
        self.nas_ok = False
        self.nas_renewed = 0.0

        # sidebar
        side = QFrame()
        side.setObjectName("sidebar")
        side.setFixedWidth(220)
        sv = QVBoxLayout(side)
        sv.setContentsMargins(14, 18, 14, 14)
        sv.setSpacing(4)
        brand = QHBoxLayout()
        logo = QLabel()
        png = APP_DIR_CODE / "baobab.png"
        if png.exists():
            logo.setPixmap(QPixmap(str(png)).scaled(36, 36, Qt.KeepAspectRatio,
                                                    Qt.SmoothTransformation))
        brand.addWidget(logo)
        bt = QVBoxLayout()
        bt.setSpacing(0)
        b1 = QLabel("Baobab HPC")
        b1.setObjectName("brand")
        b2 = QLabel("UNIGE cluster")
        b2.setObjectName("brandsub")
        bt.addWidget(b1)
        bt.addWidget(b2)
        brand.addLayout(bt)
        brand.addStretch(1)
        sv.addLayout(brand)
        sv.addSpacing(18)

        self.stack = QStackedWidget()
        self.settings_page = SettingsPage(self)
        self.job_page = NewJobPage(self)
        self.cluster_page = ClusterPage(self)
        self.jobs_page = JobsPage(self)
        self.interactive_page = InteractivePage(self)
        self.pages = {"new": self.job_page, "jobs": self.jobs_page,
                      "cluster": self.cluster_page, "interactive": self.interactive_page,
                      "settings": self.settings_page}
        self.nav: dict[str, QPushButton] = {}
        group = QButtonGroup(self)
        group.setExclusive(True)
        for key, text in (("new", "New job"), ("jobs", "Jobs"), ("cluster", "Cluster"),
                          ("interactive", "Interactive"), ("settings", "Settings")):
            self.stack.addWidget(self.pages[key])
            b = QPushButton(text)
            b.setObjectName("nav")
            b.setCheckable(True)
            b.setCursor(Qt.PointingHandCursor)
            b.clicked.connect(lambda _=False, k=key: self.go(k))
            group.addButton(b)
            self.nav[key] = b
            sv.addWidget(b)
        sv.addStretch(1)
        self.pill = QLabel("● Not connected")
        self.pill.setObjectName("pill")
        self.pill.setWordWrap(True)
        self.pill.setCursor(Qt.PointingHandCursor)
        self.pill.mousePressEvent = lambda _e: self.go("settings")
        sv.addWidget(self.pill)
        self.set_pill(False)

        central = QWidget()
        h = QHBoxLayout(central)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(0)
        h.addWidget(side)
        h.addWidget(self.stack, 1)
        self.setCentralWidget(central)
        self.statusBar().setSizeGripEnabled(True)

        # compatibility aliases
        self.conn_tab, self.job_tab, self.jobs_tab = self.settings_page, self.job_page, self.jobs_page

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.poll)
        self.timer.start(POLL_MS)
        self.status_timer = QTimer(self)
        self.status_timer.timeout.connect(self.refresh_status)
        self.status_timer.start(STATUS_MS)

        p = self.profile
        if p["username"] and p["key_path"] and Path(p["key_path"]).expanduser().exists():
            self.go("new" if p.get("last_project") else "settings")
            QTimer.singleShot(200, self.connect_cluster)
        else:
            self.go("settings")

    def go(self, key: str):
        if key == "interactive":
            self.interactive_page.refresh()
        self.stack.setCurrentWidget(self.pages[key])
        self.nav[key].setChecked(True)

    def set_pill(self, ok: bool, text: str = ""):
        if ok:
            self.pill.setText(f"● {text}")
            self.pill.setStyleSheet(f"color:{C['ok']}; background:{C['ok_soft']};")
        else:
            self.pill.setText(f"● {text or 'Not connected'}")
            self.pill.setStyleSheet(f"color:{C['err']}; background:{C['err_soft']};")

    # tasks
    def run_task(self, fn, on_done=None, on_fail=None, on_progress=None):
        w = Worker(fn)
        s = w.signals
        self._signals.add(s)

        def done(r):
            self._signals.discard(s)
            if on_done:
                on_done(r)

        def failed(e):
            self._signals.discard(s)
            (on_fail or self.show_error)(e)

        if on_progress:
            s.progress.connect(on_progress)
        s.done.connect(done)
        s.failed.connect(failed)
        self.pool.start(w)

    def show_error(self, e):
        QMessageBox.critical(self, APP_TITLE, error_text(e))

    def save_profile(self):
        self.settings_page.read_into_profile()
        try:
            core.save_profile(self.profile)
        except OSError:
            log.exception("Could not save profile")

    # connection
    def connect_cluster(self, passphrase: str | None = None, accept: str | None = None):
        self.save_profile()
        self._passphrase = passphrase
        prof = dict(self.profile)
        t = self.settings_page
        t.connect_btn.setEnabled(False)
        t.status.setText("Connecting...")
        set_kind(t.status, "hint")
        self.set_pill(False, "Connecting...")
        self.run_task(lambda _p: self.conn.connect(prof, passphrase, accept),
                      on_done=self.connected, on_fail=lambda e: self.connect_failed(e))

    def connected(self, hostname: str):
        t = self.settings_page
        t.connect_btn.setEnabled(True)
        t.connect_btn.setText("Reconnect")
        t.status.setText(f"Connected to {hostname} - scratch: {self.conn.scratch}")
        set_kind(t.status, "ok")
        self.set_pill(True, f"{self.profile['username']} @ {hostname}")
        self.load_cluster_info()
        self.refresh_nas_status()
        self.interactive_page.load_info()
        self.poll(force=True)

    def connect_failed(self, e):
        t = self.settings_page
        t.connect_btn.setEnabled(True)
        self.set_pill(False)
        if isinstance(e, core.UnknownHostKey):
            box = QMessageBox(self)
            box.setWindowTitle(APP_TITLE)
            box.setIcon(QMessageBox.Warning)
            box.setText(f"First connection to {e.host}")
            box.setInformativeText(
                "This server is not one the app knows. Check that the fingerprint below matches "
                "the one published by the cluster's administrators before trusting it:\n\n"
                f"{e.key_type}\n{e.fingerprint}\n\n"
                "Trust this server? The app will remember it.")
            trust = box.addButton("Trust and connect", QMessageBox.AcceptRole)
            box.addButton("Cancel", QMessageBox.RejectRole)
            box.exec()
            if box.clickedButton() is trust:
                self.connect_cluster(getattr(self, "_passphrase", None), e.fingerprint)
                return
            t.status.setText(f"Not connected: {e.host} was not trusted.")
            set_kind(t.status, "warn")
            return
        if isinstance(e, core.PassphraseRequired):
            pw, ok = QInputDialog.getText(self, APP_TITLE, "Passphrase of your SSH key:",
                                          QLineEdit.Password)
            if ok and pw:
                self.connect_cluster(pw)
                return
        t.status.setText(error_text(e))
        set_kind(t.status, "warn")
        self.go("settings")

    # lab NAS (Kerberos ticket on Baobab)
    def show_nas_status(self, st: dict):
        self.nas_ok = st["valid"]
        lab = self.settings_page.nas_status
        if st["valid"]:
            lab.setText(f"Logged in to the NAS until {st['expires']}; renewed automatically "
                        f"until {st['renew_until']}.")
            set_kind(lab, "ok")
            self.settings_page.nas_btn.setText("Log in again")
        else:
            lab.setText("Not logged in to the NAS. You'll be asked for your ISIS password when "
                        "a job or the NAS browser needs it.")
            set_kind(lab, "hint")
            self.settings_page.nas_btn.setText("Log in to the NAS")

    def refresh_nas_status(self, renew: bool = False):
        if not self.conn.alive():
            return
        conn = self.conn

        def work(_p):
            if renew:
                core.krb_renew(conn)
            return core.krb_status(conn)

        def done(st):
            if renew:
                self.nas_renewed = time.time()
            self.show_nas_status(st)
        self.run_task(work, on_done=done, on_fail=lambda e: log.warning("NAS status: %s", e))

    def nas_login(self, then=None):
        if not self.conn.alive():
            QMessageBox.warning(self, APP_TITLE, "Connect to Baobab first.")
            return
        self.save_profile()
        user = self.profile["username"]
        pw, ok = QInputDialog.getText(
            self, APP_TITLE,
            f"ISIS password of {user}, to let Baobab access the lab NAS.\n"
            "It is passed to Kerberos on Baobab and never stored.", QLineEdit.Password)
        if not ok or not pw:
            return
        conn, realm = self.conn, self.profile["kerberos_realm"]
        self.settings_page.nas_status.setText("Logging in to the NAS...")

        def done(st):
            self.nas_renewed = time.time()
            self.show_nas_status(st)
            if then:
                then()

        def failed(e):
            self.show_nas_status({"valid": False})
            QMessageBox.warning(self, APP_TITLE, error_text(e))
        self.run_task(lambda _p: core.krb_login(conn, pw, realm), on_done=done, on_fail=failed)

    def require_nas(self, retry) -> bool:
        """True if the NAS can be used now; otherwise asks to log in, then calls retry."""
        if not self.conn.alive():
            QMessageBox.warning(self, APP_TITLE, "Connect to Baobab first.")
            return False
        if self.nas_ok:
            return True
        self.nas_login(then=retry)
        return False

    def load_cluster_info(self):
        if not self.conn.alive():
            return
        conn = self.conn

        def work(_p):
            return core.get_matlab_modules(conn), core.get_python_versions(conn)

        def done(res):
            matlab, python = res
            self.settings_page.fill_versions(matlab, python)
            if not self.profile.get("python_modules", "").endswith(self.profile["python_version"]):
                self.resolve_python()
            else:
                self.settings_page.show_python_line()

        self.run_task(work, on_done=done, on_fail=lambda e: log.warning("versions: %s", e))
        self.refresh_status()

    def refresh_status(self):
        if self.status_busy or not self.conn.alive():
            return
        self.status_busy = True
        conn = self.conn

        def done(parts):
            self.status_busy = False
            self.partitions = parts
            self.job_page.fill_partitions(parts)
            self.cluster_page.fill(parts)
            if not self.cluster_page.datasets:
                self.cluster_page.load_datasets()

        def failed(e):
            self.status_busy = False
            self.statusBar().showMessage("Could not read the cluster state: " + error_text(e),
                                         10_000)

        self.run_task(lambda _p: core.get_cluster_status(conn), on_done=done, on_fail=failed)

    def resolve_python(self):
        if not self.conn.alive():
            return
        ver, conn = self.profile["python_version"], self.conn

        def done(line):
            if self.profile["python_version"] == ver:
                self.profile["python_modules"] = line
                self.settings_page.show_python_line()
                self.save_profile()
        self.run_task(lambda _p: core.resolve_module_load(conn, ver), on_done=done,
                      on_fail=lambda e: None)

    # job monitoring
    def poll(self, force: bool = False):
        if self.polling or not self.conn.alive():
            return
        if self.nas_ok and time.time() - self.nas_renewed > 1800:   # keep the ticket fresh
            self.refresh_nas_status(renew=True)
        recs = [dict(j) for j in self.registry.jobs if j["state"] not in core.FINAL_STATES]
        if not recs:
            self.download_finished_jobs()
            return
        self.polling = True
        conn = self.conn

        def done(updates):
            self.polling = False
            for jid, up in updates.items():
                self.registry.update(jid, **up)
            self.jobs_page.updated.setText("updated " + QTime.currentTime().toString("HH:mm"))
            self.jobs_page.refresh_table()
            self.download_finished_jobs()

        def failed(e):
            self.polling = False
            self.statusBar().showMessage("Could not check jobs: " + error_text(e), 10_000)

        self.run_task(lambda _p: core.poll_jobs(conn, recs), on_done=done, on_fail=failed)

    def fetch_usage(self, job_id: str):
        self.registry.update(job_id, usage_checked=True)
        conn = self.conn
        rec = self.registry.get(job_id) or {}
        ids = ",".join(rec.get("chain_ids") or [job_id])

        def done(u):
            self.registry.update(job_id, usage=u)
            self.jobs_page.refresh_table()
            self.job_page.update_suggestion()
        self.run_task(lambda _p: core.job_usage(conn, ids), on_done=done,
                      on_fail=lambda e: log.warning("usage of %s: %s", job_id, e))

    def download_finished_jobs(self):
        if self.conn.alive():
            for j in list(self.registry.jobs):
                if j["state"] in core.FINAL_STATES and not j.get("usage_checked"):
                    self.fetch_usage(j["job_id"])
        if not self.profile.get("auto_download", True) or not self.conn.alive():
            return
        for j in list(self.registry.jobs):
            if j["state"] in core.FINAL_STATES and j.get("results_to_pc") is False \
                    and not j.get("downloaded"):
                self.registry.update(j["job_id"], downloaded=True, download_note="on the NAS")
                continue
            if (j["state"] in core.FINAL_STATES and not j.get("downloaded")
                    and not j.get("download_note") and j["job_id"] not in self.downloading):
                self.start_download(j["job_id"])

    def start_download(self, job_id: str, manual: bool = False):
        rec = self.registry.get(job_id)
        if not rec or job_id in self.downloading:
            return
        if not self.conn.alive():
            QMessageBox.warning(self, APP_TITLE, "Not connected to Baobab.")
            return
        self.downloading.add(job_id)
        self.jobs_page.refresh_table()
        conn, jp = self.conn, self.jobs_page
        rec = dict(rec)

        def progress(d):
            if "log" in d:
                jp.view.appendPlainText(f"[{job_id}] {d['log']}")
            else:
                show_progress(d, jp.phase, jp.bar, jp.file_label)

        def finish():
            self.downloading.discard(job_id)
            if not self.downloading:
                for w in (jp.bar, jp.phase, jp.file_label):
                    w.setVisible(False)
            jp.refresh_table()

        def done(reps):
            ok = all(r.ok for r in reps)
            bad = sum(len(r.mismatches) for r in reps)
            note = "" if ok else f"CHECKSUM MISMATCH in {bad} file(s) - retry the download"
            self.registry.update(job_id, downloaded=ok, download_note=note)
            finish()
            msg = (f"Job {job_id} ({rec['name']}): results downloaded and verified in "
                   f"{rec['results_local']}" if ok else f"Job {job_id}: {note}")
            jp.view.appendPlainText(msg)
            self.statusBar().showMessage(msg, 15_000)
            QApplication.alert(self)
            if not ok:
                QMessageBox.warning(self, APP_TITLE, msg)

        def failed(e):
            self.registry.update(job_id, download_note="download failed - retry")
            finish()
            jp.view.appendPlainText(f"[{job_id}] download failed: {error_text(e)}")
            if manual:
                self.show_error(e)

        if manual:
            self.registry.update(job_id, download_note="")
        self.run_task(lambda p: core.download_job(conn, rec, p), on_done=done,
                      on_fail=failed, on_progress=progress)

    def closeEvent(self, ev):
        if self.submitting or self.downloading:
            if QMessageBox.question(self, APP_TITLE, "Transfers are in progress and will be "
                                    "interrupted. Quit anyway?") != QMessageBox.Yes:
                ev.ignore()
                return
        self.save_profile()
        self.cache.save()
        self.conn.close()
        ev.accept()


# ── Entry point ───────────────────────────────────────────────────────────────
def setup_logging():
    core.APP_DIR.mkdir(parents=True, exist_ok=True)
    h = logging.handlers.RotatingFileHandler(core.LOG_FILE, maxBytes=1_000_000, backupCount=2,
                                             encoding="utf-8")
    h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    root = logging.getLogger()
    root.addHandler(h)
    root.setLevel(logging.INFO)
    logging.getLogger("paramiko").setLevel(logging.WARNING)


def qt_message(mode, _ctx, msg):
    level = {QtMsgType.QtFatalMsg: logging.CRITICAL, QtMsgType.QtCriticalMsg: logging.ERROR,
             QtMsgType.QtWarningMsg: logging.WARNING}.get(mode, logging.DEBUG)
    log.log(level, "Qt: %s", msg)
    if mode == QtMsgType.QtFatalMsg:
        native_error_box("Qt could not start the window:\n\n" + msg)


def mark_started():
    """Tells the launcher that the window opened."""
    try:
        (core.APP_DIR / "started.txt").write_text(time.strftime("%Y-%m-%d %H:%M:%S"))
    except OSError:
        pass


def main():
    setup_logging()
    qInstallMessageHandler(qt_message)
    log.info("Starting (Python %s, %s)", sys.version.split()[0], sys.executable)
    if os.name == "nt":   # own taskbar entry and icon instead of Python's
        try:
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("UNIGE.BaobabHPC")
        except Exception:
            pass
    app = QApplication(sys.argv)
    app.setApplicationName(APP_TITLE)
    app.setStyle("Fusion")
    app.setStyleSheet(build_style())
    if ICON_FILE.exists():
        app.setWindowIcon(QIcon(str(ICON_FILE)))

    lock = QLockFile(str(core.APP_DIR / "app.lock"))
    lock.setStaleLockTime(0)
    if not lock.tryLock(100):
        mark_started()
        QMessageBox.information(None, APP_TITLE, "Baobab HPC is already open.")
        return 0

    def excepthook(t, v, tb):
        log.error("Unhandled error", exc_info=(t, v, tb))
        QMessageBox.critical(None, APP_TITLE, "Unexpected error:\n\n"
                             + "".join(traceback.format_exception_only(t, v))
                             + f"\nDetails are in {core.LOG_FILE}")
    sys.excepthook = excepthook

    win = MainWindow()
    win.show()
    mark_started()
    log.info("Window open")
    code = app.exec()
    lock.unlock()
    return code


if __name__ == "__main__":
    try:
        sys.exit(main())
    except SystemExit:
        raise
    except BaseException:
        tb = traceback.format_exc()
        logging.getLogger("baobab").critical("Start-up failed\n%s", tb)
        native_error_box("Baobab HPC could not start:\n\n" + tb)
        sys.exit(1)
