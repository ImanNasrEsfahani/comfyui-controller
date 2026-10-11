#!/usr/bin/env python3
"""Issue a one-time invitation in a *private staging copy*. Raw token written 0600, not logged."""
from __future__ import annotations
import argparse
import os
import secrets
import sqlite3
from datetime import datetime,timedelta,timezone
from pathlib import Path
from uuid import uuid4
import hashlib


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--db',type=Path,required=True)
    p.add_argument('--email',required=True)
    p.add_argument('--token-file',type=Path,required=True)
    args=p.parse_args()
    mail=args.email.strip().casefold()
    if mail.count('@')!=1 or len(mail)>254 or any(c.isspace() for c in mail):
        p.error('Invalid invite email')
    if args.token_file.exists():
        p.error('Token output already exists; refusing overwrite')
    raw=secrets.token_urlsafe(48)
    now=datetime.now(timezone.utc)
    with sqlite3.connect(args.db) as conn:
        conn.execute('PRAGMA foreign_keys=ON')
        conn.execute('''INSERT INTO auth_invitations(id,email_normalized,token_hash,created_at,expires_at)
                        VALUES (?,?,?,?,?)''',(str(uuid4()),mail,hashlib.sha256(raw.encode()).hexdigest(),
                         now.isoformat(),(now+timedelta(days=7)).isoformat()))
    fd=os.open(args.token_file,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    with os.fdopen(fd,'w') as out:
        out.write(raw+'\n')
    print('Invitation created; token saved in a private 0600 file (not shown).')

if __name__=='__main__': main()
