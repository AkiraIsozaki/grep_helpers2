"""言語別 Chaser / Classifier モジュール群と Chaser registry。

`_CHASERS` は方式α（eager import）で各 *_chaser.py を import 時に登録する。
chase.py の dispatcher が `_CHASERS[language]` で対応モジュールを取得する。
"""

from grep_analyzer.classifiers import (
    c_chaser,
    java_chaser,
    perl_chaser,
    shell_chaser,
    sql_chaser,
)
from grep_analyzer.classifiers.base import Chaser

_CHASERS: dict[str, Chaser] = {
    "java": java_chaser,
    "c": c_chaser,
    "proc": c_chaser,
    "shell": shell_chaser,
    "sql": sql_chaser,
    "perl": perl_chaser,
}

__all__ = ["Chaser"]
