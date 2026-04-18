# agentkb commands
# Run `just` to see available recipes

set shell := ["bash", "-euo", "pipefail", "-c"]

default:
    @just --list

# Install or refresh this repo as an editable uv tool with a supported Python
install-tool:
    uv tool install --editable --force --python 3.13 .

# Sync docs to S3 for isaacflath.com/docs/agentkb
docs-publish:
    uv run scripts/sync-docs-to-s3.py

# Preview what docs would be uploaded
docs-publish-dry:
    uv run scripts/sync-docs-to-s3.py --dry-run

# Build code index for current project
index:
    uv run agentkb code index

# Index everything (code + KB + chats)
index-all:
    uv run agentkb index

# Run search
search query:
    uv run agentkb search "{{query}}"

# Bump version (major|minor|patch, default minor), build, publish to PyPI, commit, push
release bump="minor":
    #!/usr/bin/env bash
    set -euo pipefail
    case "{{bump}}" in major|minor|patch) ;; *) echo "bump must be major|minor|patch" >&2; exit 1 ;; esac
    current=$(sed -n 's/^version = "\(.*\)"/\1/p' pyproject.toml)
    IFS=. read -r major minor patch <<<"$current"
    case "{{bump}}" in
        major) major=$((major+1)); minor=0; patch=0 ;;
        minor) minor=$((minor+1)); patch=0 ;;
        patch) patch=$((patch+1)) ;;
    esac
    version="$major.$minor.$patch"
    echo "Bumping $current -> $version"
    sed -i '' "s/^version = \".*\"/version = \"$version\"/" pyproject.toml
    uv lock
    rm -rf dist/
    uv build
    uv publish
    git add pyproject.toml uv.lock
    git commit -m "Release v$version"
    git push
