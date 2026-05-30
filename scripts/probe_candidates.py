"""実コーパスで初回 union 候補の総バイト・非UTF-8割合を測り option A/B を判断する。

使い方: python scripts/probe_candidates.py --input IN --source-root SRC [--jobs N]
本体パイプラインは変更しない読み取り専用プローブ。
"""
import argparse
import os
from pathlib import Path

from grep_analyzer.chase import extract_chase_symbols, extract_chase_symbols_tree
from grep_analyzer.classifiers import _AST_CHASERS
from grep_analyzer.dispatch import detect_language, detect_shell_dialect
from grep_analyzer.embed_preprocess import effective_language
from grep_analyzer.encoding import DEFAULT_FALLBACK, decode_bytes
from grep_analyzer.ingest import parse_grep_line
from grep_analyzer.stoplist import SymbolPolicy, partition
from grep_analyzer import ripgrep


def compute_initial_union(input_dir: Path, source_root: Path) -> set[str]:
    """全 .grep のヒット行から初回 chase∪terminal 記号（stoplist 適用後）を算出。

    _seed.py の hop1 first-hop に忠実化する:
      - file_meta 相当で言語判定後、effective_language(language, text, lineno) を
        適用し TS inline-template 行を angular_inline へ retarget（_seed.py l.72）。
      - AST 言語（_AST_CHASERS）はファイル全文＋lineno で extract_chase_symbols_tree。
      - 行ベース言語は **.grep 内容ではなく on-disk のファイル行**（text.split("\n")
        の lineno-1, 1-based）から extract_chase_symbols する（_seed.py l.77-81）。
    本体不動点との完全一致は要さない概算で良い（lang_map は空＝既定起動を仮定）。
    """
    policy = SymbolPolicy(min_specificity=2, user_stoplist=frozenset())
    union: set[str] = set()
    for grep_file in sorted(Path(input_dir).glob("*.grep")):
        for raw in grep_file.read_bytes().split(b"\n"):
            parsed = parse_grep_line(raw)
            if parsed is None:
                continue
            path_b, lineno, content_b = parsed
            relpath = os.fsdecode(path_b)
            target = Path(source_root) / relpath
            try:
                text, _, _ = decode_bytes(target.read_bytes(), DEFAULT_FALLBACK)
            except OSError:
                continue
            # lang_map は空（既定起動を仮定）。effective_language で TS inline-template
            # 行を angular_inline へ retarget してから AST/行ベースの分岐を決める。
            language = effective_language(
                detect_language(relpath, text[:4096], {}), text, lineno)
            if language in _AST_CHASERS:
                cs = extract_chase_symbols_tree(language, text, lineno)
            else:
                dialect = (detect_shell_dialect(relpath, text[:4096])
                           if language == "shell" else "bourne")
                # _seed.py と同様に .grep 内容ではなく on-disk のファイル行を使う。
                lines = text.split("\n")
                content = lines[lineno - 1] if 0 <= lineno - 1 < len(lines) else ""
                cs = extract_chase_symbols(language, dialect, content)
            part = partition(cs, language, policy)
            union |= set(part.chase) | set(part.terminal)
    return union


def measure(symbols, source_root: Path) -> dict:
    """union 記号で rg prefilter → 候補総バイト・非UTF-8割合を測る。

    非UTF-8はファイル粒度で計上する（utf-8 デコード失敗なら当該ファイル全体を
    non_utf8 に算入）＝chardet がファイル単位で走るため意図的な近似。
    """
    source_root = Path(source_root)
    rel_to_abs = {p.relative_to(source_root).as_posix(): p
                  for p in source_root.rglob("*") if p.is_file()}
    keep = ripgrep.prefilter(source_root, rel_to_abs, sorted(symbols))
    if keep is None:
        keep = set(rel_to_abs)
    total = nonutf8 = 0
    for rel in keep:
        ap = rel_to_abs.get(rel)
        if ap is None:
            continue
        raw = ap.read_bytes()
        total += len(raw)
        try:
            raw.decode("utf-8")
        except UnicodeDecodeError:
            nonutf8 += len(raw)
    return {"candidate_files": len(keep), "candidate_bytes": total,
            "non_utf8_bytes": nonutf8,
            "non_utf8_ratio": (nonutf8 / total) if total else 0.0}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="probe_candidates")
    ap.add_argument("--input", required=True)
    ap.add_argument("--source-root", required=True, dest="source_root")
    ap.add_argument("--jobs", type=int, default=os.cpu_count() or 1,
                    help="chardet 予算上限（ceiling）の試算にのみ使用。"
                         "プローブ自体の候補読込は単一スレッド。")
    args = ap.parse_args(argv)
    union = compute_initial_union(Path(args.input), Path(args.source_root))
    rep = measure(union, Path(args.source_root))
    ceiling_mb = 3600 * 0.1 * args.jobs
    nonutf8_mb = rep["non_utf8_bytes"] / 1e6
    print(f"union_symbols   = {len(union)}")
    print(f"candidate_files = {rep['candidate_files']}")
    print(f"candidate_bytes = {rep['candidate_bytes']/1e9:.2f} GB")
    print(f"non_utf8        = {nonutf8_mb/1000:.2f} GB "
          f"({rep['non_utf8_ratio']*100:.1f}% of candidates)")
    print(f"chardet_ceiling = {ceiling_mb/1000:.2f} GB  (= 3600s x 0.1MB/s x {args.jobs} jobs)")
    verdict = "OPTION A (within budget)" if nonutf8_mb <= ceiling_mb \
        else "OPTION B recommended (cchardet) — first-hop chardet exceeds 1h"
    print(f"VERDICT: {verdict}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
