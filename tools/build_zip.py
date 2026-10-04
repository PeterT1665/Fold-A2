"""Build the upload zip from macpoker-scaffold/ with main.py at the zip root.

  python tools/build_zip.py              # -> dist/bot.zip
  python tools/build_zip.py my_bot.zip

Skips caches and the README, then checks the submission limits
(main.py at root, <= 300 files, <= 20 MB unpacked) and that the zipped bot
actually loads.
"""
import os
import sys
import tempfile
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, os.environ.get("BOT_SRC", "macpoker-scaffold"))
SKIP_DIRS = {"__pycache__", ".git"}
SKIP_FILES = {"README.md", ".DS_Store"}


def main():
    out = sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, "dist", "bot.zip")
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    files = []
    for d, dirs, names in os.walk(SRC):
        dirs[:] = [x for x in dirs if x not in SKIP_DIRS]
        for n in names:
            if n in SKIP_FILES or n.endswith(".pyc"):
                continue
            full = os.path.join(d, n)
            files.append((full, os.path.relpath(full, SRC).replace(os.sep, "/")))
    size = sum(os.path.getsize(f) for f, _ in files)
    assert any(a == "main.py" for _, a in files), "main.py missing"
    assert len(files) <= 300, f"{len(files)} files (max 300)"
    assert size <= 20 * 1024 * 1024, f"{size} bytes (max 20 MB)"
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for full, arc in sorted(files, key=lambda t: t[1]):
            z.write(full, arc)

    # load the bot from a clean unzip, the way the sandbox would
    from macpoker.sdk import load_bot_from_file
    with tempfile.TemporaryDirectory() as tmp:
        zipfile.ZipFile(out).extractall(tmp)
        bot = load_bot_from_file(os.path.join(tmp, "main.py"))
    print(f"built {out}: {len(files)} files, {size / 1024:.0f} KB unpacked, loads as {type(bot).__name__}")
    for _, a in sorted(files, key=lambda t: t[1]):
        print("  ", a)


if __name__ == "__main__":
    main()
