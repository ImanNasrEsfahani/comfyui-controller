#!/usr/bin/env python3
"""Redact probable credentials / signed URLs in CI artifacts before upload.

Defense in depth only: structured logging must avoid secrets at origin.
"""
from __future__ import annotations
import argparse,re
from pathlib import Path
PATTERNS=(
 (re.compile(r'(?i)(authorization\s*[:=]\s*(?:bearer|basic)\s+)\S+'),r'\1[REDACTED]'),
 (re.compile(r'(?i)\b((?:APP_INTERNAL_TOKEN|DIRECT_WORKER_TOKEN|AUTH_CSRF_SECRET|R2_SECRET_ACCESS_KEY|SALAD_API_KEY|AWS_SECRET_ACCESS_KEY|password)\s*[:=]\s*)\S+'),r'\1[REDACTED]'),
 (re.compile(r'(?i)([?&](?:X-Amz-(?:Signature|Credential|Security-Token)|signature|token|api_key)=)[^\s&]+'),r'\1[REDACTED]'),
 (re.compile(r'(?i)(https?://[^\s]+[?&](?:X-Amz-Signature|signature|token)=)[^\s&]+'),r'\1[REDACTED]'),
)
def redact(value:str)->str:
 for pattern,repl in PATTERNS:value=pattern.sub(repl,value)
 return value

def main(argv=None):
 ap=argparse.ArgumentParser();ap.add_argument('--input',type=Path,required=True);ap.add_argument('--output',type=Path,required=True)
 a=ap.parse_args(argv);a.output.parent.mkdir(parents=True,exist_ok=True)
 a.output.write_text(redact(a.input.read_text(encoding='utf8',errors='replace')),encoding='utf8')
 return 0
if __name__=='__main__':raise SystemExit(main())
