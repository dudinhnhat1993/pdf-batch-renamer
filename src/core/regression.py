"""Regression test cho rule: so version mới với version cũ trên bộ file mẫu của profile.

Sửa rule mà làm field nào match kém đi thì phải báo rõ và chỉ lưu khi người dùng xác nhận.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from .config import AppConfig
from .models import Profile

logger = logging.getLogger(__name__)

# Hàm trích: (profile, đường dẫn file mẫu) -> {tên field: giá trị}
ExtractFn = Callable[[Profile, Path], dict[str, str]]


@dataclass
class FieldComparison:
    name: str
    label: str
    old_hits: int = 0
    new_hits: int = 0
    changed_values: int = 0  # số file vẫn bắt được nhưng ra giá trị KHÁC

    @property
    def delta(self) -> int:
        return self.new_hits - self.old_hits

    @property
    def is_regression(self) -> bool:
        return self.new_hits < self.old_hits


@dataclass
class RegressionReport:
    """Kết quả so sánh 2 version rule trên cùng bộ file mẫu."""

    profile_id: str = ""
    old_version: int = 0
    new_version: int = 0
    sample_count: int = 0
    fields: list[FieldComparison] = field(default_factory=list)
    failed_samples: list[str] = field(default_factory=list)

    @property
    def regressions(self) -> list[FieldComparison]:
        return [f for f in self.fields if f.is_regression]

    @property
    def improvements(self) -> list[FieldComparison]:
        return [f for f in self.fields if f.delta > 0]

    @property
    def has_regression(self) -> bool:
        return bool(self.regressions)

    def summary_vi(self) -> str:
        """Tóm tắt bằng tiếng Việt để hiện thẳng trong hộp thoại xác nhận."""
        if not self.sample_count:
            return "Profile chưa có file mẫu nào — không chạy được regression test."
        lines = [
            f"Chạy trên {self.sample_count} file mẫu "
            f"(v{self.old_version} -> v{self.new_version}):"
        ]
        for f in self.fields:
            if f.delta < 0:
                lines.append(
                    f"  [KÉM] {f.label}: {f.old_hits}/{self.sample_count} -> "
                    f"{f.new_hits}/{self.sample_count}"
                )
            elif f.delta > 0:
                lines.append(
                    f"  [TỐT] {f.label}: {f.old_hits}/{self.sample_count} -> "
                    f"{f.new_hits}/{self.sample_count}"
                )
            elif f.changed_values:
                lines.append(
                    f"  ! {f.label}: số file match không đổi nhưng {f.changed_values} file "
                    "cho ra giá trị khác trước"
                )
        if len(lines) == 1:
            lines.append("  Không có thay đổi nào về kết quả trích.")
        if self.failed_samples:
            lines.append("  File mẫu không mở được: " + ", ".join(self.failed_samples))
        return "\n".join(lines)


def default_extract_fn(config: AppConfig) -> ExtractFn:
    """Hàm trích mặc định: chạy đúng pipeline thật với duy nhất profile đang xét."""
    from .extractor import Extractor
    from .ocr import OcrEngine

    ocr = OcrEngine(
        config.ocr.tesseract_path,
        config.ocr.languages,
        config.ocr.dpi,
        config.ocr.tessdata_path,
    )

    def run(profile: Profile, path: Path) -> dict[str, str]:
        # AI bị tắt cứng khi chạy regression để kết quả deterministic
        extractor = Extractor(config, [profile], ocr=ocr, ai_client=None)
        result = extractor.extract(path, forced_profile=profile.id)
        return {k: v.value for k, v in result.fields.items()}

    return run


def run_regression(
    old_profile: Profile | None,
    new_profile: Profile,
    samples: list[Path | str] | None = None,
    extract_fn: ExtractFn | None = None,
    config: AppConfig | None = None,
) -> RegressionReport:
    """So sánh kết quả trích của 2 version rule trên bộ file mẫu.

    old_profile=None (profile mới tạo) thì mọi field đều tính là cải thiện.
    """
    fn = extract_fn or default_extract_fn(config or AppConfig())
    sample_paths = [Path(s) for s in (samples if samples is not None else new_profile.samples)]
    sample_paths = [p for p in sample_paths if p.exists()]

    report = RegressionReport(
        profile_id=new_profile.id,
        old_version=old_profile.version if old_profile else 0,
        new_version=new_profile.version,
    )

    comparisons: dict[str, FieldComparison] = {
        spec.name: FieldComparison(name=spec.name, label=spec.label)
        for spec in new_profile.fields
    }
    for spec in old_profile.fields if old_profile else []:
        comparisons.setdefault(spec.name, FieldComparison(name=spec.name, label=spec.label))

    for path in sample_paths:
        try:
            new_values = fn(new_profile, path)
            old_values = fn(old_profile, path) if old_profile else {}
        except Exception as exc:
            logger.warning("File mẫu lỗi khi chạy regression (%s): %s", path.name, exc)
            report.failed_samples.append(path.name)
            continue

        report.sample_count += 1
        for name, comp in comparisons.items():
            old_v, new_v = old_values.get(name, ""), new_values.get(name, "")
            if old_v:
                comp.old_hits += 1
            if new_v:
                comp.new_hits += 1
            if old_v and new_v and old_v != new_v:
                comp.changed_values += 1

    report.fields = sorted(comparisons.values(), key=lambda c: c.name)
    return report
