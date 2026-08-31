"""Kiểm tra đường nâng cấp: chạy bản mới trên %APPDATA% của bản cũ.

Dựng sẵn một thư mục dữ liệu "đã dùng lâu" (config đã chỉnh, rule tự tạo có lịch sử
version, registry chống trùng, correction), rồi chạy exe bản mới lên chính thư mục đó và
đối chiếu: KHÔNG được mất hay ghi đè thứ gì.

    python tools/upgrade_check.py <thư_mục_dist>
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.core import db as db_module  # noqa: E402
from src.core.config import AppConfig, save_config  # noqa: E402
from src.core.models import FieldSpec, MatchCondition, Profile  # noqa: E402


def build_old_install(home: Path, inbox: Path, output: Path) -> dict:
    """Dựng thư mục dữ liệu như của người dùng đã xài một thời gian."""
    os.environ["PDFRENAMER_HOME"] = str(home)
    db_module.reset_default_db()

    from src.core.bootstrap import build_context
    from src.core.learning import LearningStore
    from src.core.pipeline import Pipeline

    ctx = build_context()
    config: AppConfig = ctx.config
    config.output_root = str(output)
    config.strip_accents = True
    config.workers = 7
    config.passwords = ["mat-khau-cua-toi"]
    config.field_panel_area = "right"
    save_config(config)

    # Rule người dùng tự tạo, sửa 2 lần -> có lịch sử version
    custom = Profile(
        id="rule-cua-toi",
        name="Rule của tôi",
        doctype="RCT",
        priority=1,
        conditions=[MatchCondition(value="COMMERCIAL INVOICE")],
        fields=[FieldSpec(name="number", label="Số", patterns=[r"Invoice No\.:\s*(\S+)"])],
        template="{doctype}_{number}",
    )
    ctx.store.save(custom)
    custom.template = "{number}"
    ctx.store.save(custom)

    # Chạy 1 batch thật -> registry chống trùng + provenance
    pipeline = Pipeline(config, ctx.profiles, ctx.db)
    jobs = pipeline.plan([inbox])
    pipeline.apply(jobs)

    learning = LearningStore(ctx.db)
    learning.record_correction(
        field_name="number", old_value="A", new_value="B", profile_id="rule-cua-toi"
    )

    snapshot = snapshot_home(home, ctx)
    ctx.close()
    db_module.reset_default_db()
    return snapshot


def snapshot_home(home: Path, ctx=None) -> dict:
    """Chụp lại trạng thái thư mục dữ liệu để so trước/sau."""
    close_after = ctx is None
    if ctx is None:
        os.environ["PDFRENAMER_HOME"] = str(home)
        db_module.reset_default_db()
        from src.core.bootstrap import build_context

        ctx = build_context()

    from src.core.dedup import DedupRegistry
    from src.core.learning import LearningStore

    learning = LearningStore(ctx.db)
    data = {
        "config": json.loads((home / "config.json").read_text(encoding="utf-8")),
        "profiles": sorted(p.stem for p in (home / "profiles").glob("*.json")),
        "profile_noi_dung": {
            p.id: {"template": p.template, "version": p.version, "name": p.name}
            for p in ctx.store.load_all()
        },
        "versions": {
            p.id: ctx.store.versions(p.id) for p in ctx.store.load_all()
        },
        "dedup": DedupRegistry(ctx.db).count(),
        "corrections": len(learning.corrections()),
        "provenance": len(ctx.db.query("SELECT id FROM provenance")),
    }
    if close_after:
        ctx.close()
        db_module.reset_default_db()
    return data


def diff(before: dict, after: dict) -> list[str]:
    problems = []
    for key in before:
        if before[key] != after.get(key):
            problems.append(f"  {key}:\n    trước: {before[key]}\n    sau  : {after.get(key)}")
    return problems


def main(dist: Path) -> int:
    work = Path(tempfile.mkdtemp(prefix="pdfbr_upgrade_"))
    home, inbox, output = work / "home", work / "in", work / "out"
    inbox.mkdir(parents=True)
    output.mkdir(parents=True)

    from tools.make_fixtures import generate_all

    fixtures = generate_all(work / "fixtures")
    for key in ("invoice", "bill_of_lading", "packing_list"):
        shutil.copy2(fixtures[key], inbox / fixtures[key].name)

    print("1. Dung thu muc du lieu cua 'ban cu'...")
    before = build_old_install(home, inbox, output)
    print(f"   profile: {before['profiles']}")
    print(f"   version cua rule tu tao: {before['versions'].get('rule-cua-toi')}")
    print(f"   dedup: {before['dedup']} | provenance: {before['provenance']} "
          f"| correction: {before['corrections']}")

    print("2. Chay exe BAN MOI len chinh thu muc do...")
    env = dict(os.environ, PDFRENAMER_HOME=str(home))
    env.pop("PYTHONHOME", None)
    env.pop("PYTHONPATH", None)
    exe = dist / "pdf-renamer.exe"

    check = subprocess.run(
        [str(exe), "--check"], env=env, capture_output=True, text=True,
        encoding="utf-8", errors="replace",
    )
    if check.returncode != 0:
        print(check.stdout, check.stderr)
        return 1

    # Chạy lại đúng batch cũ: mọi file phải bị nhận là TRÙNG (registry còn nguyên)
    rerun = subprocess.run(
        [str(exe), "--input", str(inbox), "--output", str(output)],
        env=env, capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    duplicates = rerun.stdout.count("Trùng")
    print(f"   chay lai batch cu -> nhan dien trung: {duplicates - 1} file")

    print("3. Doi chieu truoc/sau...")
    after = snapshot_home(home)
    problems = diff(before, after)
    if problems:
        print("   KHONG DAT — co thu bi doi:")
        print("\n".join(problems))
        return 1

    print("   DAT — config, rule, lich su version, registry, correction deu nguyen ven.")
    print(f"   (thu muc kiem tra: {work})")
    return 0


if __name__ == "__main__":
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "dist" / "PDFBatchRenamer-full"
    sys.exit(main(target))
