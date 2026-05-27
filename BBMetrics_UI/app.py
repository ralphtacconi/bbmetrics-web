from __future__ import annotations

import ctypes
import ctypes.wintypes
import csv
import io
import os
import sys
import time
from contextlib import redirect_stdout
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

from PySide6 import QtCore, QtGui, QtWidgets

from bbmetrics_dc.client import BitbucketDCClient
from BBMetrics_UI.bb_api import ProjectChoice, RepoChoice, list_projects, list_repos_in_project

_PROGRESS_MARKER = "__BBMETRICS_PROGRESS__"
_STAGE_MARKER = "__BBMETRICS_STAGE__"


def _set_windows_appusermodelid(app_id: str) -> None:
    if sys.platform != "win32":
        return
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(app_id)
    except Exception:
        pass


def apply_modern_theme(app: QtWidgets.QApplication, *, dark: bool = True) -> None:
    app.setStyle("Fusion")

    if dark:
        palette = QtGui.QPalette()
        palette.setColor(QtGui.QPalette.Window, QtGui.QColor("#0f172a"))
        palette.setColor(QtGui.QPalette.WindowText, QtGui.QColor("#222831"))         # mais escuro
        palette.setColor(QtGui.QPalette.Base, QtGui.QColor("#0b1220"))
        palette.setColor(QtGui.QPalette.AlternateBase, QtGui.QColor("#111827"))
        palette.setColor(QtGui.QPalette.ToolTipBase, QtGui.QColor("#111827"))
        palette.setColor(QtGui.QPalette.ToolTipText, QtGui.QColor("#222831"))
        palette.setColor(QtGui.QPalette.Text, QtGui.QColor("#222831"))
        palette.setColor(QtGui.QPalette.Button, QtGui.QColor("#111827"))
        palette.setColor(QtGui.QPalette.ButtonText, QtGui.QColor("#222831"))        # mais escuro
        palette.setColor(QtGui.QPalette.BrightText, QtGui.QColor("#ffffff"))
        palette.setColor(QtGui.QPalette.Highlight, QtGui.QColor("#2563eb"))
        palette.setColor(QtGui.QPalette.HighlightedText, QtGui.QColor("#ffffff"))
        palette.setColor(QtGui.QPalette.Link, QtGui.QColor("#60a5fa"))
        app.setPalette(palette)

    app.setStyleSheet(
        """
        QWidget { font-size: 12px; }
        QGroupBox {
            border: 1px solid rgba(148, 163, 184, 0.25);
            border-radius: 6px;
            margin-top: 5px;
            padding: 6px;
        }
        QGroupBox::title {
            subcontrol-origin: margin;
            left: 8px;
            padding: 0 4px;
            color: rgba(55, 65, 81, 0.95);
            font-weight: 600;
        }

        QLabel#muted { color: rgba(55, 65, 81, 0.85); }

        QLineEdit, QComboBox, QListWidget, QPlainTextEdit, QTableWidget {
            border: 1px solid rgba(148, 163, 184, 0.25);
            border-radius: 5px;
            padding: 4px 7px;
            background: rgba(2, 6, 23, 0.20);
        }
        QLineEdit:focus, QComboBox:focus, QListWidget:focus, QPlainTextEdit:focus, QTableWidget:focus {
            border: 1px solid rgba(37, 99, 235, 0.9);
        }

        QPushButton {
            border: 1px solid rgba(148, 163, 184, 0.25);
            border-radius: 5px;
            padding: 5px 10px;
            background: rgba(2, 6, 23, 0.22);
        }
        QPushButton:hover { border-color: rgba(148, 163, 184, 0.40); }
        QPushButton:pressed { background: rgba(2, 6, 23, 0.35); }
        QPushButton:disabled { color: rgba(55, 65, 81, 0.32); border-color: rgba(148, 163, 184, 0.10); }

        QPushButton#primary {
            background: rgba(37, 99, 235, 0.90);
            border-color: rgba(37, 99, 235, 1.0);
            color: white;
            font-weight: 700;
        }
        QPushButton#primary:hover { background: rgba(29, 78, 216, 0.95); }
        QPushButton#primary:pressed { background: rgba(30, 64, 175, 1.0); }

        QProgressBar {
            border: 1px solid rgba(148, 163, 184, 0.25);
            border-radius: 5px;
            text-align: center;
            height: 18px;
            background: rgba(2, 6, 23, 0.15);
        }
        QProgressBar::chunk { background: rgba(37, 99, 235, 0.93); border-radius: 5px; }
        """
    )

def _fmt_duration(seconds: float) -> str:
    seconds = max(0.0, float(seconds))
    total = int(round(seconds))
    h = total // 3600
    m = (total % 3600) // 60
    s = total % 60
    if h:
        return f"{h}h {m}m {s}s"
    if m:
        return f"{m}m {s}s"
    return f"{s}s"


def assets_dir() -> Path:
    return Path(__file__).resolve().parent / "assets"


def app_icon() -> QtGui.QIcon:
    ico = assets_dir() / "app.ico"
    if ico.exists():
        return QtGui.QIcon(str(ico))
    return QtGui.QIcon()


def _app_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def _find_users_csv() -> Path:
    base = _app_base_dir()
    candidates = [
        base / "in" / "users.csv",
        base.parent / "in" / "users.csv",
        base.parent.parent / "in" / "users.csv",
    ]
    for p in candidates:
        if p.exists():
            return p
    return candidates[0]


def _load_users_csv(path: Path) -> Tuple[List[str], List[str], Dict[str, List[str]]]:
    if not path.exists():
        raise FileNotFoundError(f"users.csv not found: {path}")

    users: Set[str] = set()
    groups: Set[str] = set()
    group_to_users: Dict[str, Set[str]] = {}

    with path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        if not reader.fieldnames:
            raise ValueError("users.csv missing header row")

        fieldnames = [fn.strip().lower() for fn in reader.fieldnames]
        if "user" not in fieldnames or "group" not in fieldnames:
            raise ValueError("users.csv must have columns: user,group")

        user_col = reader.fieldnames[fieldnames.index("user")]
        group_col = reader.fieldnames[fieldnames.index("group")]

        for row in reader:
            u = (row.get(user_col) or "").strip()
            g = (row.get(group_col) or "").strip()
            if not u or not g:
                continue
            users.add(u)
            groups.add(g)
            group_to_users.setdefault(g, set()).add(u)

    group_to_users_list: Dict[str, List[str]] = {g: sorted(list(us)) for g, us in group_to_users.items()}
    return sorted(list(users)), sorted(list(groups)), group_to_users_list


_MUTEX_HANDLE = None


def _acquire_single_instance_mutex(name: str) -> bool:
    global _MUTEX_HANDLE
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

    CreateMutexW = kernel32.CreateMutexW
    CreateMutexW.argtypes = [ctypes.wintypes.LPVOID, ctypes.wintypes.BOOL, ctypes.wintypes.LPCWSTR]
    CreateMutexW.restype = ctypes.wintypes.HANDLE

    GetLastError = kernel32.GetLastError
    GetLastError.argtypes = []
    GetLastError.restype = ctypes.wintypes.DWORD

    ERROR_ALREADY_EXISTS = 183

    h = CreateMutexW(None, False, name)
    if not h:
        return True
    _MUTEX_HANDLE = h

    if GetLastError() == ERROR_ALREADY_EXISTS:
        return False
    return True


class ProjectsWorker(QtCore.QThread):
    line = QtCore.Signal(str)
    loaded = QtCore.Signal(list)
    failed = QtCore.Signal(str)

    def __init__(self, client: BitbucketDCClient):
        super().__init__()
        self.client = client

    def run(self) -> None:
        try:
            self.line.emit("Loading projects...")
            self.loaded.emit(list_projects(self.client))
        except Exception as e:
            self.failed.emit(repr(e))


class ReposWorker(QtCore.QThread):
    line = QtCore.Signal(str)
    loaded = QtCore.Signal(list)
    failed = QtCore.Signal(str)

    def __init__(self, client: BitbucketDCClient, project_key: str):
        super().__init__()
        self.client = client
        self.project_key = project_key

    def run(self) -> None:
        try:
            self.line.emit(f"Loading repos for project {self.project_key}...")
            self.loaded.emit(list_repos_in_project(self.client, self.project_key))
        except Exception as e:
            self.failed.emit(repr(e))


class _LineEmitter(io.TextIOBase):
    def __init__(self, emit_line):
        super().__init__()
        self._emit_line = emit_line
        self._buf = ""

    def write(self, s) -> int:
        if not s:
            return 0
        if isinstance(s, (bytes, bytearray)):
            s = s.decode("utf-8", errors="replace")
        else:
            s = str(s)

        self._buf += s
        while "\n" in self._buf:
            line, self._buf = self._buf.split("\n", 1)
            if line:
                self._emit_line(line)
        return len(s)

    def flush(self) -> None:
        if self._buf:
            self._emit_line(self._buf)
            self._buf = ""


class CliWorker(QtCore.QThread):
    line = QtCore.Signal(str)
    progress = QtCore.Signal(int)
    stage = QtCore.Signal(str)
    finished_ok = QtCore.Signal(float)
    finished_err = QtCore.Signal(str, float)

    def __init__(
        self,
        *,
        env: dict,
        project_key: str,
        out_dir: str,
        user: Optional[str],
        repos: Optional[List[str]],
        pr_start: Optional[str],
        pr_end: Optional[str],
        include_comment_text: bool,
        enable_diffstat: bool,
        log_file: Optional[str],
        output_mode: str,
        pr_states: str,
        activities_limit: int,
        date_field: str,
    ):
        super().__init__()
        self.env = env
        self.project_key = project_key
        self.out_dir = out_dir
        self.user = user
        self.repos = repos
        self.pr_start = pr_start
        self.pr_end = pr_end
        self.include_comment_text = include_comment_text
        self.enable_diffstat = enable_diffstat
        self.log_file = log_file
        self.output_mode = output_mode
        self.pr_states = pr_states
        self.activities_limit = activities_limit
        self.date_field = date_field

    def _handle_marker_or_log(self, ln: str) -> None:
        s = (ln or "").strip()
        if not s:
            return

        if s.startswith(_STAGE_MARKER):
            txt = s[len(_STAGE_MARKER):].strip()
            if txt:
                self.stage.emit(txt)
            return

        if s.startswith(_PROGRESS_MARKER):
            rest = s[len(_PROGRESS_MARKER):].strip()
            parts = rest.split()
            if len(parts) >= 2:
                try:
                    cur = int(parts[0])
                    total = int(parts[1])
                    total = max(1, total)
                    pct = int(round((cur / total) * 100.0))
                    self.progress.emit(max(0, min(100, pct)))
                except Exception:
                    pass
            return

        self.line.emit(ln)

    def run(self) -> None:
        t0 = time.perf_counter()
        try:
            self.stage.emit("Initializing...")
            self.progress.emit(0)

            os.environ.update(self.env)
            self.stage.emit("Preparing environment...")
            self.progress.emit(1)

            emitter = _LineEmitter(lambda ln: self._handle_marker_or_log(ln))
            with redirect_stdout(emitter):
                import bbmetrics_dc.cli as cli_mod

                cli_mod.scan(
                    project_key=self.project_key,
                    out=self.out_dir,
                    user=self.user,
                    repos=self.repos,
                    pr_start=self.pr_start,
                    pr_end=self.pr_end,
                    log_file=self.log_file,
                    include_comment_text=self.include_comment_text,
                    enable_diffstat=self.enable_diffstat,
                    output_mode=self.output_mode,
                    pr_states=self.pr_states,
                    activities_limit=self.activities_limit,
                    date_field=self.date_field,
                )

            emitter.flush()
            self.stage.emit("Done.")
            self.progress.emit(100)

            dt = time.perf_counter() - t0
            self.finished_ok.emit(dt)
        except Exception:
            import traceback

            self.stage.emit("Error.")
            self.progress.emit(100)
            dt = time.perf_counter() - t0
            self.finished_err.emit(traceback.format_exc(), dt)


try:
    from PySide6 import QtCharts  # type: ignore

    _HAS_CHARTS = True
except Exception:
    QtCharts = None  # type: ignore
    _HAS_CHARTS = False


def _read_csv_dicts(path: Path) -> List[Dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        return [dict(r) for r in csv.DictReader(f)]


def _to_float_or_none(v: object) -> Optional[float]:
    if v is None:
        return None
    s = str(v).strip()
    if not s or s.upper() == "NA":
        return None
    try:
        return float(s)
    except Exception:
        return None


class ChartsTab(QtWidgets.QWidget):
    def __init__(self, out_dir: str, parent: Optional[QtWidgets.QWidget] = None):
        super().__init__(parent)
        self.out_dir = Path(out_dir)

        self.users_rows = _read_csv_dicts(self.out_dir / "users_summary.csv")
        self.groups_rows = _read_csv_dicts(self.out_dir / "groups_summary.csv")

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        top = QtWidgets.QHBoxLayout()
        layout.addLayout(top)

        self.dataset_combo = QtWidgets.QComboBox()
        self.dataset_combo.addItems(["Users", "Groups"])
        if not self.groups_rows:
            self.dataset_combo.setCurrentIndex(0)

        self.entity_combo = QtWidgets.QComboBox()

        top.addWidget(QtWidgets.QLabel("Dataset:"))
        top.addWidget(self.dataset_combo)
        top.addSpacing(10)
        top.addWidget(QtWidgets.QLabel("Filter:"))
        top.addWidget(self.entity_combo, 1)

        self.hint = QtWidgets.QLabel("")
        self.hint.setObjectName("muted")
        layout.addWidget(self.hint)

        if not _HAS_CHARTS:
            self.hint.setText("Charts are not available (PySide6.QtCharts not installed in this build).")
            return

        self.chart_view = QtCharts.QChartView()
        self.chart_view.setRenderHint(QtGui.QPainter.Antialiasing, True)
        layout.addWidget(self.chart_view, 3)

        self.table = QtWidgets.QTableWidget()
        self.table.setColumnCount(4)
        self.table.setHorizontalHeaderLabels(
            ["Repo", "Avg PR open (min)", "Avg to first review (min)", "Avg to first approval (min)"]
        )
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        layout.addWidget(self.table, 2)

        self.dataset_combo.currentIndexChanged.connect(self._reload_entities)
        self.entity_combo.currentIndexChanged.connect(self._render)
        self._reload_entities()

    def _reload_entities(self) -> None:
        ds = (self.dataset_combo.currentText() or "").strip().lower()
        self.entity_combo.blockSignals(True)
        try:
            self.entity_combo.clear()
            self.entity_combo.addItem("All", "__ALL__")
            if ds == "groups":
                entities = sorted(
                    {(r.get("group") or "").strip() for r in self.groups_rows if (r.get("group") or "").strip()}
                )
            else:
                entities = sorted({(r.get("user") or "").strip() for r in self.users_rows if (r.get("user") or "").strip()})
            for e in entities:
                self.entity_combo.addItem(e, e)
        finally:
            self.entity_combo.blockSignals(False)
        self._render()

    def _rows_filtered(self) -> List[Dict[str, str]]:
        ds = (self.dataset_combo.currentText() or "").strip().lower()
        key = "group" if ds == "groups" else "user"
        data = self.groups_rows if ds == "groups" else self.users_rows
        sel = self.entity_combo.currentData()
        if not sel or sel == "__ALL__":
            return list(data)
        return [r for r in data if (r.get(key) or "").strip() == str(sel)]

    def _render(self) -> None:
        if not _HAS_CHARTS:
            return
        rows = self._rows_filtered()
        if not rows:
            self.hint.setText("No data found in summaries.")
            self.chart_view.setChart(QtCharts.QChart())
            self.table.setRowCount(0)
            return

        by_repo: Dict[str, Dict[str, Optional[float]]] = {}
        for r in rows:
            repo = (r.get("repo") or "").strip() or "UNKNOWN"
            by_repo.setdefault(repo, {})
            by_repo[repo]["open"] = _to_float_or_none(r.get("avg_pr_time_open_minutes"))
            by_repo[repo]["review"] = _to_float_or_none(r.get("avg_time_to_first_review_minutes"))
            by_repo[repo]["approval"] = _to_float_or_none(r.get("avg_time_to_first_approval_minutes"))

        repos = sorted(by_repo.keys())
        self.table.setRowCount(len(repos))

        def fmt(v: Optional[float]) -> str:
            return "" if v is None else f"{v:.3f}"

        for i, repo in enumerate(repos):
            self.table.setItem(i, 0, QtWidgets.QTableWidgetItem(repo))
            self.table.setItem(i, 1, QtWidgets.QTableWidgetItem(fmt(by_repo[repo].get("open"))))
            self.table.setItem(i, 2, QtWidgets.QTableWidgetItem(fmt(by_repo[repo].get("review"))))
            self.table.setItem(i, 3, QtWidgets.QTableWidgetItem(fmt(by_repo[repo].get("approval"))))
        self.table.resizeColumnsToContents()

        series_open = QtCharts.QBarSet("Avg PR open time (min)")
        series_review = QtCharts.QBarSet("Avg time to first review (min)")
        series_approval = QtCharts.QBarSet("Avg time to first approval (min)")

        missing_review = 0
        missing_approval = 0
        for repo in repos:
            v_open = by_repo[repo].get("open")
            v_review = by_repo[repo].get("review")
            v_approval = by_repo[repo].get("approval")

            series_open.append(float(v_open or 0.0))
            if v_review is None:
                missing_review += 1
                series_review.append(0.0)
            else:
                series_review.append(float(v_review))
            if v_approval is None:
                missing_approval += 1
                series_approval.append(0.0)
            else:
                series_approval.append(float(v_approval))

        chart = QtCharts.QChart()
        chart.setTitle("Summary metrics by repo")

        bar_series = QtCharts.QBarSeries()
        bar_series.append(series_open)
        bar_series.append(series_review)
        bar_series.append(series_approval)
        chart.addSeries(bar_series)
        chart.setAnimationOptions(QtCharts.QChart.SeriesAnimations)

        axis_x = QtCharts.QBarCategoryAxis()
        axis_x.append(repos)
        axis_x.setLabelsAngle(-45)
        chart.addAxis(axis_x, QtCore.Qt.AlignBottom)
        bar_series.attachAxis(axis_x)

        axis_y = QtCharts.QValueAxis()
        axis_y.setTitleText("Minutes")
        chart.addAxis(axis_y, QtCore.Qt.AlignLeft)
        bar_series.attachAxis(axis_y)

        chart.legend().setVisible(True)
        chart.legend().setAlignment(QtCore.Qt.AlignBottom)
        self.chart_view.setChart(chart)

        self.hint.setText(
            f"Repos: {len(repos)} | Missing review avg: {missing_review} | Missing approval avg: {missing_approval} "
            "(missing values shown as 0 in chart)"
        )


class MainWindow(QtWidgets.QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("BBMetrics UI")
        self.setWindowIcon(app_icon())

        self.resize(1100, 900)
        self.setMinimumSize(950, 720)

        self.connected: bool = False
        self._connected_client: Optional[BitbucketDCClient] = None

        self.projects: List[ProjectChoice] = []
        self.repos: List[RepoChoice] = []

        self.projects_worker: Optional[ProjectsWorker] = None
        self.repos_worker: Optional[ReposWorker] = None
        self.scan_worker: Optional[CliWorker] = None

        self.users_csv_path: Path = _find_users_csv()
        self.users_all: List[str] = []
        self.groups_all: List[str] = []
        self.group_to_users: Dict[str, List[str]] = {}

        self.tabs = QtWidgets.QTabWidget()
        self.setCentralWidget(self.tabs)

        self.scan_tab = QtWidgets.QWidget()
        self.tabs.addTab(self.scan_tab, "Scan")

        outer_layout = QtWidgets.QVBoxLayout(self.scan_tab)
        outer_layout.setContentsMargins(0, 0, 0, 0)
        outer_layout.setSpacing(0)

        self.scroll = QtWidgets.QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QtWidgets.QFrame.NoFrame)
        outer_layout.addWidget(self.scroll)

        content = QtWidgets.QWidget()
        self.scroll.setWidget(content)

        root = QtWidgets.QVBoxLayout(content)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(12)
        root.setAlignment(QtCore.Qt.AlignTop)

        container = QtWidgets.QWidget()
        container.setMaximumWidth(1100)
        container_layout = QtWidgets.QVBoxLayout(container)
        container_layout.setContentsMargins(0, 0, 0, 0)
        container_layout.setSpacing(12)

        center_row = QtWidgets.QHBoxLayout()
        center_row.addStretch(1)
        center_row.addWidget(container, 0)
        center_row.addStretch(1)
        root.addLayout(center_row)

        title_row = QtWidgets.QHBoxLayout()
        title = QtWidgets.QLabel("Bitbucket Metrics")
        title_font = QtGui.QFont()
        title_font.setPointSize(14)
        title_font.setBold(True)
        title.setFont(title_font)
        title_row.addWidget(title)

        self.conn_dot = QtWidgets.QLabel("●")
        dot_font = QtGui.QFont()
        dot_font.setPointSize(14)
        dot_font.setBold(True)
        self.conn_dot.setFont(dot_font)

        self.conn_text = QtWidgets.QLabel("disconnected")
        self.conn_text.setObjectName("muted")
        self.conn_text.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)

        title_row.addSpacing(10)
        title_row.addWidget(self.conn_dot)
        title_row.addWidget(self.conn_text)
        title_row.addStretch(1)
        container_layout.addLayout(title_row)

        self.gb_auth = QtWidgets.QGroupBox("Credentials / Connection")
        auth_layout = QtWidgets.QFormLayout(self.gb_auth)
        auth_layout.setLabelAlignment(QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter)
        auth_layout.setHorizontalSpacing(10)
        auth_layout.setVerticalSpacing(10)

        self.base_url = QtWidgets.QLineEdit(os.getenv("BITBUCKET_BASE_URL", "https://git.rdisoftware.com:8443"))
        auth_layout.addRow("Base URL:", self.base_url)

        self.bb_user = QtWidgets.QLineEdit()
        auth_layout.addRow("BITBUCKET_USERNAME:", self.bb_user)

        self.bb_pass = QtWidgets.QLineEdit()
        self.bb_pass.setEchoMode(QtWidgets.QLineEdit.Password)
        self.bb_pass.returnPressed.connect(self.on_connect_clicked)
        auth_layout.addRow("BITBUCKET_PASSWORD (token):", self.bb_pass)

        self.btn_load = QtWidgets.QPushButton("Connect BitBucket Server")
        self.btn_load.setObjectName("primary")
        self.btn_load.clicked.connect(self.on_connect_clicked)
        self.btn_load.setMaximumWidth(260)
        auth_layout.addRow("", self.btn_load)
        container_layout.addWidget(self.gb_auth)

        self.gb_sel = QtWidgets.QGroupBox("Selection")
        sel_layout = QtWidgets.QFormLayout(self.gb_sel)
        sel_layout.setLabelAlignment(QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter)
        sel_layout.setHorizontalSpacing(10)
        sel_layout.setVerticalSpacing(10)

        self.project_combo = QtWidgets.QComboBox()
        self.project_combo.currentIndexChanged.connect(self.on_project_changed)
        sel_layout.addRow("Project:", self.project_combo)

        self.repos_list = QtWidgets.QListWidget()
        self.repos_list.setSelectionMode(QtWidgets.QAbstractItemView.MultiSelection)
        self.repos_list.setMinimumHeight(140)
        sel_layout.addRow("Repos (multi):", self.repos_list)
        container_layout.addWidget(self.gb_sel)

        self.gb_filters = QtWidgets.QGroupBox("Filters")
        filters_layout = QtWidgets.QFormLayout(self.gb_filters)
        filters_layout.setLabelAlignment(QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter)
        filters_layout.setHorizontalSpacing(10)
        filters_layout.setVerticalSpacing(10)

        user_filter_box = QtWidgets.QVBoxLayout()
        user_filter_top = QtWidgets.QHBoxLayout()

        self.user_mode = QtWidgets.QComboBox()
        self.user_mode.addItems(["user", "group"])
        self.user_mode.currentIndexChanged.connect(self.on_user_mode_changed)

        self.user_csv_hint = QtWidgets.QLabel(f"Source: {self.users_csv_path}")
        self.user_csv_hint.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)
        self.user_csv_hint.setObjectName("muted")

        user_filter_top.addWidget(QtWidgets.QLabel("Mode:"))
        user_filter_top.addWidget(self.user_mode, 0)
        user_filter_top.addSpacing(12)
        user_filter_top.addWidget(self.user_csv_hint, 1)

        self.user_search = QtWidgets.QLineEdit()
        self.user_search.setPlaceholderText("Search (contains)...")
        self.user_search.textChanged.connect(self.populate_user_list)

        user_filter_actions = QtWidgets.QHBoxLayout()
        self.btn_user_select_all = QtWidgets.QPushButton("Select all")
        self.btn_user_clear = QtWidgets.QPushButton("Clear")
        self.btn_user_select_all.clicked.connect(self.select_all_user_list)
        self.btn_user_clear.clicked.connect(self.clear_user_list_selection)
        self.btn_user_select_all.setMaximumWidth(120)
        self.btn_user_clear.setMaximumWidth(120)
        user_filter_actions.addWidget(self.btn_user_select_all)
        user_filter_actions.addWidget(self.btn_user_clear)
        user_filter_actions.addStretch(1)

        self.user_list = QtWidgets.QListWidget()
        self.user_list.setSelectionMode(QtWidgets.QAbstractItemView.MultiSelection)
        self.user_list.setMinimumHeight(170)

        user_filter_box.addLayout(user_filter_top)
        user_filter_box.addWidget(self.user_search)
        user_filter_box.addLayout(user_filter_actions)
        user_filter_box.addWidget(self.user_list)

        filters_layout.addRow("User/Group (PR author):", user_filter_box)

        dates_row = QtWidgets.QHBoxLayout()
        self.pr_start = QtWidgets.QLineEdit()
        self.pr_start.setInputMask("99-99-9999")
        self.pr_start.setPlaceholderText("MM-DD-YYYY")

        self.pr_end = QtWidgets.QLineEdit()
        self.pr_end.setInputMask("99-99-9999")
        self.pr_end.setPlaceholderText("MM-DD-YYYY")

        dates_row.addWidget(QtWidgets.QLabel("PR Start:"), 0)
        dates_row.addWidget(self.pr_start, 1)
        dates_row.addSpacing(10)
        dates_row.addWidget(QtWidgets.QLabel("PR End:"), 0)
        dates_row.addWidget(self.pr_end, 1)

        filters_layout.addRow("", dates_row)

        self.ignore_epic_prs = QtWidgets.QCheckBox("ignore Epic prs")
        self.ignore_epic_prs.setChecked(True)
        filters_layout.addRow("", self.ignore_epic_prs)

        container_layout.addWidget(self.gb_filters)

        self.gb_run = QtWidgets.QGroupBox("Run / Output")
        run_layout = QtWidgets.QFormLayout(self.gb_run)
        run_layout.setLabelAlignment(QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter)
        run_layout.setHorizontalSpacing(10)
        run_layout.setVerticalSpacing(10)

        out_row = QtWidgets.QHBoxLayout()
        self.out_dir = QtWidgets.QLineEdit(os.path.abspath("./out"))
        self.btn_out = QtWidgets.QPushButton("Browse...")
        self.btn_out.clicked.connect(self.pick_out_dir)
        self.btn_out.setMaximumWidth(120)
        out_row.addWidget(self.out_dir, 1)
        out_row.addWidget(self.btn_out, 0)
        run_layout.addRow("Output dir:", out_row)

        self.enable_diffstat = QtWidgets.QCheckBox("Enable diffstat (lines/files changed per commit) - SLOW")
        self.enable_diffstat.setChecked(False)
        run_layout.addRow("", self.enable_diffstat)

        self.output_mode = QtWidgets.QComboBox()
        self.output_mode.addItems(["Summaries", "Full"])
        self.output_mode.setCurrentIndex(1)
        run_layout.addRow("Output mode:", self.output_mode)

        self.pr_states = QtWidgets.QComboBox()
        self.pr_states.addItems(["MERGED only (fast)", "ALL (OPEN,MERGED,DECLINED)"])
        self.pr_states.setCurrentIndex(0)
        run_layout.addRow("PR state(s):", self.pr_states)

        self.activities_limit = QtWidgets.QComboBox()
        self.activities_limit.addItems(["25", "50", "100", "200", "ALL"])
        self.activities_limit.setCurrentText("50")
        run_layout.addRow("Activities per PR:", self.activities_limit)

        self.show_charts = QtWidgets.QCheckBox("Show charts after run")
        self.show_charts.setChecked(False)
        run_layout.addRow("", self.show_charts)

        btns = QtWidgets.QHBoxLayout()
        self.btn_run = QtWidgets.QPushButton("Run")
        self.btn_run.setObjectName("primary")
        self.btn_run.clicked.connect(self.on_run)
        self.btn_run.setMaximumWidth(120)

        self.btn_open = QtWidgets.QPushButton("Open Output Folder")
        self.btn_open.clicked.connect(self.open_out_dir)
        self.btn_open.setMaximumWidth(170)

        btns.addWidget(self.btn_run)
        btns.addWidget(self.btn_open)
        btns.addStretch(1)
        run_layout.addRow("", btns)
        container_layout.addWidget(self.gb_run)

        status_row = QtWidgets.QHBoxLayout()
        self.status_label = QtWidgets.QLabel("Ready.")
        self.status_label.setObjectName("muted")
        status_row.addWidget(self.status_label)
        status_row.addStretch(1)
        container_layout.addLayout(status_row)

        self.progress = QtWidgets.QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.setVisible(False)
        container_layout.addWidget(self.progress)

        self.gb_log = QtWidgets.QGroupBox("Log")
        log_layout = QtWidgets.QVBoxLayout(self.gb_log)
        self.log = QtWidgets.QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setPlaceholderText("Scan logs will appear here...")
        log_layout.addWidget(self.log)
        container_layout.addWidget(self.gb_log)

        self._lock_widgets = [self.gb_auth, self.gb_sel, self.gb_filters, self.gb_run]

        self._set_connected(False)
        self._clear_project_repo_ui()
        self.reload_users_csv()

    # --- connection indicator helpers ---
    def _set_connected(self, connected: bool) -> None:
        self.connected = bool(connected)
        if self.connected:
            self.conn_dot.setStyleSheet("color: #22c55e;")
            self.conn_text.setText("connected")
        else:
            self.conn_dot.setStyleSheet("color: #ef4444;")
            self.conn_text.setText("disconnected")

    def _clear_project_repo_ui(self) -> None:
        self.projects = []
        self.repos = []
        self.project_combo.blockSignals(True)
        try:
            self.project_combo.clear()
            self.project_combo.addItem("(select a project...)", "")
            self.project_combo.setCurrentIndex(0)
        finally:
            self.project_combo.blockSignals(False)
        self.repos_list.clear()

    # --- log / progress helpers ---
    def append_log(self, s: str) -> None:
        self.log.appendPlainText(s)
        sb = self.log.verticalScrollBar()
        sb.setValue(sb.maximum())

    def set_loading(self, loading: bool) -> None:
        self.progress.setVisible(loading)
        self.btn_load.setEnabled(not loading)
        self.project_combo.setEnabled(not loading)
        self.repos_list.setEnabled(not loading)

    def set_running(self, running: bool) -> None:
        self.progress.setVisible(running)
        if not running:
            self.progress.setRange(0, 100)
            self.progress.setValue(0)
            self.status_label.setText("Ready.")

        for w in self._lock_widgets:
            w.setEnabled(not running)

        self.gb_log.setEnabled(True)
        self.log.setEnabled(True)
        self.log.setReadOnly(True)

        self.btn_open.setEnabled(True)
        self.btn_run.setEnabled(not running)

    def on_stage(self, text: str) -> None:
        self.status_label.setText(text)
        t = (text or "").lower()
        if "listing prs" in t or "loading repos" in t:
            if self.progress.minimum() != 0 or self.progress.maximum() != 0:
                self.progress.setRange(0, 0)
        elif "processing prs" in t:
            if self.progress.minimum() == 0 and self.progress.maximum() == 0:
                self.progress.setRange(0, 100)

    def on_progress(self, val: int) -> None:
        if self.progress.minimum() == 0 and self.progress.maximum() == 0:
            return
        self.progress.setValue(max(0, min(100, int(val))))

    # --- users.csv ---
    def reload_users_csv(self) -> None:
        try:
            users, groups, group_to_users = _load_users_csv(self.users_csv_path)
            self.users_all = users
            self.groups_all = groups
            self.group_to_users = group_to_users
            self.user_csv_hint.setText(f"Source: {self.users_csv_path} (users={len(users)} groups={len(groups)})")
            self.populate_user_list()
        except Exception as e:
            self.users_all = []
            self.groups_all = []
            self.group_to_users = {}
            self.user_list.clear()
            self.user_csv_hint.setText(f"Source: {self.users_csv_path} (ERROR: {e})")
            self.append_log(f"WARNING: failed to load users.csv: {e!r}")

    def on_user_mode_changed(self, _idx: int) -> None:
        self.user_search.setText("")
        self.populate_user_list()

    def populate_user_list(self) -> None:
        mode = (self.user_mode.currentText() or "").strip().lower()
        q = (self.user_search.text() or "").strip().lower()
        selected_before = {i.text() for i in self.user_list.selectedItems()}
        self.user_list.clear()
        items = self.groups_all if mode == "group" else self.users_all
        for v in items:
            if q and q not in v.lower():
                continue
            it = QtWidgets.QListWidgetItem(v)
            self.user_list.addItem(it)
            if v in selected_before:
                it.setSelected(True)

    def select_all_user_list(self) -> None:
        self.user_list.selectAll()

    def clear_user_list_selection(self) -> None:
        self.user_list.clearSelection()

    def selected_filter_values(self) -> List[str]:
        vals: List[str] = []
        for item in self.user_list.selectedItems():
            t = (item.text() or "").strip()
            if t:
                vals.append(t)
        return vals

    def resolve_selected_users_for_scan(self) -> List[str]:
        mode = (self.user_mode.currentText() or "").strip().lower()
        selected = self.selected_filter_values()
        if not selected:
            return []
        if mode == "group":
            users: Set[str] = set()
            for g in selected:
                for u in self.group_to_users.get(g, []):
                    users.add(u)
            return sorted(list(users))
        return selected

    # --- output dir ---
    def pick_out_dir(self) -> None:
        d = QtWidgets.QFileDialog.getExistingDirectory(self, "Choose output directory", self.out_dir.text())
        if d:
            self.out_dir.setText(d)

    def open_out_dir(self) -> None:
        d = self.out_dir.text().strip()
        if d:
            os.startfile(d)

    # --- API client/env ---
    def _client(self) -> BitbucketDCClient:
        base_url = self.base_url.text().strip()
        u = self.bb_user.text().strip()
        p = self.bb_pass.text()
        if not base_url or not u or not p:
            raise ValueError("Please fill Base URL, BITBUCKET_USERNAME and BITBUCKET_PASSWORD.")
        return BitbucketDCClient(base_url=base_url, username=u, password=p)

    def build_env(self) -> dict:
        base_url = self.base_url.text().strip()
        u = self.bb_user.text().strip()
        p = self.bb_pass.text()
        if not base_url or not u or not p:
            raise ValueError("Please fill Base URL, BITBUCKET_USERNAME and BITBUCKET_PASSWORD.")
        env = os.environ.copy()
        env["BITBUCKET_BASE_URL"] = base_url
        env["BITBUCKET_USERNAME"] = u
        env["BITBUCKET_PASSWORD"] = p
        env["BBMETRICS_FILTER_MODE"] = (self.user_mode.currentText() or "").strip().lower()
        env["BBMETRICS_USERS_CSV"] = str(self.users_csv_path)
        env["BBMETRICS_IGNORE_EPIC_PRS"] = "1" if self.ignore_epic_prs.isChecked() else "0"
        return env

    # --- connect ---
    def on_connect_clicked(self) -> None:
        if self.projects_worker and self.projects_worker.isRunning():
            return
        if self.repos_worker and self.repos_worker.isRunning():
            return

        self._set_connected(False)
        self._connected_client = None
        self._clear_project_repo_ui()

        try:
            client = self._client()
        except Exception as e:
            QtWidgets.QMessageBox.critical(self, "Error", str(e))
            return

        self.set_loading(True)
        self.append_log("Starting load...")

        self.projects_worker = ProjectsWorker(client)
        self.projects_worker.line.connect(self.append_log)
        self.projects_worker.loaded.connect(self.on_projects_loaded)
        self.projects_worker.failed.connect(self.on_api_err)
        self.projects_worker.start()

    def on_projects_loaded(self, projects: list) -> None:
        self._connected_client = self._client()
        self._set_connected(True)

        self.projects = list(projects or [])
        self.project_combo.blockSignals(True)
        try:
            self.project_combo.clear()
            self.project_combo.addItem("(select a project...)", "")
            for p in self.projects:
                self.project_combo.addItem(f"{p.key} - {p.name}", p.key)
            self.project_combo.setCurrentIndex(0)  # do not auto-select first
        finally:
            self.project_combo.blockSignals(False)

        self.append_log(f"Projects loaded: {len(self.projects)}")
        self.set_loading(False)

    def on_project_changed(self, _idx: int) -> None:
        if not self.connected:
            return
        if not self.projects:
            return
        if self.repos_worker and self.repos_worker.isRunning():
            return

        project_key = self.project_combo.currentData()
        if not project_key:
            self.repos_list.clear()
            self.repos = []
            return

        self.load_repos_for_selected_project()

    def load_repos_for_selected_project(self) -> None:
        try:
            client = self._client()
        except Exception:
            self.set_loading(False)
            return

        project_key = self.project_combo.currentData()
        if not project_key:
            self.set_loading(False)
            return

        if self.repos_worker and self.repos_worker.isRunning():
            return

        self.repos_list.clear()
        self.repos = []
        self.set_loading(True)

        self.repos_worker = ReposWorker(client, project_key=str(project_key))
        self.repos_worker.line.connect(self.append_log)
        self.repos_worker.loaded.connect(self.on_repos_loaded)
        self.repos_worker.failed.connect(self.on_api_err)
        self.repos_worker.start()

    def on_repos_loaded(self, repos: list) -> None:
        self.repos = list(repos or [])
        self.repos_list.clear()
        for r in self.repos:
            item = QtWidgets.QListWidgetItem(f"{r.slug} - {r.name}")
            item.setData(QtCore.Qt.UserRole, r.slug)
            self.repos_list.addItem(item)
        self.append_log(f"Repos loaded: {len(self.repos)}")
        self.set_loading(False)

    def on_api_err(self, msg: str) -> None:
        self.append_log("ERROR: " + msg)
        self.set_loading(False)
        self._set_connected(False)
        self._connected_client = None
        QtWidgets.QMessageBox.critical(self, "API Error", msg)

    # --- scan helpers ---
    def selected_repo_slugs(self) -> List[str]:
        slugs: List[str] = []
        for item in self.repos_list.selectedItems():
            slug = item.data(QtCore.Qt.UserRole)
            if slug:
                slugs.append(slug)
        return slugs

    def clear_scan_log(self, out_dir: str) -> None:
        try:
            p = Path(out_dir) / "scan.log"
            if p.exists():
                p.unlink()
                self.append_log(f"Cleared log: {p}")
        except Exception as e:
            self.append_log(f"WARNING: could not clear scan.log: {e!r}")

    def _parse_date(self, s: str) -> datetime:
        return datetime.strptime(s, "%m-%d-%Y")

    def build_scan_params(self) -> dict:
        project_key = self.project_combo.currentData()
        if not project_key:
            raise ValueError("Select a project (connect first).")

        out_dir = self.out_dir.text().strip() or "./out"

        selected_users = self.resolve_selected_users_for_scan()
        if not selected_users:
            mode = (self.user_mode.currentText() or "user").strip().lower()
            raise ValueError(f"Select at least one {mode} in the list.")
        user = ",".join(selected_users)

        repo_slugs = self.selected_repo_slugs()
        if not repo_slugs:
            raise ValueError("Select at least one repository in Repos (multi).")

        pr_start = self.pr_start.text().strip()
        if not pr_start or pr_start == "--  -    ":
            raise ValueError("Fill PR Start (MM-DD-YYYY).")

        pr_end = self.pr_end.text().strip()
        if not pr_end or pr_end == "--  -    ":
            raise ValueError("Fill PR End (MM-DD-YYYY).")

        try:
            d1 = self._parse_date(pr_start)
            d2 = self._parse_date(pr_end)
        except Exception:
            raise ValueError("Invalid dates. Use MM-DD-YYYY (e.g. 03-13-2026).")
        if d2 < d1:
            raise ValueError("PR End must be greater than or equal to PR Start.")

        output_mode = (self.output_mode.currentText() or "").strip().lower()
        if output_mode == "full":
            output_mode = "completo"
        if output_mode not in ("summaries", "completo"):
            output_mode = "completo"

        merged_only = self.pr_states.currentIndex() == 0
        pr_states = "MERGED" if merged_only else "OPEN,MERGED,DECLINED"
        date_field = "closed" if merged_only else "created"

        sel = (self.activities_limit.currentText() or "").strip().upper()
        if sel == "ALL":
            activities_limit = -1
        else:
            try:
                activities_limit = int(sel or "50")
            except Exception:
                activities_limit = 50

        return {
            "project_key": str(project_key),
            "out_dir": out_dir,
            "user": user,
            "repos": repo_slugs,
            "pr_start": pr_start,
            "pr_end": pr_end,
            "include_comment_text": False,
            "enable_diffstat": self.enable_diffstat.isChecked(),
            "log_file": None,
            "output_mode": output_mode,
            "pr_states": pr_states,
            "activities_limit": activities_limit,
            "date_field": date_field,
        }

    # --- run ---
    def on_run(self) -> None:
        if self.scan_worker and self.scan_worker.isRunning():
            return

        # charts tab mgmt (same behavior as original)
        self.remove_charts_tab()
        self.tabs.setCurrentWidget(self.scan_tab)

        try:
            env = self.build_env()
            params = self.build_scan_params()
        except Exception as e:
            QtWidgets.QMessageBox.critical(self, "Error", str(e))
            return

        self.clear_scan_log(params["out_dir"])

        self.append_log(
            f"RUN: project={params['project_key']} out={params['out_dir']} "
            f"user={params['user'] or ''} repos={','.join(params['repos'] or [])} "
            f"pr_start={params['pr_start'] or ''} pr_end={params['pr_end'] or ''} "
            f"mode={params['output_mode']} pr_states={params['pr_states']} "
            f"activities_limit={params['activities_limit']} date_field={params['date_field']}"
        )
        self.append_log("Running...")

        self.set_running(True)
        self.on_stage("Initializing...")
        self.on_progress(0)

        self.scan_worker = CliWorker(env=env, **params)
        self.scan_worker.line.connect(self.append_log)
        self.scan_worker.stage.connect(self.on_stage)
        self.scan_worker.progress.connect(self.on_progress)
        self.scan_worker.finished_ok.connect(self.on_ok)
        self.scan_worker.finished_err.connect(self.on_err)
        self.scan_worker.start()

    def on_ok(self, duration_s: float) -> None:
        self.set_running(False)
        self.append_log(f"Done. Duration: {_fmt_duration(duration_s)}")

        if self.show_charts.isChecked():
            out_dir = self.out_dir.text().strip()
            if out_dir:
                self.add_charts_tab(out_dir)

        QtWidgets.QMessageBox.information(
            self,
            "Done",
            f"CSVs generated in:\n{self.out_dir.text()}\n\nDuration: {_fmt_duration(duration_s)}",
        )

    def on_err(self, msg: str, duration_s: float) -> None:
        self.set_running(False)
        self.append_log(f"ERROR (after {_fmt_duration(duration_s)}):\n{msg}")
        QtWidgets.QMessageBox.critical(self, "Error", f"Duration: {_fmt_duration(duration_s)}\n\n{msg}")

    # --- charts tab mgmt (from original) ---
    def remove_charts_tab(self) -> None:
        for i in range(self.tabs.count()):
            if self.tabs.tabText(i) == "Charts":
                w = self.tabs.widget(i)
                self.tabs.removeTab(i)
                if w:
                    w.deleteLater()
                break

    def add_charts_tab(self, out_dir: str) -> None:
        self.remove_charts_tab()
        tab = ChartsTab(out_dir, parent=self.tabs)
        self.tabs.addTab(tab, "Charts")
        self.tabs.setCurrentWidget(tab)

    def closeEvent(self, event: QtGui.QCloseEvent) -> None:
        for t in (self.projects_worker, self.repos_worker, self.scan_worker):
            if t and t.isRunning():
                t.requestInterruption()
                t.wait(2000)
        super().closeEvent(event)


def main() -> None:
    if not _acquire_single_instance_mutex(r"Global\\BBMetrics_UI_SingleInstance"):
        return

    _set_windows_appusermodelid("com.bbmetrics.ui")

    app = QtWidgets.QApplication([])
    icon = app_icon()
    app.setWindowIcon(icon)
    apply_modern_theme(app, dark=True)

    w = MainWindow()
    w.setWindowIcon(icon)
    w.show()
    app.exec()


if __name__ == "__main__":
    main()