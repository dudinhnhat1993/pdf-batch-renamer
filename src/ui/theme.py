"""Theme loader for PDF Batch Renamer.

Reads design/theme_tokens.json, renders src/ui/styles/theme.qss (@token@
placeholders) and applies it to the QApplication. Also exposes the raw token
dict for widgets that paint themselves (status badges, PDF canvas highlights).
"""

from __future__ import annotations

import json
import logging
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QColor, QFontDatabase

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[2]


def _find_tokens_path() -> Path:
    meipass = getattr(sys, "_MEIPASS", None)
    candidates = [
        ROOT / "design" / "theme_tokens.json",
        ROOT / "src" / "ui" / "styles" / "theme_tokens.json",
        Path(__file__).resolve().parent / "styles" / "theme_tokens.json",
        ROOT / "assets" / "theme_tokens.json",
    ]
    if meipass:
        candidates.insert(0, Path(meipass) / "design" / "theme_tokens.json")
        candidates.insert(1, Path(meipass) / "src" / "ui" / "styles" / "theme_tokens.json")
    for c in candidates:
        if c.exists():
            return c
    return candidates[0]


def _find_qss_path() -> Path:
    meipass = getattr(sys, "_MEIPASS", None)
    candidates = [
        Path(__file__).resolve().parent / "styles" / "theme.qss",
        ROOT / "src" / "ui" / "styles" / "theme.qss",
    ]
    if meipass:
        candidates.insert(0, Path(meipass) / "src" / "ui" / "styles" / "theme.qss")
    for c in candidates:
        if c.exists():
            return c
    return candidates[0]


def _find_font_dir() -> Path:
    meipass = getattr(sys, "_MEIPASS", None)
    candidates = [
        ROOT / "assets" / "fonts",
        Path(__file__).resolve().parent.parent / "assets" / "fonts",
    ]
    if meipass:
        candidates.insert(0, Path(meipass) / "assets" / "fonts")
    for c in candidates:
        if c.exists():
            return c
    return candidates[0]


_PLACEHOLDER = re.compile(r"@([a-z0-9_]+)@")


def qcolor(value: str | QColor) -> QColor:
    """Accept '#rrggbb', 'rgba(r,g,b,a)', 'rgb(r,g,b)' or QColor and return a valid QColor."""
    if isinstance(value, QColor):
        return value
    if not value:
        return QColor(0, 0, 0, 0)
    value = str(value).strip()
    if value.startswith("rgba"):
        try:
            r, g, b, a = [p.strip() for p in value[value.index("(") + 1 : value.rindex(")")].split(",")]
            alpha_val = float(a)
            alpha_int = round(alpha_val * 255) if alpha_val <= 1.0 else int(alpha_val)
            return QColor(int(r), int(g), int(b), max(0, min(255, alpha_int)))
        except Exception:
            return QColor(2, 132, 199, 45)
    elif value.startswith("rgb"):
        try:
            r, g, b = [p.strip() for p in value[value.index("(") + 1 : value.rindex(")")].split(",")]
            return QColor(int(r), int(g), int(b), 255)
        except Exception:
            return QColor(2, 132, 199, 255)
    try:
        col = QColor(value)
        if col.isValid():
            return col
    except Exception:
        pass
    return QColor(2, 132, 199, 45)


@dataclass
class Theme(QObject):
    mode: str = "light"
    tokens: dict[str, Any] = field(default_factory=dict)

    changed = Signal(str)

    def __post_init__(self) -> None:
        QObject.__init__(self)

    # ------------------------------------------------------------------ load
    @classmethod
    def load(cls, mode: str = "light", tokens_path: Path | None = None) -> Theme:
        p = tokens_path or _find_tokens_path()
        try:
            tokens = json.loads(p.read_text(encoding="utf-8"))
        except Exception as exc:
            logger.warning("Không đọc được %s (%s) — dùng cấu hình fallback", p, exc)
            tokens = {}
        cls._register_fonts()
        if mode not in tokens.get("themes", {}):
            mode = "light"
        return cls(mode=mode, tokens=tokens)

    @staticmethod
    def _register_fonts() -> None:
        font_dir = _find_font_dir()
        if not font_dir.exists():
            return
        for ttf in font_dir.glob("*.ttf"):
            QFontDatabase.addApplicationFont(str(ttf))

    # ------------------------------------------------------------- accessors
    @property
    def palette(self) -> dict[str, Any]:
        return self.tokens.get("themes", {}).get(self.mode, {})

    def color(self, path: str, default: str = "#ff00ff") -> str:
        """Dotted lookup inside the active palette: color('status.error.fg')."""
        node: Any = self.palette
        for part in path.split("."):
            if not isinstance(node, dict) or part not in node:
                return default
            node = node[part]
        return node if isinstance(node, str) else default

    def qcolor(self, path: str) -> QColor:
        return qcolor(self.color(path))

    def status(self, code: str) -> dict[str, str]:
        """code: PENDING | PROCESSING | SUCCESS | DUPLICATE | ERROR (case-insensitive)."""
        key = str(code).strip().upper()
        # Fallback mapping
        status_map = self.tokens.get("status_map", {
            "PENDING": {"token": "pending", "label": "Chờ"},
            "PROCESSING": {"token": "processing", "label": "Đang xử lý"},
            "SUCCESS": {"token": "success", "label": "Thành công"},
            "DUPLICATE": {"token": "duplicate", "label": "Trùng lặp"},
            "ERROR": {"token": "error", "label": "Lỗi"},
        })
        meta = status_map.get(key, {"token": key.lower(), "label": key})
        token_name = meta.get("token", "pending")
        spec = dict(self.palette.get("status", {}).get(token_name, {
            "fg": "#58a6ff", "bg": "rgba(88,166,255,0.15)", "border": "rgba(88,166,255,0.35)"
        }))
        spec["label"] = meta.get("label", key)
        return spec

    def metric(self, name: str) -> Any:
        return self.tokens.get("metrics", {}).get(name, 0)

    # ----------------------------------------------------------------- apply
    def _flat_vars(self) -> dict[str, str]:
        p = self.palette
        flat: dict[str, str] = {k: v for k, v in p.items() if isinstance(v, str)}
        try:
            from src.core.config import assets_dir
            flat["check_icon"] = (assets_dir() / "icons" / "check_white.svg").as_posix()
            flat["radio_icon"] = (assets_dir() / "icons" / "radio_white.svg").as_posix()
        except Exception:
            flat["check_icon"] = ""
            flat["radio_icon"] = ""
        for group in ("status", "log", "pdf_canvas"):
            for key, val in p.get(group, {}).items():
                if isinstance(val, dict):
                    for sub, subval in val.items():
                        flat[f"{group}_{key}_{sub}"] = subval
                else:
                    flat[f"{group}_{key}"] = val
        for key, val in self.tokens.get("radius", {}).items():
            flat[f"radius_{key}"] = str(val)
        for key, val in self.tokens.get("space", {}).items():
            flat[f"space_{key}"] = str(val)
        for key, val in self.tokens.get("font", {}).items():
            flat[key] = str(val)
        for key, val in self.tokens.get("metrics", {}).items():
            if isinstance(val, (int, float)):
                flat[key] = str(int(val))
        return flat

    def stylesheet(self, qss_path: Path | None = None) -> str:
        p = qss_path or _find_qss_path()
        if not p.exists():
            return ""
        template = p.read_text(encoding="utf-8")
        variables = self._flat_vars()
        missing: set[str] = set()

        def repl(match: re.Match[str]) -> str:
            key = match.group(1)
            if key not in variables:
                missing.add(key)
                return match.group(0)
            return variables[key]

        rendered = _PLACEHOLDER.sub(repl, template)
        if missing:
            logger.warning("theme.qss tham chiếu token chưa định nghĩa: %s", sorted(missing))
        return rendered

    def apply(self, app) -> None:
        app.setStyleSheet(self.stylesheet())
        app.setProperty("themeMode", self.mode)
        self.changed.emit(self.mode)

    def set_mode(self, mode: str) -> None:
        if mode not in self.tokens.get("themes", {}):
            mode = "light"
        self.mode = mode


def repolish(widget) -> None:
    """Call after changing a dynamic QSS property (variant/state/selected...)."""
    if widget and hasattr(widget, "style"):
        style = widget.style()
        if style:
            style.unpolish(widget)
            style.polish(widget)
        widget.update()
