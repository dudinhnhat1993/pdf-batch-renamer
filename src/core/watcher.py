"""Watch folder: PDF mới rơi vào thư mục -> tự xử lý.

Chống nhặt file đang copy dở: chỉ báo lên khi kích thước file đứng yên đủ N giây.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from pathlib import Path

logger = logging.getLogger(__name__)


class StableFileWatcher:
    """Giám sát 1 thư mục và gọi callback khi có file PDF mới đã ghi xong."""

    def __init__(
        self,
        folder: Path | str,
        on_file: Callable[[Path], None],
        *,
        stable_seconds: int = 3,
        poll_interval: float = 1.0,
        suffixes: tuple[str, ...] = (".pdf",),
        process_existing: bool = False,
    ) -> None:
        self.folder = Path(folder)
        self.on_file = on_file
        self.stable_seconds = stable_seconds
        self.poll_interval = poll_interval
        self.suffixes = tuple(s.lower() for s in suffixes)
        self.process_existing = process_existing

        self._observer = None
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()
        # đường dẫn -> (kích thước lần đo trước, thời điểm kích thước bắt đầu đứng yên)
        self._pending: dict[Path, tuple[int, float]] = {}
        self._done: set[Path] = set()

    # ------------------------------------------------------------- vòng đời

    def start(self) -> None:
        from watchdog.events import FileSystemEventHandler
        from watchdog.observers import Observer

        if not self.folder.exists():
            raise FileNotFoundError(f"Thư mục theo dõi không tồn tại: {self.folder}")

        watcher = self

        class _Handler(FileSystemEventHandler):
            def on_created(self, event):
                if not event.is_directory:
                    watcher.enqueue(Path(event.src_path))

            def on_moved(self, event):
                if not event.is_directory:
                    watcher.enqueue(Path(event.dest_path))

            def on_modified(self, event):
                if not event.is_directory:
                    watcher.enqueue(Path(event.src_path))

        if self.process_existing:
            for p in sorted(self.folder.glob("*")):
                self.enqueue(p)

        self._observer = Observer()
        self._observer.schedule(_Handler(), str(self.folder), recursive=False)
        self._observer.start()

        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="watch-stability", daemon=True)
        self._thread.start()
        logger.info("Bắt đầu theo dõi thư mục %s", self.folder)

    def stop(self) -> None:
        self._stop.set()
        if self._observer is not None:
            self._observer.stop()
            self._observer.join(timeout=5)
            self._observer = None
        if self._thread is not None:
            self._thread.join(timeout=5)
            self._thread = None

    def __enter__(self) -> StableFileWatcher:
        self.start()
        return self

    def __exit__(self, *exc) -> None:
        self.stop()

    # ------------------------------------------------------------- hàng đợi

    def enqueue(self, path: Path) -> None:
        """Đưa 1 file vào diện chờ ổn định."""
        if path.suffix.lower() not in self.suffixes:
            return
        with self._lock:
            if path in self._done:
                return
            try:
                size = path.stat().st_size
            except OSError:
                return
            previous = self._pending.get(path)
            # Kích thước còn đổi -> đặt lại đồng hồ đếm ổn định
            if previous is None or previous[0] != size:
                self._pending[path] = (size, time.monotonic())

    def check_once(self) -> list[Path]:
        """Kiểm tra 1 lượt, trả các file đã ổn định và gọi callback cho từng file."""
        ready: list[Path] = []
        now = time.monotonic()
        with self._lock:
            for path, (size, since) in list(self._pending.items()):
                try:
                    current = path.stat().st_size
                except OSError:
                    self._pending.pop(path, None)
                    continue
                if current != size:
                    self._pending[path] = (current, now)
                    continue
                if now - since >= self.stable_seconds:
                    self._pending.pop(path, None)
                    self._done.add(path)
                    ready.append(path)

        for path in ready:
            try:
                self.on_file(path)
            except Exception:
                logger.exception("Xử lý file từ watch folder thất bại: %s", path)
        return ready

    def _loop(self) -> None:
        while not self._stop.is_set():
            self.check_once()
            self._stop.wait(self.poll_interval)
