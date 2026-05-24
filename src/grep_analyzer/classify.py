"""言語別行分類の共有実装。pipeline と fixedpoint が共通利用する。

Related: spec §7
"""

from grep_analyzer.classifiers.base import ClassifyResult
from grep_analyzer.classifiers.regex_classifier import (
    classify_groovy,
    classify_perl,
    classify_shell,
    classify_sql,
)
from grep_analyzer.classifiers.ts_classifier import classify_ts
from grep_analyzer.embed_preprocess import effective_language


def classify_hit(
    language: str, dialect: str, file_text: str, lineno: int, content: str,
    cache: dict | None = None,
) -> ClassifyResult:
    """1 ヒットを言語別に分類して (category, confidence) を返す（spec §7/§4）。

    java/c/proc は tree-sitter(high)、sql/shell は正規表現(medium)、未知は
    bourne shell フォールバック（pipeline 既存挙動と同一）。
    perl/groovy は正規表現分類(medium)。

    `cache` は parse_tree と共有するファイル単位のパース木辞書（build_snippet と
    同一 dict を渡せば同一ファイルの parse を 1 回に集約できる）。
    """
    language = effective_language(language, file_text, lineno)
    if language in ("java", "c", "proc", "python", "javascript", "typescript",
                    "tsx", "jsp", "angular", "angular_inline"):
        return classify_ts(language, file_text, lineno, cache=cache)
    if language == "html":
        return ("その他", "high")
    if language == "sql":
        return classify_sql(content)
    if language == "perl":
        return classify_perl(content)
    if language == "groovy":
        return classify_groovy(content)
    if language == "shell":
        return classify_shell(content, dialect)
    return classify_shell(content, "bourne")
