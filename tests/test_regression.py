"""Test regression: sửa rule làm field match kém đi thì phải báo rõ."""

from __future__ import annotations

from pathlib import Path

from src.core.models import FieldSpec, Profile
from src.core.regression import run_regression


def profile(version: int = 1) -> Profile:
    return Profile(
        id="inv",
        name="Invoice",
        version=version,
        fields=[
            FieldSpec(name="number", label="Số hóa đơn"),
            FieldSpec(name="doc_date", label="Ngày"),
        ],
    )


def fake_extract(results: dict[tuple[int, str], dict[str, str]]):
    """extract_fn giả: tra kết quả theo (version của profile, tên file)."""

    def fn(p: Profile, path: Path) -> dict[str, str]:
        return results.get((p.version, path.name), {})

    return fn


class TestRegression:
    def test_phat_hien_field_kem_di(self, tmp_path):
        samples = []
        for i in range(3):
            f = tmp_path / f"mau{i}.pdf"
            f.write_bytes(b"x")
            samples.append(f)

        results = {}
        for i in range(3):
            results[(1, f"mau{i}.pdf")] = {"number": "A", "doc_date": "01/01/2026"}
            # version 2 chỉ còn bắt được doc_date ở 1 file
            results[(2, f"mau{i}.pdf")] = {"number": "A"} if i == 0 else {}

        report = run_regression(
            profile(1), profile(2), samples, extract_fn=fake_extract(results)
        )
        assert report.sample_count == 3
        assert report.has_regression
        names = {f.name for f in report.regressions}
        assert names == {"number", "doc_date"}
        assert "[KÉM]" in report.summary_vi()

    def test_phat_hien_cai_thien(self, tmp_path):
        f = tmp_path / "mau.pdf"
        f.write_bytes(b"x")
        results = {(1, "mau.pdf"): {}, (2, "mau.pdf"): {"number": "A"}}

        report = run_regression(profile(1), profile(2), [f], extract_fn=fake_extract(results))
        assert not report.has_regression
        assert [c.name for c in report.improvements] == ["number"]
        assert "[TỐT]" in report.summary_vi()

    def test_canh_bao_khi_gia_tri_doi_du_van_match(self, tmp_path):
        f = tmp_path / "mau.pdf"
        f.write_bytes(b"x")
        results = {(1, "mau.pdf"): {"number": "A"}, (2, "mau.pdf"): {"number": "B"}}

        report = run_regression(profile(1), profile(2), [f], extract_fn=fake_extract(results))
        assert not report.has_regression
        assert report.fields[1].changed_values == 1  # fields sắp xếp theo tên: doc_date, number
        assert "giá trị khác trước" in report.summary_vi()

    def test_profile_moi_tao_khong_co_ban_cu(self, tmp_path):
        f = tmp_path / "mau.pdf"
        f.write_bytes(b"x")
        results = {(1, "mau.pdf"): {"number": "A"}}

        report = run_regression(None, profile(1), [f], extract_fn=fake_extract(results))
        assert report.old_version == 0
        assert not report.has_regression

    def test_khong_co_file_mau_thi_bao_ro(self):
        report = run_regression(profile(1), profile(2), [], extract_fn=fake_extract({}))
        assert report.sample_count == 0
        assert "chưa có file mẫu" in report.summary_vi()

    def test_file_mau_loi_duoc_liet_ke_rieng(self, tmp_path):
        f = tmp_path / "hong.pdf"
        f.write_bytes(b"x")

        def boom(p, path):
            raise ValueError("khong mo duoc")

        report = run_regression(profile(1), profile(2), [f], extract_fn=boom)
        assert report.failed_samples == ["hong.pdf"]
        assert report.sample_count == 0

    def test_bo_qua_file_mau_khong_ton_tai(self, tmp_path):
        report = run_regression(
            profile(1), profile(2), [tmp_path / "khong-co.pdf"], extract_fn=fake_extract({})
        )
        assert report.sample_count == 0

    def test_dung_samples_cua_profile_khi_khong_truyen(self, tmp_path):
        f = tmp_path / "mau.pdf"
        f.write_bytes(b"x")
        new = profile(2)
        new.samples = [str(f)]
        results = {(1, "mau.pdf"): {"number": "A"}, (2, "mau.pdf"): {"number": "A"}}

        report = run_regression(profile(1), new, extract_fn=fake_extract(results))
        assert report.sample_count == 1
