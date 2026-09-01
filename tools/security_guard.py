"""Security Guard & DLP Scanner — Bo kiem tra an ninh va chong ro ri du lieu tu dong."""

from __future__ import annotations
import os
import re
import subprocess
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parent.parent

SECRET_PATTERNS = {
    "GitHub Token": r"gh[pousr]_[A-Za-z0-9_]{36,255}",
    "OpenAI / Anthropic API Key": r"sk-(?:proj-|ant-)?[A-Za-z0-9-_]{20,}",
    "Generic Private Key": r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----",
    "JWT Token": r"eyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}",
    "AWS Access Key": r"(?:A3T[A-Z0-9]|AKIA|AGPA|AIDA|AROA|AIPA|ANPA|ANVA|ASIA)[A-Z0-9]{16}",
}

FORBIDDEN_PATTERNS = [
    re.compile(r".*\.pdf$", re.IGNORECASE),
    re.compile(r".*BRIEF.*\.md$", re.IGNORECASE),
    re.compile(r"^CLAUDE\.md$", re.IGNORECASE),
    re.compile(r".*\.env.*$", re.IGNORECASE),
    re.compile(r".*\.(?:pem|key|p12|pfx|crt)$", re.IGNORECASE),
    re.compile(r".*Giao diện ứng dụng.*", re.IGNORECASE),
]

EXCLUDE_SECRET_SCAN_FILES = {"guide_assets.py", "security_guard.py"}

def get_tracked_files() -> list[str]:
    try:
        out = subprocess.check_output(["git", "ls-files"], cwd=str(ROOT), text=True, encoding="utf-8", errors="replace")
        return [f.strip() for f in out.splitlines() if f.strip()]
    except Exception:
        return []

def scan_project() -> int:
    issues = 0
    print(f"=== Bắt đầu quét an ninh & chống rò rỉ dữ liệu: {ROOT} ===")
    tracked_files = get_tracked_files()
    if not tracked_files:
        print("[INFO] Không tìm thấy file nào đang được Git theo dõi.")
        return 0
    for rel_path in tracked_files:
        norm_path = rel_path.replace(chr(92), "/")
        file_name = Path(norm_path).name
        for pat in FORBIDDEN_PATTERNS:
            if pat.match(norm_path) or pat.match(file_name):
                print(f"[CẢNH BÁO BẢO MẬT] File nhạy cảm bị theo dõi bởi Git: {norm_path}")
                issues += 1
    text_extensions = {".py", ".json", ".iss", ".toml", ".yml", ".yaml", ".ini", ".txt", ".md"}
    for rel_path in tracked_files:
        p_file = ROOT / rel_path
        if not p_file.exists() or p_file.name in EXCLUDE_SECRET_SCAN_FILES:
            continue
        if p_file.suffix.lower() in text_extensions:
            try:
                content = p_file.read_text(encoding="utf-8", errors="ignore")
                for sec_name, sec_regex in SECRET_PATTERNS.items():
                    for m in re.finditer(sec_regex, content, re.IGNORECASE):
                        line_num = content[:m.start()].count(chr(10)) + 1
                        matched_str = m.group(0)
                        print(f"[CẢNH BÁO SECRET] {sec_name} tại {rel_path} (Dòng {line_num}): {matched_str[:8]}***")
                        issues += 1
            except Exception:
                pass
    if issues == 0:
        print(f"[THÀNH CÔNG] Quét {len(tracked_files)} files: Sạch 100% — Không rò rỉ dữ liệu, file cấm hay secret nào!")
        return 0
    else:
        print(f"[PHÁT HIỆN LỖI] Tìm thấy {issues} vấn đề bảo mật trong Git!")
        return 1

if __name__ == "__main__":
    sys.exit(scan_project())