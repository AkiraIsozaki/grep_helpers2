"""追跡シンボル抽出 dispatcher。

各言語の規則は `classifiers/{java,c,shell,sql}_chaser.py` に分散され、
`_CHASERS[language]` で取得する。本ファイルは public API
（extract_var_symbols / mask_literals / extract_chase_symbols）を保持しつつ
内部実装を Chaser に委譲する薄い dispatcher のみ。

Related: docs/superpowers/specs/2026-05-21-refactor-design.md §6 Phase 2 [B]
"""

from grep_analyzer.classifiers import _CHASERS
from grep_analyzer.classifiers.shell_chaser import _extract_var_symbols as _shell_extract
from grep_analyzer.classifiers.sql_chaser import _extract_var_symbols as _sql_extract
from grep_analyzer.model import ChaseSymbols


def extract_var_symbols(language: str, dialect: str, line: str) -> list[str]:
    """1 行から indirect:var 追跡シンボル（代入の左辺識別子）を抽出する。

    indirect:var 追跡で左辺識別子のみを必要とする呼出元から使われるため、
    Chaser を経由せず直接対応する `*_chaser._extract_var_symbols` を呼ぶ。
    対象外言語・該当なしは空リスト。
    """
    if language == "sql":
        return _sql_extract(dialect, line)
    if language == "shell":
        return _shell_extract(dialect, line)
    return []


def mask_literals(language: str, line: str) -> str:
    """文字列リテラル・コメントを同字数空白に置換する。

    言語が登録されていない場合は原行をそのまま返す（既存 behavior 保持）。
    """
    chaser = _CHASERS.get(language)
    return line if chaser is None else chaser.mask(line)


def extract_chase_symbols(language: str, dialect: str, line: str) -> ChaseSymbols:
    """1 行をマスク後に言語別 Chaser で分類抽出する（決定的・出現順）。

    対象外言語は空の ChaseSymbols を返す。
    """
    chaser = _CHASERS.get(language)
    if chaser is None:
        return ChaseSymbols()
    return chaser.extract(dialect, line)
