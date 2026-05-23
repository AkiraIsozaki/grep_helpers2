"""分類器の共通型と Chaser プロトコル。

ClassifyResult: direct 行の分類結果型。
Chaser: 言語別 Chaser サブモジュールが実装する抽出 IF。
"""

from typing import Callable, Protocol

from grep_analyzer.model import ChaseSymbols

ClassifyResult = tuple[str, str]


class Chaser(Protocol):
    """言語別 Chaser モジュールの抽出 IF。

    各 `*_chaser.py` がモジュールレベルで `extract` / `mask` を関数として
    公開し、`_CHASERS[language] = module` で登録する。属性形式の Protocol
    を採用することで、module オブジェクトを `Chaser` 型として扱える
    （mypy/pyright の structural 互換性）。
    """

    extract: Callable[[str, str], ChaseSymbols]
    """(dialect, line) → ChaseSymbols。line は生行（マスクは extract 内で実施）。"""

    mask: Callable[[str], str]
    """line → masked_line。同字数空白へ置換する。"""


class ASTChaser(Protocol):
    """AST 言語 chaser の抽出 IF（spec §6.6）。

    parse は呼出側（chase.py / worker）。本 IF は parse 済 root から
    束縛名のみ（name:/left: フィールド）を field-directed に抽出する。
    `language` は ts/tsx の grammar 変種・束縛規則の選択に使う。
    """

    extract_tree: Callable[[str, object, int], ChaseSymbols]
    """(language, root, lineno) → ChaseSymbols。root は parse 済 root_node。"""
