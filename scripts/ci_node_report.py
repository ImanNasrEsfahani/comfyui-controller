#!/usr/bin/env python3
"""Fail closed on malformed or failing Node TAP, but report genuine skips."""
import argparse
import json
from pathlib import Path
import re
import sys

KEYS = ('tests', 'pass', 'fail', 'cancelled', 'skipped', 'todo')

def parse(text: str) -> dict:
    values = {}
    for key in KEYS:
        found = re.findall(r'^# ' + key + r'\s+(\d+)\s*$', text, re.M)
        if len(found) != 1:
            raise ValueError('Expected exactly one Node TAP summary for ' + key)
        values[key] = int(found[0])
    if values['tests'] < 1:
        raise ValueError('No Node tests ran')
    counted = values['pass'] + values['fail'] + values['cancelled'] + values['skipped']
    if counted != values['tests'] and counted + values['todo'] != values['tests']:
        raise ValueError('Node TAP totals inconsistent or missing test results')
    values['status'] = 'PASS' if values['fail'] == values['cancelled'] == 0 else 'FAIL'
    values['note'] = 'Skipped tests are explicitly reported, not counted as passing.'
    return values

def main():
    p=argparse.ArgumentParser();p.add_argument('--input',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    a=p.parse_args()
    try:
        result=parse(a.input.read_text(encoding='utf-8'))
        a.output.parent.mkdir(parents=True,exist_ok=True)
        a.output.write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
        print('NODE TAP SUMMARY: '+json.dumps(result,sort_keys=True))
        return 0 if result['status']=='PASS' else 1
    except (OSError,ValueError) as exc:
        print('NODE TAP INVALID: '+str(exc),file=sys.stderr);return 2
if __name__=='__main__':raise SystemExit(main())
