#!/usr/bin/env python3
"""One-time interactive superadmin creation for the migrated live Controller.
Never accepts passwords on command-line arguments or in environment variables.
"""
from __future__ import annotations
import getpass
import os
import sqlite3
from uuid import uuid4
from app import auth, security

if os.environ.get('AUTH_ENABLED') != 'true':
    raise SystemExit('AUTH_ENABLED is not true')
if os.environ.get('DB_PATH') != '/app/data/controller.db':
    raise SystemExit('Unexpected live DB_PATH; refusing to create account')
if not os.environ.get('AUTH_PUBLIC_ORIGIN','').startswith('https://'):
    raise SystemExit('AUTH_PUBLIC_ORIGIN must be HTTPS')

print('Creates an active superadmin account. Use only on a private operator terminal.')
name = input('Admin display name: ').strip()
email = auth.normalized(input('Admin email: ').strip())
pw = getpass.getpass('Strong password (not echoed): ')
again = getpass.getpass('Repeat password: ')
if pw != again:
    raise SystemExit('Passwords did not match; nothing written')
hashed = auth.password_hash(pw)
del pw, again
now = security.iso()
with sqlite3.connect(os.environ['DB_PATH']) as db:
    db.execute('PRAGMA foreign_keys=ON')
    db.execute('BEGIN IMMEDIATE')
    if not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='users'").fetchone():
        raise SystemExit('Required user migration was not applied')
    if db.execute('SELECT id FROM users WHERE email_normalized=?', (email,)).fetchone():
        raise SystemExit('Account already exists; use existing login or controlled recovery')
    uid = str(uuid4())
    db.execute('''INSERT INTO users(id,email,email_normalized,password_hash,display_name,status,email_verified_at,created_at,updated_at)
    VALUES (?,?,?,?,?,'active',?,?,?)''',(uid,email,email,hashed,name or 'Administrator',now,now,now))
    db.execute('INSERT INTO user_roles(user_id,role_id,granted_at) VALUES(?,?,?)',(uid,'superadmin',now))
print('SUPERADMIN CREATED. Password was not printed or saved in scripts.')
