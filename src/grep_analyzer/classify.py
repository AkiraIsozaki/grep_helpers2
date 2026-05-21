"""言語別行分類の共有実装。pipeline と fixedpoint が共通利用する。

Related: spec §7
"""

from grep_analyzer.classifiers.base import ClassifyResult
from grep_analyzer.classifiers.regex_classifier import classify_shell, classify_sql
from grep_analyzer.classifiers.ts_classifier import classify_ts


def classify_hit(
    language: str, dialect: str, file_text: str, lineno: int, content: str
) -> ClassifyResult:
    """1 ヒットを言語別に分類して (category, confidence) を返す（spec §7）。

    java/c/proc は tree-sitter(high)、sql/shell は正規表現(medium)、未知は
    bourne shell フォールバック（pipeline 既存挙動と同一）。
    """
    if language in ("java", "c", "proc"):
        return classify_ts(language, file_text, lineno)
    if language == "sql":
        return classify_sql(content)
    if language == "shell":
        return classify_shell(content, dialect)
    return classify_shell(content, "bourne")
