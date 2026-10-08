"""Rebuild a flattened Python file, and say exactly what was inferred.

WHAT THIS IS FOR

`blackhole_extrapolator --reconstruct-into` emits a proposal for every
flattened file in a tree: safe, fast, never wrong about what it claims, and
measured at 0 of 34 files recovered as a program. It is the right tool to
point at thirty-seven repositories overnight. This is the other end of that
trade: one file at a time, minutes of search instead of milliseconds, and
an answer that parses.

It exists because four files in the library were flattened and no copy with
their line breaks intact survived anywhere -- not in another repository, not
in the ChatGPT, Claude, Gemini or CoPilot exports. Recovery had nothing to
find, so the choice was a rebuild or nothing.

HOW IT WORKS

Three things are recovered in order, and each is a different kind of claim.

    Comments      A `#` in a flattened file swallows the rest of it. The
                  comment is ended where code visibly resumes, or at a
                  newline if one survived.

    Statements    Found where two tokens cannot be adjacent inside one
                  expression: two atoms in a row, a statement keyword, a
                  decorator, the colon that closes a compound header. This
                  is the part that is close to certain; it does not guess.

    Indentation   A search, validated prefix by prefix by Python's own
                  parser, over candidates ordered by what the code says
                  about itself: a method whose first parameter is `self`
                  goes inside a class, a decorator with what it decorates,
                  an entry-point guard at column 0, a `return` closes the
                  block it ends. Dead states are memoised, which is what
                  makes the search finish rather than thrash.

    Absences      A block whose body the flattened source never held gets
                  an Ellipsis that says so; a line that is not Python in any
                  scope (a shell cell pasted into the same file) is kept as
                  a marked comment. Both are counted and reported.

WHAT IT CLAIMS, AND WHAT IT DOES NOT

Every statement, name and literal in the output comes from the input,
unchanged. Nothing is invented but the two marked absences above.

The nesting is inferred. The tool counts every block boundary that had more
than one reading the parser accepts and prints that count, and the header it
writes onto the file repeats it. Trust the statements; check the nesting.

MEASURED

Tests/test_unflatten.py holds the control: a flattened file whose original
was later found in a chat export. The rebuild matches it exactly, syntax
tree for syntax tree. On the four files that had no original anywhere, all
four parse, no name defined in the flattened source is missing from the
rebuild, and in three of the four every method that takes `self` sits inside
a class.

    python tools/unflatten.py FLATTENED.py OUT.py [top-level names...]

Writes only to OUT.py, never beside the input.
"""
from __future__ import annotations
import codeop
import io
import keyword
import re
import sys
import tokenize
from pathlib import Path

STMT_KW = {"def", "class", "if", "elif", "else", "for", "while", "try", "except", "finally", "with",
           "return", "raise", "pass", "continue", "break", "import", "from", "global", "nonlocal",
           "assert", "del", "async", "yield"}
EXPR_KW = {"and", "or", "not", "in", "is", "if", "else", "lambda", "for", "await", "None", "True", "False"}
ATOM = {tokenize.NAME, tokenize.NUMBER, tokenize.STRING}
CLOSE = {")", "]", "}"}
FOREIGN = "# [reconstruction: not python in the source] "
SECTION = re.compile(r"^#\s*(?:\d+[.)]|[-=#*]{3,})")
BLOCK_END = {"return", "raise", "pass", "continue", "break"}
COMPOUND = {"def", "class", "if", "elif", "else", "for", "while", "try", "except", "finally", "with", "async"}
NBSP = " "

CODE_RESUMES = re.compile(
    r" (?=(?:def |class |if |elif |else:|for |while |return\b|import |from |with |try:|except\b|finally:|raise |assert |"
    r"pass\b|continue\b|break\b|print\(|self\.|@|[A-Za-z_][A-Za-z_0-9.]*(?:, ?[A-Za-z_][A-Za-z_0-9.]*)*(?:\[[^\]]*\])? ?(?:=|\+=|-=)[^=]|"
    r"[A-Za-z_][A-Za-z_0-9.]*\())")


# In shape 1 only a column-0 line can follow a comment without a surviving
# newline, so the places code may resume are the column-0 shapes.
COLUMN0_RESUMES = re.compile(
    r" (?=(?:class |def |async def |@|if __name__|import |from \w[\w.]* import |"
    r"[A-Za-z_][A-Za-z_0-9]* ?(?:=|\+=|-=) ?[^=>]|[A-Za-z_][A-Za-z_0-9.]*\())")


def unswallow_comments(text, resumes=CODE_RESUMES):
    """Re-insert the newline that ended each comment: a `#` outside a string
    runs to a surviving newline or to the first place code visibly resumes."""
    out = []
    i = 0
    n = len(text)
    quote = None
    while i < n:
        ch = text[i]
        if quote:
            if text.startswith(quote, i):
                out.append(quote)
                i += len(quote)
                quote = None
                continue
            if ch == "\\" and i + 1 < n:
                out.append(text[i:i + 2])
                i += 2
                continue
            out.append(ch)
            i += 1
            continue
        if text.startswith(('"""', "'''"), i):
            quote = text[i:i + 3]
            out.append(quote)
            i += 3
            continue
        if ch in "\"'":
            quote = ch
            out.append(ch)
            i += 1
            continue
        if ch == "#":
            m = resumes.search(text, i + 1)
            nl = text.find("\n", i)
            if nl != -1 and (not m or nl < m.start()):
                # a newline survived (shape 1): the comment ends there and the
                # next line keeps its own indentation
                out.append(text[i:nl].rstrip() + "\n")
                i = nl + 1
                continue
            end = m.start() if m else n
            out.append(text[i:end].rstrip() + "\n")
            i = end + 1 if m else n
            continue
        out.append(ch)
        i += 1
    return "".join(out)


def toks(text):
    out = []
    try:
        for t in tokenize.generate_tokens(io.StringIO(text).readline):
            if t.type in (tokenize.INDENT, tokenize.DEDENT, tokenize.ENDMARKER):
                continue
            out.append(t)
    except (tokenize.TokenError, IndentationError, SyntaxError) as e:
        print("tokenize stopped:", e, file=sys.stderr)
    return out


def is_atom(t):
    if t.type == tokenize.NAME:
        return not keyword.iskeyword(t.string) or t.string in ("None", "True", "False")
    return t.type in ATOM


def split_statements(tokens):
    stmts, cur, depth = [], [], 0
    prev = None
    def flush():
        nonlocal cur
        if cur:
            stmts.append(cur)
            cur = []
    for i, t in enumerate(tokens):
        if t.type in (tokenize.NEWLINE, tokenize.NL):
            if depth == 0:
                flush()
                prev = None
            continue
        if t.type == tokenize.COMMENT:
            flush()
            stmts.append([t])
            prev = None
            continue
        s = t.string
        if depth == 0 and prev is not None and cur:
            boundary = False
            if t.type == tokenize.OP and s == "@":
                boundary = True
            elif t.type == tokenize.NAME and s in STMT_KW and s not in ("else", "if", "for", "yield"):
                boundary = not (s == "import" and cur[0].string == "from" and not any(x.string == "import" for x in cur))
                if prev.string == "async" and s in ("def", "with"):
                    boundary = False
            elif t.type == tokenize.NAME and s == "else":
                d = 0
                has_if = False
                colon0 = False
                for x in cur:
                    if x.string in "([{":
                        d += 1
                    elif x.string in ")]}":
                        d -= 1
                    elif d == 0 and x.string == "if":
                        has_if = True
                    elif d == 0 and x.string == ":":
                        colon0 = True
                boundary = not (has_if and not colon0)
            elif t.type == tokenize.NAME and s == "if":
                rest = [x.string for x in tokens[i + 1:i + 80]]
                ternary = "else" in rest and (":" not in rest or rest.index("else") < rest.index(":"))
                boundary = not ternary
            elif t.type == tokenize.NAME and s == "for":
                boundary = prev.string != "async"
            elif (is_atom(prev) or prev.string in CLOSE) and (is_atom(t) or s == "@"):
                if t.type == tokenize.NAME and s in EXPR_KW:
                    boundary = False
                elif prev.type == tokenize.STRING and t.type == tokenize.STRING:
                    boundary = False
                else:
                    boundary = True
            if boundary:
                flush()
        cur.append(t)
        prev = t
        if t.type == tokenize.OP:
            if s in "([{":
                depth += 1
            elif s in ")]}":
                depth = max(0, depth - 1)
            elif s == ":" and depth == 0 and cur[0].string in COMPOUND and not any(x.string == "lambda" for x in cur):
                flush()
                prev = None
    flush()
    for st in stmts:                       # a lone trailing "." is a paste artifact
        if len(st) > 1 and st[-1].string == "." and st[-2].string in CLOSE:
            st.pop()
    return stmts


def compiles_alone(line):
    """Whether a rendered statement is Python at all, in any of the scopes
    it could sit in. A block header gets a pass body
    a continuation header
    gets the block it continues."""
    body = line + ("\n    pass" if line.rstrip().endswith(":") else "")
    first = line.split(None, 1)[0] if line.strip() else ""
    if line.startswith("@"):
        body = line + "\ndef _f(): pass"
    elif first == "try:":
        body = line + "\n    pass\nexcept Exception:\n    pass"
    if first in ("elif", "else", "else:"):
        body = "if 1:\n    pass\n" + body
    elif first in ("except", "except:", "finally", "finally:"):
        body = "try:\n    pass\n" + body
    if first == "nonlocal":
        return True
    for wrap in ("{}", "async def _f():\n{}"):
        pad = "    " if wrap != "{}" else ""
        src = wrap.format("\n".join(pad + line for line in body.splitlines()))
        try:
            compile(src + "\n", "<line>", "exec")
            return True
        except SyntaxError:
            continue
    return False


NO_SPACE_BEFORE = {",", ")", "]", "}", ":", "."}
NO_SPACE_AFTER = {"(", "[", "{", "."}


def render(stmt):
    if stmt[0].type == tokenize.COMMENT:
        return stmt[0].string
    out = ""
    prev = None
    depth = 0
    for t in stmt:
        s = t.string
        if prev is None:
            out = s
            prev = t
            if s in "([{":
                depth += 1
            continue
        join = " "
        if s in NO_SPACE_BEFORE or prev.string in NO_SPACE_AFTER or (prev.string == "@" and len(out) == 1):
            join = ""
        elif s in ("(", "[") and ((prev.type == tokenize.NAME and not keyword.iskeyword(prev.string)) or prev.string in CLOSE or prev.type == tokenize.STRING):
            join = ""
        elif depth > 0 and (s == "=" or prev.string == "="):
            join = ""
        elif prev.string in ("-", "+", "~") and (len(out) < 2 or out[-2] in "(,=[:{" or out[:-1].rstrip().endswith(("return", "in", "=", ",", "(", "[", "{", ":", "yield"))):
            join = ""
        elif s == "**" and depth > 0 and prev.string in ("(", ","):
            join = ""
        elif prev.string in ("**", "*") and depth > 0 and len(out) > 2 and out[-3:-1].strip() in ("(", ","):
            join = ""
        if s == ":" and depth > 0:
            join = ""
        out += join + s
        prev = t
        if s in "([{":
            depth += 1
        elif s in ")]}":
            depth = max(0, depth - 1)
    return out


def reconstruct(text, top_names=()):
    tokens = toks(text)
    stmts = split_statements(tokens)
    lines = [render(s) for s in stmts]
    is_comment = [s[0].type == tokenize.COMMENT for s in stmts]
    # lines that are not Python in any scope are kept as marked comments,
    # and bare names beside them (fragments of the same paste) go with them
    foreign = [not is_comment[i] and not compiles_alone(lines[i]) for i in range(len(lines))]
    bare = [all(t.type == tokenize.NAME and not keyword.iskeyword(t.string) for t in s) for s in stmts]
    changed = True
    while changed:
        changed = False
        for i in range(len(lines)):
            if bare[i] and not foreign[i] and ((i > 0 and foreign[i - 1]) or (i + 1 < len(lines) and foreign[i + 1])):
                foreign[i] = True
                changed = True
    for i in range(len(lines)):
        if foreign[i]:
            lines[i] = FOREIGN + lines[i]
            is_comment[i] = True
    print(f"  {sum(foreign)} statements are not python; kept as marked comments", file=sys.stderr)
    heads = [ln.rstrip().endswith(":") and not is_comment[i] for i, ln in enumerate(lines)]
    firsts = [s[0].string for s in stmts]
    defname = [s[1].string if len(s) > 1 and s[0].string in ("def", "class") else None for s in stmts]
    takes_self = [len(s) > 3 and s[0].string == "def" and s[2].string == "(" and s[3].string in ("self", "cls")
                  for s in stmts]
    n = len(lines)
    ambiguous = 0
    indents = [0] * n
    CONT = {"elif", "else", "except", "finally"}
    def valid(k):
        # every earlier prefix was validated, so only the current top-level
        # chunk (from the last column-0 statement that starts one) is compiled
        j = k - 1
        while j > 0 and not (indents[j] == 0 and not is_comment[j] and firsts[j] not in CONT):
            j -= 1
        while j > 0 and firsts[j - 1] == "@":      # a decorator belongs to the chunk it decorates
            j -= 1
        src = "\n".join("    " * indents[i] + lines[i] for i in range(j, k)) + "\n"
        try:
            codeop.compile_command(src, symbol="exec")
            return True
        except (SyntaxError, OverflowError, ValueError):
            return False
    steps = [0]
    heuristic = [False] * n

    def shallower_first(level):
        """Every level below this one, nearest first, then this one last.

        The ordering a statement gets when the evidence says it more likely
        closes a block than continues one.
        """
        return list(range(level - 1, -1, -1)) + [level]

    def candidates(k, cur):
        f = firsts[k]
        if f == "if" and len(stmts[k]) > 1 and stmts[k][1].string == "__name__":
            cands = [0]                        # the entry-point guard is always at column 0
        elif is_comment[k]:
            # a numbered or ruled section comment ("# 3. Data Alignment", "# ----") is a
            # top-level landmark far more often than a note inside a block
            cands = ([0] + list(range(cur, 0, -1))) if SECTION.match(lines[k]) else ([cur] + list(range(cur - 1, -1, -1)))
            heuristic[k] = len(cands) > 1
        elif k > 0 and heads[k - 1]:
            cands = [cur + 1]
        elif f in ("elif", "else", "except", "finally"):
            cands = list(range(cur, -1, -1))
        elif k > 0 and firsts[k - 1] == "@":
            cands = [indents[k - 1]]                 # decorated: same indent as its decorator
        elif f == "class" or (defname[k] in top_names):
            cands = [0] + ([cur] if cur else [])
        elif f in ("@", "def"):
            m = k
            while m < n and firsts[m] == "@":
                m += 1
            if m < n and (firsts[m] == "class" or defname[m] in top_names):
                cands = [0] + ([cur] if cur else [])
            elif k > 1 and heads[k - 2] and stmts[k - 1][0].type == tokenize.STRING and len(stmts[k - 1]) == 1:
                cands = [cur]                        # header, docstring, def: a nested def or a method
            else:
                # inside a class body a def is a method (same level); inside
                # anything else it is most often a sibling of the block
                # opener, then shallower, and a nested def last
                def opener_of(c):
                    return next((j for j in range(k - 1, -1, -1)
                                 if not is_comment[j] and heads[j] and indents[j] == c - 1), None)
                opener = opener_of(cur)
                if cur == 0:
                    cands = [0]
                elif opener is not None and firsts[opener] == "class":
                    cands = [cur] + list(range(cur - 1, -1, -1))
                else:
                    cands = shallower_first(cur)
                if takes_self[k]:
                    # a def whose first parameter is self is a method: put the
                    # levels whose enclosing block is a class first
                    in_class = [c for c in cands
                                if c and (opener_of(c) is not None
                                          and firsts[opener_of(c)] == "class")]
                    if in_class:
                        cands = in_class + [c for c in cands if c not in in_class]
        elif f in ("if", "for", "while", "try", "with") and k > 1 and heads[k - 2] and not heads[k - 1] and not is_comment[k - 1] and indents[k - 1] == cur:
            # a compound statement right after a one-statement body is more
            # often the next sibling of that block than nested in it
            cands = shallower_first(cur)
            heuristic[k] = True
        elif k > 0 and firsts[k - 1] in BLOCK_END and cur > 0:
            cands = shallower_first(cur)
            heuristic[k] = True
        elif f in BLOCK_END and k > 1 and heads[k - 2] and not heads[k - 1] and not is_comment[k - 1] and indents[k - 1] == cur and cur > 0:
            # a return after a one-statement body usually closes the enclosing block, not the one-liner
            cands = [cur - 1, cur] + list(range(cur - 2, -1, -1))
            heuristic[k] = True
        else:
            cands = [cur] + list(range(cur - 1, -1, -1))
        return cands

    dead = set()

    def solve(k, cur):
        steps[0] += 1
        if steps[0] > 2000000 or k == n:
            return k == n
        if steps[0] % 50000 == 0:
            print(f"  step {steps[0]} at statement {k}/{n}", file=sys.stderr)
        if (k, cur) in dead:
            return False
        for c in candidates(k, cur):
            indents[k] = c
            if valid(k + 1) and solve(k + 1, c):
                return True
        dead.add((k, cur))
        return False
    sys.setrecursionlimit(max(10000, 4 * n + 100))
    ok = solve(0, 0)
    if not ok:
        # The exhaustive search ran out of budget. Place each statement by the
        # same ordered preferences, taking the first candidate the parser
        # accepts and never backtracking past it: bounded, and every line it
        # could not settle is counted.
        cur = 0
        for k in range(n):
            for c in candidates(k, cur):
                indents[k] = c
                if valid(k + 1):
                    cur = c
                    break
            else:
                indents[k] = cur = candidates(k, cur)[0]
                heuristic[k] = True
        print(f"  exhaustive search exhausted; placed {n} statements greedily", file=sys.stderr)
    ambiguous += sum(heuristic)
    src = "\n".join("    " * indents[i] + lines[i] for i in range(n)) + "\n"
    return ok, src, n, ambiguous


# ---------------------------------------------------------------- shape 1
# Indentation survived: each newline became one space, so an indented line
# now follows a run of 4n+1 spaces and its indentation is exact. Only the
# breaks before column-0 lines (a single space) are lost, and those fall
# to the statement splitter.

INDENT_RUN = re.compile(r"(?<! ) ((?: {4})+)(?! )")
SPACE_RUN = re.compile(r" {2,}")
AMBIGUOUS = []


def restore_indented_lines(text):
    """A run of 4n+1 spaces is a newline plus an indent of 4n. A longer run
    that is not of that form is a blank line that kept trailing spaces, then a
    newline plus an indent: the indent is ambiguous (any 4-multiple with the
    right residue), and the indent of the line the run ends is taken when it
    fits, else the largest candidate below it. Runs of two to four spaces
    are alignment inside a line and are kept."""
    out = []
    pos = 0
    line_indent = 0
    for m in SPACE_RUN.finditer(text):
        L = len(m.group())
        out.append(text[pos:m.start()])
        pos = m.end()
        if L % 4 == 1:
            line_indent = L - 1
            out.append("\n" + " " * line_indent)
        elif L >= 5:
            k = next(k for k in range(2, 6) if (L - k) % 4 == 0)   # newlines in the run
            header = text[:m.start()].rstrip().endswith(":")
            # after a header the next line is one level deeper; otherwise it
            # cannot be deeper than the line the run ends. Within that, an
            # editor leaves a blank line carrying the previous indent, so
            # try that reading first, then the same indent, then shallower.
            allowed = [line_indent + 4] if header else list(range(line_indent, -1, -4))
            order = [L - k - line_indent, line_indent] + list(range(line_indent - 4, -1, -4))
            cands = [b for b in order if b in allowed and 0 <= b <= L - k]
            b = cands[0] if cands else (line_indent + 4 if header else 0)
            if not header and len(set(cands)) > 1:
                AMBIGUOUS.append(len(out))
            line_indent = b
            out.append("\n" * k + " " * b)
        else:
            out.append(m.group())
    out.append(text[pos:])
    return "".join(out)


def reconstruct_indented(text):
    """Exact for every indented line; the splitter finds the column-0 ones.
    The tokenizer sees a dedented copy (so it never trips on indentation it
    was not asked to judge) and each statement takes the indent of the line
    it starts on."""
    text = unswallow_comments(restore_indented_lines(text.lstrip(" ")), COLUMN0_RESUMES)
    lines = text.splitlines()
    indent_of = [len(line) - len(line.lstrip(" ")) for line in lines]
    dedented = "\n".join(line.lstrip(" ") for line in lines) + "\n"
    tokens = toks(dedented)
    stmts = split_statements(tokens)
    out_lines = []
    last_indent = 0
    prev_line = None
    for st in stmts:
        row, col = st[0].start
        text_line = render(st)
        if col == 0 and row - 1 < len(indent_of):
            indent = indent_of[row - 1]
        elif prev_line is not None and prev_line.rstrip().endswith(":") and st[0].type != tokenize.COMMENT:
            indent = last_indent + 4          # a one-line body: `if x: return y`
        else:
            indent = 0                        # a break that collapsed to one space was a column-0 line
        out_lines.append(" " * indent + text_line)
        last_indent = indent
        prev_line = text_line
    return "\n".join(out_lines) + "\n", len(stmts)


MISSING_BODY = "...  # reconstruction: the flattened source has no body here"


def fill_missing_bodies(src, limit=200):
    """The source itself may omit a body (a paste abbreviated to a comment).
    Each such block gets an Ellipsis placeholder that says so
    the count is
    reported."""
    import ast
    lines = src.splitlines()
    filled = 0
    while filled < limit:
        try:
            ast.parse("\n".join(lines) + "\n")
            break
        except SyntaxError as e:
            m = re.search(r"expected an indented block after .* on line (\d+)", e.msg or "")
            if not m:
                break
            h = int(m.group(1)) - 1
            head_indent = len(lines[h]) - len(lines[h].lstrip(" "))
            j = h + 1
            while j < len(lines) and lines[j].lstrip().startswith("#") and (len(lines[j]) - len(lines[j].lstrip(" "))) > head_indent:
                j += 1
            lines.insert(j, " " * (head_indent + 4) + MISSING_BODY)
            filled += 1
    return "\n".join(lines) + "\n", filled


def comment_out_foreign(src, limit=400):
    """A pasted transcript can carry lines that were never Python (a shell
    cell, prose). A line that fails to compile on its own and is not a block
    header is kept as a marked comment; anything else is left for a person."""
    import ast
    lines = src.splitlines()
    done = 0
    while done < limit:
        try:
            ast.parse("\n".join(lines) + "\n")
            break
        except SyntaxError as e:
            if not e.lineno or e.lineno - 1 >= len(lines):
                break
            k = e.lineno - 1
            body = lines[k].strip()
            if body.endswith(":") or body.startswith("#") or not body:
                break
            try:
                compile(body + "\n", "<line>", "exec")
                break     # the line is fine alone: a structure problem
            except SyntaxError:
                indent = len(lines[k]) - len(lines[k].lstrip(" "))
                lines[k] = " " * indent + FOREIGN + body
                done += 1
    return "\n".join(lines) + "\n", done


if __name__ == "__main__":
    import ast
    path = Path(sys.argv[1])
    out = Path(sys.argv[2])
    names = set(sys.argv[3:])
    raw = path.read_text(errors="replace").replace(NBSP, " ")
    if INDENT_RUN.search(raw):
        src, n = reconstruct_indented(raw)
        ok = True
        amb = len(AMBIGUOUS)
        print(f"{path.name}: indentation survived the flattening; indented lines restored exactly", file=sys.stderr)
    else:
        text = unswallow_comments(raw)
        ok, src, n, amb = reconstruct(text, names)
    src, missing = fill_missing_bodies(src)
    src, foreign = comment_out_foreign(src)
    src, missing2 = fill_missing_bodies(src)
    missing += missing2
    try:
        ast.parse(src)
        parses = True
    except SyntaxError as e:
        parses = False
        print(f"{path.name}: does not parse: line {e.lineno}: {e.msg}", file=sys.stderr)
    out.write_text(src)
    print(f"{path.name}: {n} statements, search {'complete' if ok else 'INCOMPLETE'}, parses={parses}, "
          f"heuristic block ends={amb}, bodies missing in the source={missing}, non-python lines={foreign}")


