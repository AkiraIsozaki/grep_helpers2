"""言語別シンボル抽出 regex。

`extract_chase_symbols` と `extract_var_symbols` が、マスク後の行から
代入左辺・const 定義・getter/setter 等を切り出すために使う。

- SQL (Oracle/PL-SQL): 宣言/代入 `name [CONSTANT] [TYPE] := …` の先頭 id（型名は捨てる）。CONSTANT は定数。バインド `:v`／置換 `&v` は非抽出
- Shell (bourne): 行頭 `var=` の左辺
- Shell (cshell): `set v =` / `setenv V` / `@ v =` の左辺
注: Java/C は AST 化（_AST_CHASERS 経路）のため regex 非対象（除去済）。
"""

import re

# PL/SQL 宣言対応の := 抽出（C-C/R2-C1）。名前と := の間に実型トークンが
# あれば宣言形＝先頭 id を採り型名を捨てる。型トークン無しは通常代入＝その id。
# PL/SQL はキーワード大小無視＝IGNORECASE 必須（小文字 constant リーク防止）。
ORACLE_DECL_ASSIGN_RE = re.compile(
    r"(?<![:&])\b([A-Za-z_]\w*)(?:\s+(?:CONSTANT\s+)?[A-Za-z_][\w%.]*(?:\([^)]*\))?)?\s*:=",
    re.IGNORECASE)
ORACLE_CONSTANT_RE = re.compile(r"(?<![:&])\b([A-Za-z_]\w*)\s+CONSTANT\b", re.IGNORECASE)

BOURNE_ASSIGN_RE = re.compile(r"^\s*([A-Za-z_]\w*)=")

CSHELL_ASSIGN_RE = re.compile(
    r"^\s*(?:set\s+([A-Za-z_]\w*)\s*=|setenv\s+([A-Za-z_]\w*)\b|@\s+([A-Za-z_]\w*)\s*=)"
)

BOURNE_READONLY_RE = re.compile(r"^\s*readonly\s+([A-Za-z_]\w*)=")

# Perl: sigil 付き代入左辺（== / =~ / => は除外）。sigil は剥がして bare 識別子を採る。
PERL_ASSIGN_RE = re.compile(r"[$@%](\w+)\s*=(?![=~>])")
PERL_USE_CONSTANT_RE = re.compile(r"\buse\s+constant\s+(\w+)")

# GROOVY 正規表現（CONST/VAR）はカタストロフィックバックトラッキングを起こすため、
# 入力行をこの文字数で頭打ちにして最悪時間を有界化する（A-4 follow-up）。実 groovy
# 宣言の `name =` までの長さは十分下回る＝出力不変。実測: 200字で最悪 ~57ms。
GROOVY_LINE_CAP = 200

# Groovy: final 定数（static 任意・型任意）と一般代入左辺（限定子は剥がす＝§8.4）。
GROOVY_CONST_RE = re.compile(
    r"\b((?:public|protected|private|static|final)(?:\s+(?:public|protected|private|static|final))*)"
    r"\s+(?:[\w.$<>,\[\]\s]+?\s+)?([A-Za-z_]\w*)\s*=")
GROOVY_VAR_RE = re.compile(r"(?<![=!<>+\-*/%&|^])\b([A-Za-z_]\w*)\s*=(?!=)")
