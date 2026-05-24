"""言語別 Chaser / Classifier モジュール群と Chaser registry。

方式α（eager import）で各 *_chaser.py を import 時に登録する。chase.py の
dispatcher が言語に応じて以下いずれかから対応モジュールを取得する:
- `_AST_CHASERS`: tree-sitter AST で抽出する言語（java/c/proc/jsp/python/
  javascript/typescript/tsx/angular(_inline)）。
- `_CHASERS`: 行ベース regex で抽出する言語（shell/sql/perl/groovy）。
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

# 行ベース chaser（shell/sql/perl/groovy）
_CHASERS: dict[str, Chaser] = {
    "shell": shell_chaser, "sql": sql_chaser, "perl": perl_chaser, "groovy": groovy_chaser,
}
# AST ベース chaser（java/c/proc/jsp ＋ python/js/ts 系）
_AST_CHASERS: dict[str, ASTChaser] = {
    "python": python_chaser,
    "javascript": javascript_chaser,
    "typescript": typescript_chaser,
    "tsx": typescript_chaser,
    "angular": typescript_chaser,
    "angular_inline": typescript_chaser,
    "java": java_chaser,
    "c": c_chaser,
    "proc": c_chaser,
    "jsp": java_chaser,
}

__all__ = ["Chaser", "ASTChaser"]
