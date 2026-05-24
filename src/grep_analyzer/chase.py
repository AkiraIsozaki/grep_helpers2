"""追跡シンボル抽出 dispatcher。

各言語の規則は classifiers/ 以下の各 chaser に分散される。
行ベース（_CHASERS）: shell/sql/perl/groovy。
AST ベース（_AST_CHASERS）: python/javascript/typescript/tsx/angular/java/c/proc/jsp。
本ファイルは public API（extract_var_symbols / mask_literals / extract_chase_symbols）を
保持しつつ内部実装を Chaser に委譲する薄い dispatcher のみ。
"""

from grep_analyzer.classifiers import _AST_CHASERS, _CHASERS
from grep_analyzer.classifiers.shell_chaser import _extract_var_symbols as _shell_extract
from grep_analyzer.classifiers.sql_chaser import _extract_var_symbols as _sql_extract
from grep_analyzer.classifiers.ts_classifier import parse_tree
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


def extract_chase_symbols_from_root(language: str, root, lineno: int) -> ChaseSymbols:
    """parse 済 root から AST chaser で抽出（worker 用・file 単位1パース共有）。"""
    chaser = _AST_CHASERS.get(language)
    return ChaseSymbols() if chaser is None else chaser.extract_tree(language, root, lineno)


def extract_chase_symbols_tree(language: str, text: str, lineno: int) -> ChaseSymbols:
    """text を parse して AST chaser で抽出（seed/absorb 用）。非 AST 言語は空。"""
    if language not in _AST_CHASERS:
        return ChaseSymbols()
    return extract_chase_symbols_from_root(language, parse_tree(language, text), lineno)
