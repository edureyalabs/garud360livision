# garud360/ui/theme.py
"""Application palette and Qt style sheet (dark control-room theme using the Garud navy/blue brand colours)."""
from __future__ import annotations

from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import QApplication

C = {
    "bg": "#0E1322", "panel": "#161D33", "panel2": "#1D2644", "border": "#2A3560", "text": "#E7EAF6",
    "muted": "#98A2C3", "accent": "#4F6BED", "accent_hi": "#7088FF", "navy": "#1B2B6B",
    "ok": "#2FBF71", "warn": "#F2B632", "crit": "#F0524F", "info": "#4FA3F7", "off": "#6B7394",
}

# status text -> colour key
STATUS_KIND = {
    "CLEAR": "ok", "STARTING": "warn", "PERSON DETECTED": "crit", "CAMERA FAULT": "crit",
    "LATCHED - RESET REQUIRED": "crit", "PAUSED": "warn", "NO LOAD - AI OFF": "info", "STOPPED": "off",
}


def color(key: str) -> QColor:
    return QColor(C[key])


def status_color(status: str) -> str:
    return C[STATUS_KIND.get(status, "off")]


STYLE = f"""
* {{ font-family: 'Segoe UI', 'Inter', 'Roboto', sans-serif; font-size: 13px; color: {C['text']}; }}
QMainWindow, QDialog, QWidget#page {{ background: {C['bg']}; }}
QWidget {{ background: transparent; }}
QDialog, QMessageBox {{ background: {C['bg']}; }}
QLabel#h1 {{ font-size: 22px; font-weight: 600; }}
QLabel#h2 {{ font-size: 16px; font-weight: 600; }}
QLabel#muted, QLabel[muted="true"] {{ color: {C['muted']}; }}
QFrame#card, QFrame#panel {{ background: {C['panel']}; border: 1px solid {C['border']}; border-radius: 10px; }}
QFrame#card:hover {{ border-color: {C['accent']}; }}
QFrame#nav {{ background: {C['panel']}; border-right: 1px solid {C['border']}; }}
QPushButton {{ background: {C['panel2']}; border: 1px solid {C['border']}; border-radius: 6px; padding: 7px 14px; }}
QPushButton:hover {{ border-color: {C['accent']}; background: #232E55; }}
QPushButton:pressed {{ background: {C['navy']}; }}
QPushButton:disabled {{ color: {C['off']}; border-color: #222a49; background: #141a2e; }}
QPushButton#primary {{ background: {C['accent']}; border-color: {C['accent']}; color: white; font-weight: 600; }}
QPushButton#primary:hover {{ background: {C['accent_hi']}; }}
QPushButton#danger {{ background: #8E2B2B; border-color: #B83B3B; color: white; }}
QPushButton#danger:hover {{ background: #B83B3B; }}
QPushButton#ok {{ background: #1E7A4C; border-color: {C['ok']}; color: white; font-weight: 600; }}
QPushButton#ok:hover {{ background: #249A5F; }}
QPushButton#nav {{ text-align: left; padding: 11px 16px; border: none; border-radius: 8px; background: transparent; }}
QPushButton#nav:hover {{ background: {C['panel2']}; }}
QPushButton#nav:checked {{ background: {C['navy']}; border-left: 3px solid {C['accent_hi']}; font-weight: 600; }}
QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox, QTextEdit, QPlainTextEdit, QDateEdit {{
    background: #0B101E; border: 1px solid {C['border']}; border-radius: 6px; padding: 6px 8px;
    selection-background-color: {C['accent']}; }}
QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus {{ border-color: {C['accent_hi']}; }}
QLineEdit:disabled, QSpinBox:disabled, QDoubleSpinBox:disabled, QComboBox:disabled {{ color: {C['off']}; }}
QComboBox QAbstractItemView {{ background: {C['panel']}; border: 1px solid {C['border']};
    selection-background-color: {C['navy']}; }}
QCheckBox {{ spacing: 8px; }}
QCheckBox::indicator {{ width: 18px; height: 18px; border: 1px solid {C['border']}; border-radius: 4px; background: #0B101E; }}
QCheckBox::indicator:checked {{ background: {C['accent']}; border-color: {C['accent_hi']}; }}
QTableWidget, QListWidget, QTreeWidget {{ background: {C['panel']}; border: 1px solid {C['border']}; border-radius: 8px;
    gridline-color: #232c4f; alternate-background-color: #19213b; selection-background-color: {C['navy']}; }}
QHeaderView::section {{ background: {C['panel2']}; border: none; border-bottom: 1px solid {C['border']}; padding: 7px; font-weight: 600; }}
QTabWidget::pane {{ border: 1px solid {C['border']}; border-radius: 8px; background: {C['panel']}; top: -1px; }}
QTabBar::tab {{ background: transparent; padding: 9px 16px; border-bottom: 2px solid transparent; color: {C['muted']}; }}
QTabBar::tab:selected {{ color: {C['text']}; border-bottom: 2px solid {C['accent_hi']}; }}
QScrollArea {{ border: none; }}
QScrollBar:vertical {{ background: transparent; width: 12px; }}
QScrollBar::handle:vertical {{ background: {C['border']}; border-radius: 5px; min-height: 30px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; width: 0; }}
QScrollBar:horizontal {{ background: transparent; height: 12px; }}
QScrollBar::handle:horizontal {{ background: {C['border']}; border-radius: 5px; min-width: 30px; }}
QToolTip {{ background: {C['panel2']}; color: {C['text']}; border: 1px solid {C['border']}; padding: 5px; }}
QTextBrowser {{ background: {C['panel']}; border: 1px solid {C['border']}; border-radius: 8px; padding: 10px; }}
QProgressBar {{ background: #0B101E; border: 1px solid {C['border']}; border-radius: 5px; height: 10px; text-align: center; }}
QProgressBar::chunk {{ background: {C['accent']}; border-radius: 4px; }}
"""


def apply(app: QApplication) -> None:
    app.setStyle("Fusion")
    f = QFont("Segoe UI", 10)
    app.setFont(f)
    app.setStyleSheet(STYLE)
