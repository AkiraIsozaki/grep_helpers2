"""言語別 Chaser / Classifier モジュール群と Chaser registry。

`_CHASERS` は方式α（eager import）で各 *_chaser.py を import 時に登録する。
chase.py の dispatcher が `_CHASERS[language]` で対応モジュールを取得する。
"""

from grep_analyzer.classifiers import (
    c_chaser,
    groovy_chaser,
    java_chaser,
    javascript_chaser,
    perl_chaser,
    python_chaser,
    shell_chaser,
    sql_chaser,
    typescript_chaser,
)
from grep_analyzer.classifiers.base import ASTChaser, Chaser

# 行ベース chaser（既存）
_CHASERS: dict[str, Chaser] = {
    "java": java_chaser, "c": c_chaser, "proc": c_chaser, "shell": shell_chaser,
    "sql": sql_chaser, "perl": perl_chaser, "groovy": groovy_chaser,
    "jsp": java_chaser,
}
# AST ベース chaser（新規・行版 _CHASERS には載せない）
_AST_CHASERS: dict[str, ASTChaser] = {
    "python": python_chaser,
    "javascript": javascript_chaser,
    "typescript": typescript_chaser,
    "tsx": typescript_chaser,
    "angular": typescript_chaser,
}

__all__ = ["Chaser", "ASTChaser"]
