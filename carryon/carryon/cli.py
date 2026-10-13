"""Local CLI: python -m carryon.cli import <export.zip|dir> ... / search <query>"""
from __future__ import annotations

import argparse
import logging

from . import db
from .importers import iter_conversations


def main():
    ap = argparse.ArgumentParser(prog="carryon")
    ap.add_argument("--db", default="carryon.db")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("import")
    p.add_argument("paths", nargs="+")
    s = sub.add_parser("search")
    s.add_argument("query")
    s.add_argument("--source")
    s.add_argument("-n", type=int, default=10)
    f = sub.add_parser("fetch")
    f.add_argument("id")
    sub.add_parser("stats")
    a = ap.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(message)s")
    con = db.connect(a.db)
    if a.cmd == "import":
        for path in a.paths:
            counts = {"new": 0, "updated": 0, "skipped": 0}
            for conv in iter_conversations(path):
                counts[db.upsert(con, conv)] += 1
            con.commit()
            print(path, counts)
        print(db.stats(con))
    elif a.cmd == "search":
        for h in db.search(con, a.query, a.n, a.source):
            print(f"{h['id']}  {h['title']}\n    {h['snippet']}\n")
    elif a.cmd == "fetch":
        c = db.fetch(con, a.id)
        print(c["text"] if c else "not found")
    else:
        print(db.stats(con))


if __name__ == "__main__":
    main()
