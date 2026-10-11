#!/usr/bin/env python3
"""Phase 00 R2 inventory: ListObjectsV2 metadata only, no GetObject or downloads.
Run manually on the authorized server with existing private environment values.
Prints counts only (bucket name/key names are deliberately not included).
"""
import os
import json
import boto3


def count_prefixes(client, bucket, prefixes=('inputs/', 'outputs/', 'other')):
    tally = {p:0 for p in prefixes}
    total = 0
    paginator=client.get_paginator('list_objects_v2')
    for page in paginator.paginate(Bucket=bucket):
        for item in page.get('Contents', []):
            key=item.get('Key','')
            match=next((p for p in prefixes[:-1] if key.startswith(p)), prefixes[-1])
            tally[match] += 1
            total+=1
    return {'total_objects':total,'prefix_counts':tally,'source':'R2 ListObjectsV2 metadata only'}


def main():
    names=('R2_ENDPOINT_URL','R2_BUCKET','R2_ACCESS_KEY_ID','R2_SECRET_ACCESS_KEY')
    if not all(os.environ.get(k) for k in names):
        raise SystemExit('Missing private R2 configuration; no request was made')
    client=boto3.client('s3',endpoint_url=os.environ['R2_ENDPOINT_URL'],
        aws_access_key_id=os.environ['R2_ACCESS_KEY_ID'],
        aws_secret_access_key=os.environ['R2_SECRET_ACCESS_KEY'],
        region_name=os.environ.get('R2_REGION','auto'))
    print(json.dumps(count_prefixes(client, os.environ['R2_BUCKET']),sort_keys=True))

if __name__=='__main__':
    main()
