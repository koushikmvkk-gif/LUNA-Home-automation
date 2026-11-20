#!/usr/bin/env python3
"""Manage the people Luna knows from the keyboard (useful when voice recognition mishears a name).

  python3 tools/manage_people.py list
  python3 tools/manage_people.py rename "Rahool" "Rahul"
  python3 tools/manage_people.py tier Rahul master|priority1|priority2|least
  python3 tools/manage_people.py forget Rahul
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config as cfg
from buddy.people import PeopleStore, MASTER, PRIORITY, LEAST, rank_label

TIERS = {"master": (MASTER, 2), "priority1": (PRIORITY, 1), "priority2": (PRIORITY, 2), "least": (LEAST, 2)}
ps = PeopleStore(cfg)
a = sys.argv[1:]
if not a or a[0] == "list":
    for p in ps.people:
        print("%-20s %-14s samples=%d added=%s" % (p["name"], rank_label(ps.rank(p)), len(p["embeddings"]), p.get("added", "?")))
elif a[0] == "rename" and len(a) == 3:
    print("done" if ps.rename(a[1], a[2]) else "failed (name unknown or new name already used)")
elif a[0] == "tier" and len(a) == 3 and a[2] in TIERS:
    print("done" if ps.set_tier(a[1], *TIERS[a[2]]) else "unknown person")
elif a[0] == "forget" and len(a) == 2:
    try:
        print("done" if ps.forget(a[1]) else "unknown person")
    except ValueError:
        print("cannot remove the only master")
else:
    print(__doc__)
