#!/usr/bin/env python3
"""Interactive Admin bootstrap on an isolated COPY after explicit verification.

No password argument/env variable, no hard-coded admin, no automatic account.
This command refuses DB targets without 'copy'/'test' in their filename.
"""
import argparse
from getpass import getpass
import sqlite3
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'backend'))
from app.identity_repository import seed_verified_admin


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--copy',type=Path,required=True)
    parser.add_argument('--email',required=True)
    parser.add_argument('--display-name',required=True)
    parser.add_argument('--evidence-ref',required=True)
    parser.add_argument('--approver',required=True)
    parser.add_argument('--verified-out-of-band',action='store_true',required=True)
    a=parser.parse_args()
    if not any(word in a.copy.name.lower() for word in ('copy','test')) or not a.copy.is_file():
        parser.error('Only an existing non-production SQLite copy is allowed')
    if not sys.stdin.isatty():
        parser.error('Requires an interactive TTY; no password in CLI arguments or logs')
    password=getpass('Admin password (hidden): ')
    confirm=getpass('Repeat password (hidden): ')
    if password!=confirm:
        parser.error('Password confirmation failed')
    with sqlite3.connect(a.copy) as conn:
        conn.row_factory=sqlite3.Row
        uid=seed_verified_admin(conn,email=a.email,password=password,display_name=a.display_name,
               verification_evidence=a.evidence_ref,approver=a.approver)
    print('Admin created on isolated copy only; identity:',uid)


if __name__=='__main__':
    main()
