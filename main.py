"""
Pillow Fight Scoring App
Single file PyQt6 application for live judging and scorekeeping.

Includes
• Editable fighter names with live update across the UI
• Three ninety second rounds and optional thirty second tiebreaker
• Timer with Start Pause Reset. Reset restores to the current round default
• Scoring buttons with keyboard shortcuts and Undo
• Event log with timestamp fighter round action and points
• Per round score table and running totals
• Open and Save as JSON in a scores folder

Run
pip install PyQt6
python pillow_scoring.py
"""
from __future__ import annotations

import json
import sys
import time
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import List, Optional

from PyQt6.QtCore import Qt, QTimer, QSize
from PyQt6.QtGui import QAction, QKeySequence, QTextDocument
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QGridLayout, QVBoxLayout, QHBoxLayout,
    QLabel, QLineEdit, QPushButton, QGroupBox, QMessageBox, QTableWidget,
    QTableWidgetItem, QToolBar, QStatusBar, QFileDialog, QHeaderView
)
from PyQt6.QtPrintSupport import QPrinter, QPrintDialog

# Storage
SCORE_DIR = Path.cwd() / "scores"
SCORE_DIR.mkdir(exist_ok=True)

# Durations
ROUND_SECONDS = 90
TIEBREAKER_SECONDS = 30

# Scoring map
SCORING_EVENTS = {
    "Head": 1,
    "360 Head": 3,
    "Knockdown": 5,
    "Leg Unbalanced": 1,
    "Pillow Break": 3,
}

ROUND_NAMES = ["Round 1", "Round 2", "Round 3", "Tiebreaker"]
ROUND_SHORT = ["R1", "R2", "R3", "TB"]

@dataclass
class Event:
    ts: float
    fighter: str  # "A" or "B"
    round_index: int  # 0..2, 3 for TB
    label: str
    points: int

    def to_row(self) -> list[str]:
        t = time.strftime("%H:%M:%S", time.localtime(self.ts))
        return [t, self.fighter, ROUND_SHORT[self.round_index], self.label, str(self.points)]

class TimerWidget(QWidget):
    def __init__(self, seconds: int = ROUND_SECONDS, parent=None):
        super().__init__(parent)
        self.default_seconds = int(seconds)
        self.remaining = int(seconds)
        self.timer = QTimer(self)
        self.timer.setInterval(1000)
        self.timer.timeout.connect(self.on_tick)

        self.display = QLabel(self.format_time(self.remaining))
        self.display.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.display.setStyleSheet("font-size:56px;font-weight:700;")

        self.start_btn = QPushButton("Start")
        self.pause_btn = QPushButton("Pause")
        self.reset_btn = QPushButton("Reset")
        self.start_btn.clicked.connect(self.start)
        self.pause_btn.clicked.connect(self.pause)
        self.reset_btn.clicked.connect(self.reset)

        layout = QVBoxLayout(self)
        layout.addWidget(self.display)
        btns = QHBoxLayout()
        btns.addWidget(self.start_btn)
        btns.addWidget(self.pause_btn)
        btns.addWidget(self.reset_btn)
        layout.addLayout(btns)

    @staticmethod
    def format_time(sec: int) -> str:
        m, s = divmod(max(0, int(sec)), 60)
        return f"{m:02d}:{s:02d}"

    def start(self):
        if self.remaining <= 0:
            self.remaining = self.default_seconds
            self.display.setText(self.format_time(self.remaining))
        if not self.timer.isActive() and self.remaining > 0:
            self.timer.start()

    def pause(self):
        self.timer.stop()

    def reset(self, seconds: Optional[int] = None):
        self.timer.stop()
        if seconds is not None:
            self.default_seconds = int(seconds)
            self.remaining = int(seconds)
        else:
            self.remaining = self.default_seconds
        self.display.setText(self.format_time(self.remaining))

    def on_tick(self):
        if self.remaining > 0:
            self.remaining -= 1
            self.display.setText(self.format_time(self.remaining))
        if self.remaining <= 0:
            self.timer.stop()

class FighterPanel(QGroupBox):
    def __init__(self, label: str, color: str, parent=None):
        super().__init__(label, parent)
        self.color = color
        self.total_label = QLabel("0")
        self.total_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.total_label.setStyleSheet(f"font-size:40px;font-weight:800;color:{color};")

        grid = QGridLayout()
        grid.addWidget(QLabel("Round Total"), 0, 0, 1, 2)
        grid.addWidget(self.total_label, 1, 0, 1, 2)

        self.buttons = {}
        r, c = 2, 0
        for name, pts in SCORING_EVENTS.items():
            btn = QPushButton(f"{name}\n+{pts}")
            btn.setProperty("event_name", name)
            btn.setProperty("points", pts)
            btn.setMinimumHeight(64)
            self.buttons[name] = btn
            grid.addWidget(btn, r, c)
            c += 1
            if c > 1:
                c = 0
                r += 1

        self.setLayout(grid)

    def set_total(self, value: int):
        self.total_label.setText(str(value))

class ScoreTable(QTableWidget):
    def __init__(self, parent=None):
        super().__init__(4, 3, parent)
        self.setHorizontalHeaderLabels(["A", "B", "Total"])
        self.setVerticalHeaderLabels(ROUND_NAMES)
        self.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        for r in range(4):
            for c in range(3):
                self.setItem(r, c, QTableWidgetItem("0"))

    def set_round_scores(self, round_index: int, a: int, b: int):
        self.item(round_index, 0).setText(str(a))
        self.item(round_index, 1).setText(str(b))
        self.item(round_index, 2).setText(str(a + b))

class EventTable(QTableWidget):
    def __init__(self, parent=None):
        super().__init__(0, 5, parent)
        self.setHorizontalHeaderLabels(["Time", "Fighter", "Round", "Action", "Pts"])
        self.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)

    def append_event(self, ev: Event):
        row = self.rowCount()
        self.insertRow(row)
        for col, val in enumerate(ev.to_row()):
            self.setItem(row, col, QTableWidgetItem(val))
        self.scrollToBottom()

    def load_events(self, events: List[Event]):
        self.setRowCount(0)
        for ev in events:
            self.append_event(ev)

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Pillow Fight Scoring")
        self.resize(1200, 780)

        # State
        self.current_round = 0  # 0..2, 3 for TB
        self.round_scores_a = [0, 0, 0, 0]
        self.round_scores_b = [0, 0, 0, 0]
        self.events: List[Event] = []
        self.has_tb = False

        # Header inputs
        self.judge_edit = QLineEdit()
        self.judge_edit.setPlaceholderText("Judge name")
        self.bout_edit = QLineEdit()
        self.bout_edit.setPlaceholderText("Bout ID")
        self.a_edit = QLineEdit()
        self.a_edit.setPlaceholderText("Fighter A name")
        self.b_edit = QLineEdit()
        self.b_edit.setPlaceholderText("Fighter B name")
        self.a_edit.textChanged.connect(self.update_names)
        self.b_edit.textChanged.connect(self.update_names)

        header = QHBoxLayout()
        header.addWidget(QLabel(""))
        header.addWidget(self.judge_edit)
        header.addWidget(QLabel(""))
        header.addWidget(self.bout_edit)
        header.addWidget(self.a_edit)
        header.addWidget(self.b_edit)

        # Timer and round controls
        self.timer = TimerWidget(ROUND_SECONDS)
        self.round_label = QLabel("Round 1 of 3")
        self.round_label.setStyleSheet("font-size:18px;font-weight:600;")
        self.prev_round_btn = QPushButton("Prev Round")
        self.prev_round_btn.clicked.connect(self.prev_round)
        self.next_round_btn = QPushButton("Next Round")
        self.next_round_btn.clicked.connect(self.next_round)
        self.tb_btn = QPushButton("Start Tiebreaker 30s")
        self.tb_btn.clicked.connect(self.start_tiebreaker)
        self.tb_btn.setEnabled(False)

        ctrls = QHBoxLayout()
        ctrls.addWidget(self.round_label)
        ctrls.addStretch(1)
        ctrls.addWidget(self.prev_round_btn)
        ctrls.addWidget(self.next_round_btn)
        ctrls.addWidget(self.tb_btn)

        # Fighter panels
        self.panel_a = FighterPanel("Fighter A", "#e53935")
        self.panel_b = FighterPanel("Fighter B", "#1e88e5")
        for name, btn in self.panel_a.buttons.items():
            btn.clicked.connect(lambda _, n=name: self.add_score("A", n))
        for name, btn in self.panel_b.buttons.items():
            btn.clicked.connect(lambda _, n=name: self.add_score("B", n))
        # Shortcuts
        self.panel_a.buttons["Head"].setShortcut("Q")
        self.panel_a.buttons["360 Head"].setShortcut("W")
        self.panel_a.buttons["Knockdown"].setShortcut("E")
        self.panel_a.buttons["Leg Unbalanced"].setShortcut("R")
        self.panel_a.buttons["Pillow Break"].setShortcut("T")
        self.panel_b.buttons["Head"].setShortcut("Y")
        self.panel_b.buttons["360 Head"].setShortcut("U")
        self.panel_b.buttons["Knockdown"].setShortcut("I")
        self.panel_b.buttons["Leg Unbalanced"].setShortcut("O")
        self.panel_b.buttons["Pillow Break"].setShortcut("P")

        # Tables and totals
        self.score_table = ScoreTable()
        self.event_table = EventTable()
        self.total_a_label = QLabel("0")
        self.total_b_label = QLabel("0")
        for lbl in (self.total_a_label, self.total_b_label):
            lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            lbl.setStyleSheet("font-size:28px;font-weight:700;")
        totals = QHBoxLayout()
        totals.addWidget(QLabel("Total A"))
        totals.addWidget(self.total_a_label)
        totals.addStretch(1)
        totals.addWidget(QLabel("Total B"))
        totals.addWidget(self.total_b_label)

        # Compose layouts
        left = QVBoxLayout()
        left.addLayout(header)
        panels = QHBoxLayout()
        panels.addWidget(self.panel_a)
        panels.addWidget(self.panel_b)
        left.addLayout(panels)

        right = QVBoxLayout()
        right.addWidget(self.timer)
        right.addLayout(ctrls)
        right.addWidget(self.score_table)
        right.addLayout(totals)
        right.addWidget(QLabel("Event Log"))
        right.addWidget(self.event_table)

        root = QHBoxLayout()
        left_container = QWidget()
        left_container.setLayout(left)
        right_container = QWidget()
        right_container.setLayout(right)
        root.addWidget(left_container, 1)
        root.addWidget(right_container, 1)

        central = QWidget()
        central.setLayout(root)
        self.setCentralWidget(central)

        # Toolbar
        self.setStatusBar(QStatusBar())
        tb = QToolBar("Main")
        tb.setIconSize(QSize(18, 18))
        self.addToolBar(tb)

        new_act = QAction("New", self)
        new_act.setShortcut("Ctrl+N")
        new_act.triggered.connect(self.new_match)
        open_act = QAction("Open", self)
        open_act.setShortcut(QKeySequence.StandardKey.Open)
        open_act.triggered.connect(self.open_match)
        save_act = QAction("Save", self)
        save_act.setShortcut(QKeySequence.StandardKey.Save)
        save_act.triggered.connect(self.save_match)
        undo_act = QAction("Undo", self)
        undo_act.setShortcut(QKeySequence.StandardKey.Undo)
        undo_act.triggered.connect(self.undo_last)

        tb.addAction(new_act)
        tb.addAction(open_act)
        tb.addAction(save_act)
        tb.addAction(undo_act)

        print_act = QAction("Print Score", self)
        print_act.triggered.connect(self.print_score)
        pdf_act = QAction("Save Score PDF", self)
        pdf_act.triggered.connect(self.export_score_pdf)
        tb.addAction(print_act)
        tb.addAction(pdf_act)

        self.refresh_scores()
        self.update_names()

    # Round helpers
    def round_name(self, idx: int) -> str:
        return ROUND_NAMES[idx]

    def set_round(self, idx: int):
        self.current_round = idx
        self.round_label.setText(self.round_name(idx) + ("" if idx < 3 else " 30s"))
        self.timer.reset(TIEBREAKER_SECONDS if idx == 3 else ROUND_SECONDS)
        self.refresh_scores()

    def next_round(self):
        if self.current_round < 2:
            self.set_round(self.current_round + 1)
        elif self.current_round == 2:
            QMessageBox.information(self, "Info", "Three rounds complete. Start tiebreaker if totals are tied.")

    def prev_round(self):
        if self.current_round > 0:
            self.set_round(self.current_round - 1)

    def start_tiebreaker(self):
        self.has_tb = True
        self.set_round(3)

    # Scoring
    def add_score(self, fighter: str, event_name: str):
        pts = SCORING_EVENTS[event_name]
        ev = Event(ts=time.time(), fighter=fighter, round_index=self.current_round, label=event_name, points=pts)
        self.events.append(ev)
        self.event_table.append_event(ev)
        if fighter == "A":
            self.round_scores_a[self.current_round] += pts
        else:
            self.round_scores_b[self.current_round] += pts
        self.refresh_scores()
        self.evaluate_tie_for_tb()

    def undo_last(self):
        if not self.events:
            return
        ev = self.events.pop()
        # remove last event row
        if self.event_table.rowCount() > 0:
            self.event_table.removeRow(self.event_table.rowCount() - 1)
        if ev.fighter == "A":
            self.round_scores_a[ev.round_index] -= ev.points
        else:
            self.round_scores_b[ev.round_index] -= ev.points
        self.refresh_scores()
        self.evaluate_tie_for_tb()

    def refresh_scores(self):
        for r in range(4):
            self.score_table.set_round_scores(r, self.round_scores_a[r], self.round_scores_b[r])
        total_a = sum(self.round_scores_a)
        total_b = sum(self.round_scores_b)
        self.total_a_label.setText(str(total_a))
        self.total_b_label.setText(str(total_b))
        self.panel_a.set_total(self.round_scores_a[self.current_round])
        self.panel_b.set_total(self.round_scores_b[self.current_round])

    def evaluate_tie_for_tb(self):
        a3 = sum(self.round_scores_a[:3])
        b3 = sum(self.round_scores_b[:3])
        self.tb_btn.setEnabled(self.current_round <= 2 and a3 == b3 and (a3 + b3) > 0)

    # File IO
    def to_payload(self) -> dict:
        return {
            "judge": self.judge_edit.text().strip(),
            "bout": self.bout_edit.text().strip(),
            "fighter_a": self.a_edit.text().strip() or "Fighter A",
            "fighter_b": self.b_edit.text().strip() or "Fighter B",
            "scores_a": self.round_scores_a,
            "scores_b": self.round_scores_b,
            "has_tb": self.has_tb,
            "events": [asdict(e) for e in self.events],
            "saved_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        }

    def from_payload(self, data: dict):
        self.judge_edit.setText(data.get("judge", ""))
        self.bout_edit.setText(data.get("bout", ""))
        self.a_edit.setText(data.get("fighter_a", "Fighter A"))
        self.b_edit.setText(data.get("fighter_b", "Fighter B"))
        sa = data.get("scores_a", [0, 0, 0, 0])
        sb = data.get("scores_b", [0, 0, 0, 0])
        self.round_scores_a = (sa + [0, 0, 0, 0])[:4]
        self.round_scores_b = (sb + [0, 0, 0, 0])[:4]
        self.has_tb = bool(data.get("has_tb", False))
        self.events = []
        for e in data.get("events", []):
            try:
                ev = Event(float(e["ts"]), str(e["fighter"]), int(e["round_index"]), str(e["label"]), int(e["points"]))
            except Exception:
                continue
            self.events.append(ev)
        self.event_table.load_events(self.events)
        # Default view to round 1 or tiebreaker depending on flag
        self.set_round(3 if self.has_tb else 0)
        self.refresh_scores()
        self.update_names()
        self.evaluate_tie_for_tb()

    def save_match(self):
        payload = self.to_payload()
        ts = time.strftime("%Y%m%d_%H%M%S")
        default_name = f"{ts}_{payload['fighter_a']}_vs_{payload['fighter_b']}.json"
        path, _ = QFileDialog.getSaveFileName(self, "Save Match", str(SCORE_DIR / default_name), "JSON Files (*.json)")
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(payload, f, indent=2)
            self.statusBar().showMessage(f"Saved {path}", 5000)
        except Exception as e:
            QMessageBox.critical(self, "Save Error", str(e))

    def open_match(self):
        path, _ = QFileDialog.getOpenFileName(self, "Open Match", str(SCORE_DIR), "JSON Files (*.json)")
        if not path:
            return
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            self.from_payload(data)
            self.statusBar().showMessage(f"Opened {path}", 5000)
        except Exception as e:
            QMessageBox.critical(self, "Open Error", str(e))

    def new_match(self):
        if self.timer.timer.isActive():
            self.timer.pause()
        if QMessageBox.question(self, "Confirm", "Start a new match. Unsaved data will be lost.") != QMessageBox.StandardButton.Yes:
            return
        self.current_round = 0
        self.round_scores_a = [0, 0, 0, 0]
        self.round_scores_b = [0, 0, 0, 0]
        self.events.clear()
        self.event_table.setRowCount(0)
        self.has_tb = False
        self.judge_edit.clear()
        self.bout_edit.clear()
        self.a_edit.clear()
        self.b_edit.clear()
        self.set_round(0)
        self.refresh_scores()
        self.update_names()
        self.evaluate_tie_for_tb()

    # Names
    def update_names(self):
        a = self.a_edit.text().strip() or "Fighter A"
        b = self.b_edit.text().strip() or "Fighter B"
        self.panel_a.setTitle(a)
        self.panel_b.setTitle(b)
        self.setWindowTitle(f"Pillow Fight Scoring  {a} vs {b}  {ROUND_NAMES[self.current_round]}")

    # Score sheet generation
    def build_score_html(self) -> str:
        a = self.a_edit.text().strip() or "Fighter A"
        b = self.b_edit.text().strip() or "Fighter B"
        judge = self.judge_edit.text().strip()
        bout = self.bout_edit.text().strip()
        r = self.round_scores_a
        s = self.round_scores_b
        total_a = sum(r)
        total_b = sum(s)
        winner = "Draw"
        if total_a > total_b:
            winner = a
        elif total_b > total_a:
            winner = b
        rows = "".join(
            f"<tr><td>{ROUND_NAMES[i]}</td><td style='text-align:center'>{r[i]}</td><td style='text-align:center'>{s[i]}</td></tr>"
            for i in range(4)
        )
        actions = "".join(
            f"<tr><td>{time.strftime('%H:%M:%S', time.localtime(ev.ts))}</td><td>{'A' if ev.fighter=='A' else 'B'}</td><td>{ROUND_SHORT[ev.round_index]}</td><td>{ev.label}</td><td style='text-align:center'>{ev.points}</td></tr>"
            for ev in self.events
        )
        html = f"""
        <html>
        <head>
            <meta charset='utf-8'>
            <style>
                body {{ font-family: Arial, sans-serif; }}
                h1 {{ text-align:center; margin-bottom:4px; }}
                h3 {{ text-align:center; margin-top:0; }}
                table {{ width:100%; border-collapse:collapse; margin-top:10px; }}
                th, td {{ border:1px solid #444; padding:6px; font-size:12pt; }}
                .totals {{ font-size:13pt; font-weight:bold; }}
            </style>
        </head>
        <body>
            <h1>Official Pillow Fight Score Sheet</h1>
            <h3>Bout {bout}</h3>
            <p><strong>Judge:</strong> {judge}</p>
            <p><strong>Fighters:</strong> {a} vs {b}</p>
            <table>
                <tr><th>Round</th><th>{a}</th><th>{b}</th></tr>
                {rows}
                <tr class='totals'><td>Total</td><td style='text-align:center'>{total_a}</td><td style='text-align:center'>{total_b}</td></tr>
                <tr><td colspan='3'><strong>Winner:</strong> {winner}</td></tr>
            </table>
            <h3>Event Log</h3>
            <table>
                <tr><th>Time</th><th>F</th><th>Rd</th><th>Action</th><th>Pts</th></tr>
                {actions}
            </table>
            <p style='margin-top:40px'>Judge Signature: ________________________________ Date: ____________</p>
        </body>
        </html>
        """
        return html

    def print_score(self):
        doc = QTextDocument()
        doc.setHtml(self.build_score_html())
        printer = QPrinter(QPrinter.PrinterMode.HighResolution)
        dialog = QPrintDialog(printer, self)
        dialog.setWindowTitle("Print Score Sheet")
        if dialog.exec():
            doc.print(printer)

    def export_score_pdf(self):
        path, _ = QFileDialog.getSaveFileName(self, "Save Score Sheet as PDF", str(SCORE_DIR / "score_sheet.pdf"), "PDF Files (*.pdf)")
        if not path:
            return
        printer = QPrinter(QPrinter.PrinterMode.HighResolution)
        printer.setOutputFormat(QPrinter.OutputFormat.PdfFormat)
        printer.setOutputFileName(path)
        doc = QTextDocument()
        doc.setHtml(self.build_score_html())
        doc.print(printer)


def main():
    app = QApplication(sys.argv)
    win = MainWindow()
    win.show()
    sys.exit(app.exec())

if __name__ == "__main__":
    main()
