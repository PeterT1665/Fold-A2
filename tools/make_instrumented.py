"""Make a throwaway copy of macpoker-scaffold whose flop/turn/river record their equity estimate in LAST_EQ[0].

  python tools/make_instrumented.py /tmp/inst
"""
import os, re, shutil, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
dst = sys.argv[1]
shutil.rmtree(dst, ignore_errors=True)
shutil.copytree(os.path.join(ROOT, "macpoker-scaffold"), dst, ignore=shutil.ignore_patterns("__pycache__"))
ANCHORS = {
    "flop.py": r"    eq_r = 1\.0\n    for s in opps:\n        eq_r \*= rm\.equity\(my_b, info\.eq, ranges\[s\]\)",
    "turn.py": r"    eq_r = 1\.0\n    for s in opps:\n        eq_r \*= _equity\(combos, cws\[s\]\)\[1\]",
    "river.py": r"    eq_r = 1\.0\n    for s in opps:\n        eq_r \*= _equity\(my_score, combos, cws\[s\]\)\[1\]",
}
for fn, rx in ANCHORS.items():
    p = os.path.join(dst, fn); s = open(p).read(); m = re.search(rx, s)
    if not m: sys.exit(f"{fn}: eq_r loop not found (code changed?)")
    s = s.replace(m.group(0), m.group(0) + "\n    LAST_EQ[0] = eq_r\n", 1)
    s = s.replace("from __future__ import annotations", "from __future__ import annotations\n\nLAST_EQ = [None]  # instrumentation", 1)
    open(p, "w").write(s)
print("instrumented copy ->", dst)
