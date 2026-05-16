"""direct-only パイプライン（spec §15 フェーズ1/1.5）。多ホップ追跡は Phase 2。"""

from pathlib import Path

from grep_analyzer.classifiers.regex_classifier import classify_shell, classify_sql
from grep_analyzer.classifiers.ts_classifier import classify_ts
from grep_analyzer.diagnostics import Diagnostics
from grep_analyzer.dispatch import (
    detect_language,
    detect_shell_dialect,
    extension_resolves_language,
    shebang_dialect,
)
from grep_analyzer.encoding import DEFAULT_FALLBACK, decode_bytes
from grep_analyzer.ingest import parse_grep_line
from grep_analyzer.model import Hit
from grep_analyzer.tsv import write_tsv


def _classify(language: str, dialect: str, file_text: str, lineno: int, content: str):
    if language in ("java", "c", "proc"):
        return classify_ts(language, file_text, lineno)
    if language == "sql":
        return classify_sql(content)
    if language == "shell":
        return classify_shell(content, dialect)
    # 未知言語は bourne shell 規則にフォールバック（Phase 2 で言語追加時は
    # dispatch と本関数の両方を更新すること）
    return classify_shell(content, "bourne")


def run(input_dir: Path, output_dir: Path, source_root: Path) -> int:
    """input/*.grep を処理し、キーワード毎TSV＋diagnostics.txt を出力する。"""
    diag = Diagnostics()
    output_dir.mkdir(parents=True, exist_ok=True)

    for grep_file in sorted(Path(input_dir).glob("*.grep")):
        keyword = grep_file.stem
        raw_bytes = grep_file.read_bytes()
        text, _, _ = decode_bytes(raw_bytes, DEFAULT_FALLBACK)
        hits: list[Hit] = []

        for raw_line in text.splitlines():
            parsed = parse_grep_line(raw_line)
            if parsed is None:
                diag.add("bad_grep_line", f"{grep_file.name}: {raw_line!r}")
                continue
            rel, lineno, content = parsed
            target = Path(source_root) / rel
            if not target.is_file():
                diag.add("missing_source", str(rel))
                continue
            file_text, enc, replaced = decode_bytes(target.read_bytes(), DEFAULT_FALLBACK)
            if replaced:
                diag.add("decode_replaced", str(rel))
            sample = file_text[:4096]
            language = detect_language(rel, sample, {})
            dialect = detect_shell_dialect(rel, sample) if language == "shell" else "bourne"
            # spec §5.1 手順3 に実際に到達した（拡張子で言語未確定）かつ非シェルの
            # シェバン → §8.4 として明示。既知拡張子で手順2 確定したものは手順3 に
            # 来ないため対象外（spec §5.1 のシェバン検出は手順3 限定）。
            if (
                not extension_resolves_language(rel, {})
                and language != "shell"
                and shebang_dialect(sample) == "other"
            ):
                diag.add("unsupported_shebang", str(rel))
            category, confidence = _classify(language, dialect, file_text, lineno, content)
            hits.append(Hit(
                keyword=keyword, language=language, file=rel, lineno=lineno,
                ref_kind="direct", category=category, category_sub="",
                usage_summary=f"{category} ({language})", via_symbol="",
                chain=f"{keyword}@{rel}:{lineno}", snippet=content,
                encoding=enc + (" 要確認" if replaced else ""), confidence=confidence,
            ))

        write_tsv(output_dir / f"{keyword}.tsv", hits, "utf-8-sig")

    (output_dir / "diagnostics.txt").write_text(diag.render(), encoding="utf-8")
    return 0
