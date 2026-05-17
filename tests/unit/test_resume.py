"""resume 完了判定5条件（spec v4 §4 WS1）。"""

import json

from grep_analyzer.output_writer import finalize
from grep_analyzer import resume
from tests.unit.test_output_writer import _hit, _mk, _opts


def test_正常完了は完了判定真(tmp_path):
    finalize(tmp_path, "K", _mk(5), _opts(max_rows_per_part=2))
    assert resume.is_complete(tmp_path, "K", _opts()) is True


def test_manifest不在は未完了(tmp_path):
    finalize(tmp_path, "K", _mk(2), _opts())
    (tmp_path / "K.manifest.json").unlink()
    assert resume.is_complete(tmp_path, "K", _opts()) is False


def test_part欠落は未完了(tmp_path):
    finalize(tmp_path, "K", _mk(4), _opts(max_rows_per_part=1))
    next(tmp_path.glob("K.part01.tsv")).unlink()
    assert resume.is_complete(tmp_path, "K", _opts()) is False


def test_行数保存_1文字改竄でsha不一致は未完了(tmp_path):
    finalize(tmp_path, "K", _mk(3), _opts())
    p = tmp_path / "K.tsv"
    b = p.read_bytes().replace(b"s0", b"sX", 1)   # 行数不変・内容変化
    p.write_bytes(b)
    assert resume.is_complete(tmp_path, "K", _opts()) is False


def test_items_per_mb不一致は未完了(tmp_path):
    finalize(tmp_path, "K", _mk(2), _opts())
    m = json.loads((tmp_path / "K.manifest.json").read_text("utf-8"))
    m["items_per_mb"] = m["items_per_mb"] + 1
    (tmp_path / "K.manifest.json").write_text(
        json.dumps(m, sort_keys=True, separators=(",", ":")), "utf-8")
    assert resume.is_complete(tmp_path, "K", _opts()) is False


def test_破損manifestは未完了(tmp_path):
    finalize(tmp_path, "K", _mk(1), _opts())
    (tmp_path / "K.manifest.json").write_text("{not json", "utf-8")
    assert resume.is_complete(tmp_path, "K", _opts()) is False


def test_utf8sig_複数part_行数保存改竄で未完了_BOM再構成経路(tmp_path):
    # utf-8-sig × 2part の再構成（各 part BOM/ヘッダ除去）が data_sha256 と
    # 同一関数で照合されること＝書込側/完了判定側の正規形一致を踏む。
    finalize(tmp_path, "K", _mk(4), _opts(max_rows_per_part=2,
                                          output_encoding="utf-8-sig"))
    assert resume.is_complete(tmp_path, "K", _opts()) is True
    p = tmp_path / "K.part02.tsv"
    p.write_bytes(p.read_bytes().replace(b"s3", b"sZ", 1))  # 行数不変
    assert resume.is_complete(tmp_path, "K", _opts()) is False


def test_name欠落manifestは未完了(tmp_path):
    finalize(tmp_path, "K", _mk(2), _opts())
    m = json.loads((tmp_path / "K.manifest.json").read_text("utf-8"))
    m["parts"] = [{"rows": 2}]   # "name" キーを意図的に欠落させる
    (tmp_path / "K.manifest.json").write_text(
        json.dumps(m, sort_keys=True, separators=(",", ":")), "utf-8")
    assert resume.is_complete(tmp_path, "K", _opts()) is False


def test_part不正バイトで復号失敗は未完了(tmp_path):
    finalize(tmp_path, "K", _mk(2), _opts())
    # utf-8-sig（既定）では無効なバイト列で UnicodeDecodeError を起こす
    (tmp_path / "K.tsv").write_bytes(b"\xff\xfe\xff\xfe")
    assert resume.is_complete(tmp_path, "K", _opts()) is False
