"""Engine rule: nhận diện profile, chạy regex tầng 1, và kho profile có versioning.

Mỗi lần lưu profile tạo 1 version mới trong _versions/<profile_id>/<n>.json để
rollback 1 click và để chạy regression test so với version trước.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import UTC, datetime
from pathlib import Path

from .errors import ProfileError
from .models import DocumentText, ExtractedField, Layer, MatchCondition, Profile
from .textloc import locate

logger = logging.getLogger(__name__)

RULEPACK_FORMAT = "pdf-batch-renamer-rulepack"
RULEPACK_VERSION = 1

# Regex của rule chạy không phân biệt hoa thường: nhãn trên chứng từ lúc "B/L No.",
# lúc "B/L NO." — người dùng không nên phải quan tâm chuyện đó.
RULE_FLAGS = re.IGNORECASE | re.MULTILINE


# --------------------------------------------------------------- nhận diện


def condition_matches(cond: MatchCondition, text: str) -> bool:
    """1 điều kiện nhận diện có trúng trong text không."""
    if not cond.value:
        return False
    if cond.kind == "regex":
        try:
            flags = 0 if cond.case_sensitive else RULE_FLAGS
            return re.search(cond.value, text, flags) is not None
        except re.error as exc:
            logger.error("Điều kiện regex không hợp lệ (%s): %s", cond.value, exc)
            return False
    if cond.case_sensitive:
        return cond.value in text
    return cond.value.casefold() in text.casefold()


def profile_matches(profile: Profile, text: str) -> bool:
    """Profile có nhận file này không.

    Điều kiện LOẠI TRỪ được xét trước và có quyền phủ quyết: trúng 1 cái là loại ngay,
    dù conditions có trúng hết. Nhờ vậy người dùng xử lý được chứng từ chồng lấn
    (Invoice NOT contains "PACKING LIST") mà không phải mày mò thứ tự ưu tiên.
    """
    if not profile.enabled or not profile.conditions:
        return False
    if any(condition_matches(c, text) for c in profile.exclude_conditions):
        return False
    results = (condition_matches(c, text) for c in profile.conditions)
    return all(results) if profile.condition_mode == "all" else any(results)


def resolve_profile(profiles: list[Profile], key: str) -> Profile | None:
    """Tìm profile theo id hoặc theo tên (không phân biệt hoa thường)."""
    if not key:
        return None
    for p in profiles:
        if p.id == key or p.name.casefold() == key.casefold():
            return p
    return None


def select_profile(
    profiles: list[Profile], text: str, forced_id: str = ""
) -> Profile | None:
    """Chọn profile cho 1 file.

    forced_id (CLI --profile) ép dùng profile đó và BỎ QUA điều kiện nhận diện.
    Ngược lại duyệt theo priority tăng dần; không cái nào trúng thì dùng profile fallback.
    """
    if forced_id:
        forced = resolve_profile(profiles, forced_id)
        if forced is None:
            raise ProfileError(f"Không tìm thấy profile '{forced_id}'")
        return forced

    ordered = sorted(
        (p for p in profiles if p.enabled and not p.is_fallback),
        key=lambda p: (p.priority, p.name.casefold()),
    )
    for profile in ordered:
        if profile_matches(profile, text):
            return profile

    fallbacks = sorted(
        (p for p in profiles if p.enabled and p.is_fallback),
        key=lambda p: (p.priority, p.name.casefold()),
    )
    return fallbacks[0] if fallbacks else None


# ------------------------------------------------------------------ tầng 1


def run_regex_field(spec, document: DocumentText) -> ExtractedField | None:
    """Chạy các regex của 1 field theo thứ tự dự phòng, dừng ở regex đầu tiên trúng.

    Thứ tự ưu tiên là thứ tự regex (không phải thứ tự trang): patterns[0] là rule chính,
    các pattern sau chỉ là dự phòng.
    """
    for pattern_index, pattern in enumerate(spec.patterns):
        if not pattern:
            continue
        try:
            compiled = re.compile(pattern, RULE_FLAGS)
        except re.error as exc:
            logger.error("Regex hỏng ở field '%s': %s (%s)", spec.name, pattern, exc)
            continue

        for page in document.pages:
            if not page.text:
                continue
            m = compiled.search(page.text)
            if not m:
                continue
            value = (m.group(1) if m.groups() else m.group(0)).strip()
            if not value:
                continue
            return ExtractedField(
                name=spec.name,
                value=value,
                raw_value=m.group(0).strip(),
                layer=Layer.REGEX,
                rule_id=f"pattern[{pattern_index}]",
                page=page.index,
                bbox=locate(page, value),
            )
    return None


# ---------------------------------------------------------------- kho profile


class ProfileStore:
    """Đọc/ghi profile JSON kèm lịch sử version."""

    def __init__(self, directory: Path | str, versions_directory: Path | str | None = None) -> None:
        self.directory = Path(directory)
        self.versions_directory = (
            Path(versions_directory) if versions_directory else self.directory / "_versions"
        )
        self.directory.mkdir(parents=True, exist_ok=True)
        self.versions_directory.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------- đọc/ghi

    def path_for(self, profile_id: str) -> Path:
        return self.directory / f"{profile_id}.json"

    def load_all(self) -> list[Profile]:
        """Load mọi profile. File hỏng bị bỏ qua kèm log, không làm chết app."""
        profiles: list[Profile] = []
        for path in sorted(self.directory.glob("*.json")):
            try:
                profiles.append(Profile.from_dict(json.loads(path.read_text(encoding="utf-8"))))
            except (json.JSONDecodeError, TypeError, ValueError) as exc:
                logger.error("Bỏ qua profile hỏng %s: %s", path.name, exc)
        return sorted(profiles, key=lambda p: (p.priority, p.name.casefold()))

    def get(self, profile_id: str) -> Profile | None:
        path = self.path_for(profile_id)
        if not path.exists():
            return None
        try:
            return Profile.from_dict(json.loads(path.read_text(encoding="utf-8")))
        except (json.JSONDecodeError, TypeError, ValueError) as exc:
            raise ProfileError(f"Profile hỏng: {path.name} ({exc})") from exc

    def save(self, profile: Profile, bump_version: bool = True) -> Profile:
        """Lưu profile. bump_version=True tạo version mới + snapshot để rollback."""
        if bump_version:
            # Số version lấy từ trạng thái ĐÃ LƯU, không lấy từ đối tượng trong bộ nhớ,
            # để profile mới tạo (version mặc định 1) không nhảy thẳng lên 2.
            existing = self.get(profile.id)
            base = max(
                existing.version if existing else 0,
                max(self.versions(profile.id) or [0]),
            )
            profile.version = base + 1

        payload = json.dumps(profile.to_dict(), ensure_ascii=False, indent=2)
        path = self.path_for(profile.id)
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(payload, encoding="utf-8")
        tmp.replace(path)

        snap_dir = self.versions_directory / profile.id
        snap_dir.mkdir(parents=True, exist_ok=True)
        (snap_dir / f"{profile.version}.json").write_text(payload, encoding="utf-8")
        return profile

    def delete(self, profile_id: str) -> None:
        self.path_for(profile_id).unlink(missing_ok=True)

    # ------------------------------------------------------------ versioning

    def versions(self, profile_id: str) -> list[int]:
        snap_dir = self.versions_directory / profile_id
        if not snap_dir.exists():
            return []
        out = []
        for p in snap_dir.glob("*.json"):
            try:
                out.append(int(p.stem))
            except ValueError:
                continue
        return sorted(out)

    def load_version(self, profile_id: str, version: int) -> Profile:
        path = self.versions_directory / profile_id / f"{version}.json"
        if not path.exists():
            raise ProfileError(f"Không có version {version} của profile {profile_id}")
        return Profile.from_dict(json.loads(path.read_text(encoding="utf-8")))

    def rollback(self, profile_id: str, version: int) -> Profile:
        """Quay về nội dung của version cũ, nhưng vẫn lưu thành version MỚI.

        Không xoá lịch sử: rollback cũng là một thay đổi và phải truy vết được.
        """
        old = self.load_version(profile_id, version)
        old.version = max(self.versions(profile_id) or [0])
        return self.save(old, bump_version=True)

    # ------------------------------------------------------------- rule pack

    def export_pack(self, path: Path | str, profile_ids: list[str] | None = None) -> Path:
        """Xuất bộ rule ra 1 file JSON để backup / đồng bộ sang máy khác."""
        profiles = self.load_all()
        if profile_ids:
            wanted = set(profile_ids)
            profiles = [p for p in profiles if p.id in wanted]
        payload = {
            "format": RULEPACK_FORMAT,
            "version": RULEPACK_VERSION,
            "exported_at": datetime.now(UTC).isoformat(timespec="seconds"),
            "profiles": [p.to_dict() for p in profiles],
        }
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return p

    def import_pack(self, path: Path | str, overwrite: bool = False) -> list[Profile]:
        """Nạp rule pack. overwrite=False thì profile trùng id sẽ được nhân bản thành id mới."""
        p = Path(path)
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            raise ProfileError(f"Rule pack không đọc được: {exc}") from exc

        if data.get("format") != RULEPACK_FORMAT:
            raise ProfileError("File này không phải rule pack của PDF Batch Renamer")

        imported: list[Profile] = []
        for raw in data.get("profiles", []):
            profile = Profile.from_dict(raw)
            if not overwrite and self.path_for(profile.id).exists():
                profile.id = ""  # __post_init__ đã chạy rồi nên cấp id mới thủ công
                Profile.__post_init__(profile)
                profile.name = f"{profile.name} (nhập)"
            profile.version = 0
            imported.append(self.save(profile, bump_version=True))
        return imported
