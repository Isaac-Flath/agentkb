#!/usr/bin/env python3
# /// script
# dependencies = ["boto3", "pyyaml"]
# ///
"""
Sync agentkb docs to S3 for isaacflath.com/agentkb.

Uploads markdown files from docs/ to s3://isaacflath/docs/agentkb/
and generates a docs-index.json with navigation metadata.

Usage:
    uv run scripts/sync-docs-to-s3.py [--dry-run]
"""

import json
import os
import sys
from pathlib import Path

import boto3
import yaml
from botocore.exceptions import ClientError

BUCKET_NAME = "isaacflath"
REGION = "us-east-1"
S3_PREFIX = "docs/agentkb"
DOCS_DIR = Path(__file__).parent.parent / "docs"


def get_s3_client():
    return boto3.client(
        "s3",
        region_name=os.environ.get("AWS_REGION", REGION),
        aws_access_key_id=os.environ.get("AWS_ACCESS_KEY_ID"),
        aws_secret_access_key=os.environ.get("AWS_SECRET_ACCESS_KEY"),
    )


def parse_frontmatter(text: str) -> dict:
    if not text.startswith("---"):
        return {}
    rest = text[3:]
    end = rest.find("\n---")
    if end == -1:
        return {}
    try:
        return yaml.safe_load(rest[:end]) or {}
    except yaml.YAMLError:
        return {}


def discover_docs() -> list[dict]:
    """Find all markdown files in docs/ and extract metadata."""
    docs = []
    for md_file in sorted(DOCS_DIR.rglob("*.md")):
        rel_path = md_file.relative_to(DOCS_DIR)

        # Skip internal design docs
        if rel_path.name.startswith("design-"):
            continue

        text = md_file.read_text()
        fm = parse_frontmatter(text)

        docs.append({
            "path": str(rel_path),
            "title": fm.get("title", rel_path.stem.replace("-", " ").title()),
            "description": fm.get("description", ""),
            "order": fm.get("order", 99),
        })

    docs.sort(key=lambda d: (d["path"].count("/"), d["order"], d["path"]))
    return docs


def upload_file(s3_client, local_path: Path, s3_key: str, dry_run: bool = False):
    if dry_run:
        print(f"[DRY-RUN] Would upload: {local_path} -> s3://{BUCKET_NAME}/{s3_key}")
        return True

    try:
        s3_client.upload_file(
            str(local_path),
            BUCKET_NAME,
            s3_key,
            ExtraArgs={"ContentType": "text/markdown; charset=utf-8"},
        )
        print(f"Uploaded: {local_path} -> s3://{BUCKET_NAME}/{s3_key}")
        return True
    except ClientError as e:
        print(f"Error uploading {local_path}: {e}")
        return False


def upload_json(s3_client, data: dict, s3_key: str, dry_run: bool = False):
    body = json.dumps(data, indent=2)
    if dry_run:
        print(f"[DRY-RUN] Would upload index: s3://{BUCKET_NAME}/{s3_key}")
        return True

    try:
        s3_client.put_object(
            Bucket=BUCKET_NAME,
            Key=s3_key,
            Body=body.encode("utf-8"),
            ContentType="application/json; charset=utf-8",
        )
        print(f"Uploaded index: s3://{BUCKET_NAME}/{s3_key}")
        return True
    except ClientError as e:
        print(f"Error uploading index: {e}")
        return False


def main():
    dry_run = "--dry-run" in sys.argv

    if not DOCS_DIR.exists():
        print(f"Docs directory not found: {DOCS_DIR}")
        sys.exit(1)

    s3_client = get_s3_client()

    # Discover and upload docs
    docs = discover_docs()
    print(f"Found {len(docs)} doc files")

    uploaded = 0
    for doc in docs:
        local_path = DOCS_DIR / doc["path"]
        s3_key = f"{S3_PREFIX}/{doc['path']}"
        if upload_file(s3_client, local_path, s3_key, dry_run=dry_run):
            uploaded += 1

    # Generate and upload index
    upload_json(s3_client, docs, f"{S3_PREFIX}/docs-index.json", dry_run=dry_run)

    print(f"\nDone: {uploaded} files uploaded to s3://{BUCKET_NAME}/{S3_PREFIX}/")


if __name__ == "__main__":
    main()
