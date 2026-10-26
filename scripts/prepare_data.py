"""Read-only ICSE 2024 artifact ingestion and conservative CI screening."""
import argparse
import base64
import csv
import hashlib
import io
import json
import os
from pathlib import Path
import re
import socket
import sys
import time
import urllib.error
import urllib.request
import zipfile
from datetime import datetime, timezone

import yaml

SOURCE = 'sola-st/github-workflow-resource-optimization'
ASSET = 'https://github.com/' + SOURCE + '/releases/download/v1.0.0/data_set.zip'


def download_artifact(destination):
    """Download with range-based resume; keep partial bytes after transient failures."""
    partial = destination.with_suffix('.partial')
    for attempt in range(8):
        offset = partial.stat().st_size if partial.exists() else 0
        headers = {'User-Agent': 'CloudTune-research-collector'}
        if offset:
            headers['Range'] = f'bytes={offset}-'
        try:
            with urllib.request.urlopen(urllib.request.Request(ASSET, headers=headers), timeout=90) as response:
                if offset and response.status != 206:
                    # Server ignored Range; restart from byte zero to avoid a corrupt ZIP.
                    offset = 0
                    mode = 'wb'
                else:
                    mode = 'ab' if offset else 'wb'
                with partial.open(mode) as target:
                    while chunk := response.read(1024 * 1024):
                        target.write(chunk)
                if response.headers.get('Content-Length') is None or partial.stat().st_size >= offset + int(response.headers['Content-Length']):
                    partial.replace(destination)
                    return
        except (TimeoutError, socket.timeout, urllib.error.URLError, ConnectionError) as exc:
            if attempt == 7:
                raise RuntimeError(f'Download interrupted after 8 attempts; resume file kept at {partial}') from exc
            print(f'Download interrupted; resuming in {min(2 ** attempt, 30)}s (attempt {attempt + 1}/8).', flush=True)
            time.sleep(min(2 ** attempt, 30))
    raise RuntimeError(f'Could not finish artifact download; resume file kept at {partial}')


def request(url, token=None):
    headers = {'User-Agent': 'CloudTune-research-collector', 'Accept': 'application/vnd.github+json'}
    if token:
        headers['Authorization'] = 'Bearer ' + token
    for attempt in range(4):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=90) as response:
                return response.read()
        except urllib.error.HTTPError as exc:
            if exc.code not in (429, 500, 502, 503, 504) or attempt == 3:
                raise
            time.sleep(min(int(exc.headers.get('Retry-After', '5')), 60))


def digest(data):
    return hashlib.sha256(data).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--artifact', type=Path, help='Official data_set.zip; downloaded when omitted')
    parser.add_argument('--output', type=Path, default=Path('research-data'))
    parser.add_argument('--repo-column', help='Override repository identity column in all_repositories.csv')
    parser.add_argument('--limit', type=int, default=5, help='Maximum repositories screened, default 5')
    args = parser.parse_args()
    if args.limit < 1:
        parser.error('--limit must be positive')
    args.output.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    out = args.output / stamp
    out.mkdir()
    artifact = args.artifact or args.output / 'data_set.zip'
    if not artifact.exists():
        if args.artifact:
            parser.error('Artifact file does not exist')
        print('Downloading official artifact (may be large)...', flush=True)
        download_artifact(artifact)
    artifact_hash = hashlib.file_digest(artifact.open('rb'), 'sha256').hexdigest()
    with zipfile.ZipFile(artifact) as archive:
        names = [n for n in archive.namelist() if n.rsplit('/', 1)[-1] == 'all_repositories.csv']
        if len(names) != 1:
            raise ValueError('Expected exactly one all_repositories.csv in official artifact')
        raw = archive.read(names[0])
    reader = csv.DictReader(io.StringIO(raw.decode('utf-8-sig')))
    columns = reader.fieldnames or []
    column = args.repo_column or next((c for c in ('full_name', 'repository', 'repo', 'name', 'html_url', 'url') if c in columns), None)
    if column not in columns:
        raise ValueError(f'Select --repo-column from {columns}')
    candidates = set()
    for row in reader:
        value = row[column].strip()
        value = re.sub(r'^https://(?:api\.)?github.com/(?:repos/)?', '', value).rstrip('/')
        if re.fullmatch(r'[\w.-]+/[\w.-]+', value):
            candidates.add(value)
    if not candidates:
        raise ValueError('No owner/repository identities found; check --repo-column')
    manifest = {'paper_doi': '10.1145/3597503.3623303', 'source_url': ASSET,
                'artifact_sha256': artifact_hash, 'member': names[0], 'csv_sha256': digest(raw),
                'repository_column': column, 'candidate_count': len(candidates),
                'selection': 'sorted identities, first limit; convenience pilot, not random evaluation sample',
                'limit': args.limit, 'collected_at_utc': stamp}
    (out / 'source_manifest.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
    token = os.environ.get('GITHUB_TOKEN')

    def api(path):
        url = 'https://api.github.com/repos/' + path
        try:
            return json.loads(request(url, token))
        except urllib.error.HTTPError as exc:
            try:
                detail = exc.read(500).decode('utf-8', errors='replace')
            except Exception:
                detail = exc.reason
            reset = exc.headers.get('X-RateLimit-Reset', '')
            request_id = exc.headers.get('X-GitHub-Request-Id', '')
            raise RuntimeError(f'GitHub API HTTP {exc.code} at {url}: {detail}; '
                               f'rate_limit_reset={reset}; request_id={request_id}') from exc

    rows = []
    for repo in sorted(candidates)[:args.limit]:
        record = {'repo_id': repo, 'eligibility': 'REVIEW_REQUIRED', 'reasons': [], 'workflows': []}
        try:
            meta = api(repo)
            record.update(language=meta.get('language'), license=(meta.get('license') or {}).get('spdx_id'),
                          family_id=(meta.get('source') or meta).get('full_name'),
                          archived=meta['archived'], fork=meta['fork'])
            if meta['archived'] or meta.get('disabled'):
                record['reasons'].append('ARCHIVED_OR_DISABLED')
            sha = api(repo + '/commits/' + meta['default_branch'])['sha']
            record['source_commit_sha'] = sha
            tree = api(repo + '/git/trees/' + sha + '?recursive=1')
            if tree.get('truncated'):
                record['reasons'].append('TRUNCATED_TREE_REVIEW_REQUIRED')
            paths = [entry['path'] for entry in tree['tree'] if entry['type'] == 'blob']
            record['file_tree_sha256'] = digest(json.dumps(tree['tree'], sort_keys=True).encode())
            record['manifest_paths'] = [p for p in paths if p.rsplit('/', 1)[-1] in
                ('package.json', 'package-lock.json', 'pyproject.toml', 'requirements.txt', 'pom.xml', 'build.gradle', 'go.mod', 'Cargo.toml', 'Makefile')]
            for path in paths:
                if not re.fullmatch(r'\.github/workflows/[^/]+\.ya?ml', path):
                    continue
                content = api(repo + '/contents/' + path + '?ref=' + sha)
                text = base64.b64decode(content['content']).decode('utf-8')
                # BaseLoader preserves Actions `on` and expressions as strings.
                doc = yaml.load(text, Loader=yaml.BaseLoader)
                if not isinstance(doc, dict) or not isinstance(doc.get('jobs'), dict):
                    record['workflows'].append({'path': path, 'review': ['INVALID_JOB_STRUCTURE']})
                    continue
                hazards = []
                if re.search(r'secrets\s*(?:\.|\[)|secrets:\s*inherit', text):
                    hazards.append('SECRET_REFERENCE')
                if re.search(r'self-hosted', text, re.I):
                    hazards.append('SELF_HOSTED_RUNNER')
                if re.search(r'\b(deploy|publish|release|signing)\b', text, re.I):
                    hazards.append('POSSIBLE_EXTERNAL_SIDE_EFFECT')
                runs = api(repo + '/actions/runs?per_page=100')
                comparable = [r for r in runs.get('workflow_runs', []) if r.get('path', '').split('@')[0] == path]
                record['workflows'].append({'path': path, 'sha256': digest(text.encode()),
                    'jobs': list(doc['jobs']), 'triggers': doc.get('on'), 'review': hazards,
                    'has_build_test_lint_hint': bool(re.search(r'\b(test|pytest|lint|build|check)\b', text, re.I)),
                    'recent_runs': [{'id': r['id'], 'head_sha': r['head_sha'], 'conclusion': r['conclusion'],
                                     'event': r['event']} for r in comparable],
                    'history_scope': 'first 100 repository runs; incomplete historical evidence'})
            if not record['workflows'] and not tree.get('truncated'):
                record['reasons'].append('NO_ACTIONS_WORKFLOW')
            if any(r in record['reasons'] for r in ('ARCHIVED_OR_DISABLED', 'NO_ACTIONS_WORKFLOW')):
                record['eligibility'] = 'EXCLUDED'
            if not record['license'] or record['license'] == 'NOASSERTION':
                record['reasons'].append('LICENSE_REVIEW_REQUIRED')
            record['reasons'] += ['BASELINE_NOT_EXECUTED', 'REQUIRED_CHECK_CONTRACT_NOT_APPROVED',
                                  'FORK_REPRODUCIBILITY_UNVERIFIED', 'BUDGET_NOT_VERIFIED']
        except Exception as exc:
            record['eligibility'] = 'COLLECTION_ERROR'
            record['reasons'].append(f'{type(exc).__name__}: {exc}')
        rows.append(record)
        with (out / 'repo_context.jsonl').open('a', encoding='utf-8') as handle:
            handle.write(json.dumps(record) + '\n')
        print(repo, record['eligibility'], flush=True)
    with (out / 'repositories.csv').open('w', newline='', encoding='utf-8') as handle:
        writer = csv.writer(handle)
        writer.writerow(['repo_id', 'eligibility', 'reasons'])
        writer.writerows((r['repo_id'], r['eligibility'], ';'.join(r['reasons'])) for r in rows)
    print('Results:', out)
    return 1 if any(r['eligibility'] == 'COLLECTION_ERROR' for r in rows) else 0


if __name__ == '__main__':
    sys.exit(main())
