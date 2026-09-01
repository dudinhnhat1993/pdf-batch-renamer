"""Theme loader for PDF Batch Renamer.

Reads design/theme_tokens.json, renders src/ui/styles/theme.qss (@token@
placeholders) and applies it to the QApplication. Also exposes the raw token
dict for widgets that paint themselves (status badges, PDF canvas highlights).

Usage
-----
    from src.ui.theme import Theme

    app = QApplication(sys.argv)
    theme = Theme.load(mode="dark")      # "dark" | "light"
    theme.apply(app)
    ...
    theme.set_mode("light"); theme.apply(app)   # live switch, no restart
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QColor, QFontDatabase

ROOT = Path(__file__).resolve().parents[2]
TOKENS_PATH = ROOT / "design" / "theme_tokens.json"
QSS_PATH = Path(__file__).resolve().parent / "styles" / "theme.qss"
FONT_DIR = ROOT / "assets" / "fonts"

_PLACEHOLDER = re.compile(r"@([a-z0-9_]+)@")


def qcolor(value: str) -> QColor:
    """Accept '#rrggbb' or 'rgba(r,g,b,a)' (a in 0..1) and return a QColor."""
    value = value.strip()
    if value.startswith("rgba"):
        r, g, b, a = [p.strip() for p in value[value.index("(") + 1: value.rindex(")")].split(",")]
        return QColor(int(r), int(g), int(b), round(float(a) * 255))
    return QColor(value)


@dataclass
class Theme(QObject):
    mode: str = "dark"
    tokens: dict[str, Any] = field(default_factory=dict)

    changed = Signal(str)

    def __post_init__(self) -> None:
        QObject.__init__(self)

    # ------------------------------------------------------------------ load
    @classmethod
    def load(cls, mode: str = "dark", tokens_path: Path = TOKENS_PATH) -> "Theme":
        tokens = json.loads(tokens_path.read_text(encoding="utf-8"))
        cls._register_fonts()
        return cls(mode=mode, tokens=tokens)

    @staticmethod
    def _register_fonts() -> None:
        if not FONT_DIR.exists():
            return
        for ttf in FONT_DIR.glob("*.ttf"):
            QFontDatabase.addApplicationFont(str(ttf))

    # ------------------------------------------------------------- accessors
    @property
    def palette(self) -> dict[str, Any]:
        return self.tokens["themes"][self.mode]

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
        """code: PENDING | PROCESSING | SUCCESS | DUPLICATE | ERROR"""
        meta = self.tokens["status_map"][code]
        spec = dict(self.palette["status"][meta["token"]])
        spec["label"] = meta["label"]
        return spec

    def metric(self, name: str) -> Any:
        return self.tokens["metrics"][name]

    # ----------------------------------------------------------------- apply
    def _flat_vars(self) -> dict[str, str]:
        p = self.palette
        flat: dict[str, str] = {k: v for k, v in p.items() if isinstance(v, str)}
        for group in ("status", "log", "pdf_canvas"):
            for key, val in p.get(group, {}).items():
                if isinstance(val, dict):
                    for sub, subval in val.items():
                        flat[f"{group}_{key}_{sub}"] = subval
                else:
                    flat[f"{group}_{key}"] = val
        for key, val in self.tokens["radius"].items():
            flat[f"radius_{key}"] = str(val)
        for key, val in self.tokens["space"].items():
            flat[f"space_{key}"] = str(val)
        for key, val in self.tokens["font"].items():
            flat[key] = str(val)
        for key, val in self.tokens["metrics"].items():
            if isinstance(val, (int, float)):
                flat[key] = str(int(val))
        return flat

    def stylesheet(self, qss_path: Path = QSS_PATH) -> str:
        template = qss_path.read_text(encoding="utf-8")
        variables = self._flat_vars()
        missing: set[str] = set()

        def repl(match: re.Match[str]) -> str:
            key = match.group(1)
            if key not in variables:
                missing.add(key)
                return match.group(0)
            return variables[key]

        rendered = _PLACEHOLDER.sub(repl, template)
        if missing:  # fail loudly in dev, never ship a half-styled window
            raise KeyError(f"theme.qss references unknown tokens: {sorted(missing)}")
        return rendered

    def apply(self, app) -> None:
        app.setStyleSheet(self.stylesheet())
        app.setProperty("themeMode", self.mode)
        self.changed.emit(self.mode)

    def set_mode(self, mode: str) -> None:
        if mode not in self.tokens["themes"]:
            raise ValueError(mode)
        self.mode = mode


def repolish(widget) -> None:
    """Call after changing a dynamic QSS property (variant/state/selected...)."""
    widget.style().unpolish(widget)
    widget.style().polish(widget)
    widget.update()
