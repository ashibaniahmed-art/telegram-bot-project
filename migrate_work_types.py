#!/usr/bin/env python3
"""Migrate workers.work_type values to canonical emoji-labeled names.
This script imports khidmati (to reuse normalize_label and WORK_TYPES_NORMALIZED)
and updates rows in data.db. It creates a timestamped backup before modifying.
"""
import os
import shutil
import sqlite3
import datetime

import khidmati

ROOT = os.path.dirname(__file__)
DB = os.path.join(ROOT, "data.db")
if not os.path.exists(DB):
    print("data.db not found at:", DB)
    raise SystemExit(1)

bak = DB + ".bak.migration." + datetime.datetime.utcnow().strftime("%Y%m%d%H%M%S")
shutil.copy2(DB, bak)
print("Backup created:", bak)

conn = sqlite3.connect(DB)
cur = conn.cursor()
cur.execute("SELECT DISTINCT work_type FROM workers")
rows = [r[0] for r in cur.fetchall()]

changes = []
updated_count = 0
for wt in rows:
    if not wt:
        continue
    # if it's already a canonical entry (exact match), skip
    if wt in khidmati.WORK_TYPES:
        continue
    norm = khidmati.normalize_label(wt)
    canonical = khidmati.WORK_TYPES_NORMALIZED.get(norm) or khidmati.WORK_TYPES_NORMALIZED.get(khidmati.strip_definite_article(norm))
    if canonical and canonical != wt:
        print(f"Updating: '{wt}' -> '{canonical}'")
        cur.execute("UPDATE workers SET work_type=? WHERE work_type=?", (canonical, wt))
        updated_count += cur.rowcount
        changes.append((wt, canonical))

conn.commit()
conn.close()

print('\nMigration complete.')
print('Distinct values checked:', len(rows))
print('Values changed (pairs):', len(changes))
print('Approx rows updated (sum of rowcounts):', updated_count)
if changes:
    for old, new in changes:
        print(f" - {old} -> {new}")
print('Backup retained at:', bak)
print('Done.')
