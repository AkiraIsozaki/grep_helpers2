"""言語別シンボル抽出 regex。

`extract_chase_symbols` と `extract_var_symbols` が、マスク後の行から
代入左辺・const 定義・getter/setter 等を切り出すために使う。

- SQL (Oracle): PL/SQL `var := 式` の左辺。バインド `:v`／置換 `&v` は非抽出
- Shell (bourne): 行頭 `var=` の左辺
- Shell (cshell): `set v =` / `setenv V` / `@ v =` の左辺
- Java: getter/setter, static final 定数, 一般変数代入
- C / Pro*C: `#define`, `const ... var =`, 一般変数代入
"""

import re

ORACLE_ASSIGN_RE = re.compile(r"(?<![:&])\b([A-Za-z_]\w*)\s*:=")

BOURNE_ASSIGN_RE = re.compile(r"^\s*([A-Za-z_]\w*)=")

CSHELL_ASSIGN_RE = re.compile(
    r"^\s*(?:set\s+([A-Za-z_]\w*)\s*=|setenv\s+([A-Za-z_]\w*)\b|@\s+([A-Za-z_]\w*)\s*=)"
)

JAVA_GETSET_RE = re.compile(r"\b((?:get|set)[A-Z]\w*)\s*\(")

JAVA_CONST_RE = re.compile(
    r"\b((?:public|protected|private|static|final)(?:\s+(?:public|protected|private|static|final))*)"
    r"\s+[\w.$]+(?:\s*<[^=;{}]*?>)?(?:\s*\[\s*\])*\s+([A-Za-z_]\w*)\s*=")

JAVA_VAR_RE = re.compile(r"(?<![=!<>+\-*/%&|^])\b([A-Za-z_]\w*)\s*=(?!=)")

C_DEFINE_RE = re.compile(r"^\s*#\s*define\s+([A-Za-z_]\w*)")

C_CONST_RE = re.compile(r"\bconst\b[\w\s*]*?\b([A-Za-z_]\w*)\s*=")

C_VAR_RE = re.compile(r"(?<![=!<>+\-*/%&|^])\b([A-Za-z_]\w*)\s*=(?!=)")

BOURNE_READONLY_RE = re.compile(r"^\s*readonly\s+([A-Za-z_]\w*)=")

# Perl: sigil 付き代入左辺（== / =~ / => は除外）。sigil は剥がして bare 識別子を採る。
PERL_ASSIGN_RE = re.compile(r"[$@%](\w+)\s*=(?![=~>])")
PERL_USE_CONSTANT_RE = re.compile(r"\buse\s+constant\s+(\w+)")

# Groovy: final 定数（static 任意・型任意）と一般代入左辺（限定子は剥がす＝§8.4）。
GROOVY_CONST_RE = re.compile(
    r"\b((?:public|protected|private|static|final)(?:\s+(?:public|protected|private|static|final))*)"
    r"\s+(?:[\w.$<>,\[\]\s]+?\s+)?([A-Za-z_]\w*)\s*=")
GROOVY_VAR_RE = re.compile(r"(?<![=!<>+\-*/%&|^])\b([A-Za-z_]\w*)\s*=(?!=)")
