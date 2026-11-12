#!/usr/bin/env python3
"""Validate documentation/contract bundle, not the application or providers."""
from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from pathlib import Path
from urllib.parse import unquote

ROOT = Path(__file__).resolve().parents[1]
errors: list[str] = []


def require(condition, message):
    if not condition:
        errors.append(message)


def resolve_pointer(document, pointer):
    current = document
    for part in pointer.removeprefix('#/').split('/'):
        current = current[part.replace('~1', '/').replace('~0', '~')]
    return current


def walk(value):
    yield value
    if isinstance(value, dict):
        for child in value.values():
            yield from walk(child)
    elif isinstance(value, list):
        for child in value:
            yield from walk(child)


documents = {}
for path in sorted(ROOT.rglob('*.json')):
    try:
        documents[path.relative_to(ROOT).as_posix()] = json.loads(path.read_text())
    except (ValueError, UnicodeError) as exc:
        errors.append(f'{path}: invalid JSON: {exc}')

for name, value in documents.items():
    for node in walk(value):
        if isinstance(node, dict) and '$ref' in node:
            ref = node['$ref']
            if ref.startswith('#/'):
                try:
                    resolve_pointer(value, ref)
                except (KeyError, TypeError):
                    errors.append(f'{name}: unresolved reference {ref}')
            else:
                errors.append(f'{name}: unexpected nonlocal schema ref {ref}')

links = 0
for path in sorted(ROOT.rglob('*.md')):
    for target in re.findall(r'\[[^\]]*\]\(([^)]+)\)', path.read_text()):
        if '://' in target or target.startswith(('#', 'mailto:')):
            continue
        target_path = (path.parent / unquote(target.split('#')[0])).resolve()
        require(target_path.is_relative_to(ROOT), f'{path}: link escapes bundle: {target}')
        require(target_path.exists(), f'{path}: missing link target {target}')
        links += 1

checklist = documents['contracts/checklist.borrower.v1.json']
checks = {c['id']: c for m in checklist['materials'] for c in m['checks']}
require(len(checks) == 18, 'Fixture baseline must contain 18 unique leaf checks')
require(sum(len(m['checks']) for m in checklist['materials']) == len(checks), 'Duplicate checklist ids')
require(checklist['customer_role'] == 'borrower' and checklist['enabled'], 'Borrower must be enabled')
for cid, check in checks.items():
    require(all(dep in checks for dep in check['dependencies']), f'{cid}: missing dependency')


def visit(cid, stack):
    require(cid not in stack, 'Checklist dependency cycle: ' + cid)
    if cid in stack:
        return
    for dep in checks[cid]['dependencies']:
        if dep in checks:
            visit(dep, stack | {cid})


for cid in checks:
    visit(cid, set())
roles = documents['contracts/feature_flags.json']['roles']
require({r['code'] for r in roles if r['enabled']} == {'borrower'}, 'Only borrower may be enabled')
require(all(r['checklist_version'] is None for r in roles if not r['enabled']), 'Disabled role must not borrow checklist version')

oas = documents['contracts/openapi.json']
require(oas['openapi'] == '3.1.0', 'Unexpected OpenAPI version')
operation_ids = []
operation_count = 0
for path, operations in oas['paths'].items():
    placeholders = set(re.findall(r'\{([^}]+)\}', path))
    for method, operation in operations.items():
        operation_count += 1
        operation_ids.append(operation['operationId'])
        named = {p['name'] for p in operation['parameters'] if p['in'] == 'path'}
        require(placeholders == named, f'{method} {path}: missing path parameter')
        require(any(str(x).startswith('2') for x in operation['responses']), f'{method} {path}: no success response')
        if method in {'post','put','patch','delete'} and path != '/auth/login':
            require(any(p['name'] == 'X-CSRF-Token' for p in operation['parameters']), f'{path}: missing CSRF contract')
require(len(operation_ids) == len(set(operation_ids)), 'Duplicate OpenAPI operationId')

review = documents['fixtures/review_results.example.json']
results = review['items']
require(len(results) == 19, 'Synthetic fixture should have 19 results')
require(Counter(r['material_type'] for r in results) == {'business_license':3,'articles_of_association':7,'audited_financials':9}, 'Synthetic material counts differ')
require(len({r['id'] for r in results}) == len(results), 'Duplicate result ids')
require(set(r['check_item_id'] for r in results) == set(checks), 'Fixture does not cover every check')
for result in results:
    require(result['decision']['result_id'] == result['id'], 'Decision refers to wrong result')
    require(result['task_id'] == results[0]['task_id'] and result['run_id'] == review['run_id'], 'Fixture cross-task/run leakage')
    if result['kind'] == 'not_found':
        require(not result['sources'] and result['not_found_reason'], 'Not-found must not invent sources')

stats_cases = documents['fixtures/statistics_cases.json']
for case in stats_cases:
    s = case['expected']
    n,u,a,r,m = [s[k] for k in ['total','unselected','accepted','rejected','missing_reason']]
    require(n == u+a+r and 0 <= m <= r, f"{case['name']}: count invariant")
    require(s['can_complete'] == (n>0 and u==0 and m==0), f"{case['name']}: completion invariant")
    require(s['accept_rate'] == (a/n if n else None), f"{case['name']}: accept denominator")
    require(s['reject_rate'] == (r/n if n else None), f"{case['name']}: reject denominator")

license_pages = documents['fixtures/ocr_license_seal.sanitized.json']
page = license_pages[0] if isinstance(license_pages, list) else license_pages
blocks = page['prunedResult']['parsing_res_list']
require(len(blocks) == 20 and len(page['prunedResult']['layout_det_res']['boxes']) == 23, 'License fixture structure changed')
seal = next(b for b in blocks if b.get('block_label') == 'seal' and b.get('block_id') == 15)
require(seal['block_bbox'] == [608,398,721,519], 'Seal bbox differs from uploaded sample')
require('北京市朝阳区市场监督管理局' in seal['block_content'], 'Seal text missing')
require('imgs/img_in_seal_box_608_398_721_519.jpg' in page['markdown']['images'], 'Seal image key missing')

for name, value in documents.items():
    if name.endswith('.sanitized.json'):
        for node in walk(value):
            if isinstance(node, str):
                require(not re.search(r'https?://(?!ocr-assets\.example\.invalid/)[^\s<>"\']+', node), f'{name}: original remote URL remains')

for output_name,input_name,id_field,collection in [
    ('text_search','text_search','block_id','blocks'),
    ('vision_match','vision_match','crop_id','candidates'),
]:
    output = documents[f'fixtures/{output_name}.example.json']
    input_value = documents[f'fixtures/{input_name}.input.example.json']
    require(output['bundle_id'] == input_value['bundle_id'], f'{output_name}: wrong bundle')
    allowed = {row[id_field] for row in input_value[collection]}
    if output_name == 'text_search':
        selected = [src['block_id'] for c in output['check_results'] for e in c['evidence'] for src in e['source_refs']]
        require({c['check_item_id'] for c in output['check_results']} == {c['id'] for c in input_value['checks']}, 'Text search missing/extra checks')
        for check in output['check_results']:
            require(bool(check['evidence']) == (check['outcome']=='found'), 'Search outcome/evidence mismatch')
    else:
        selected = [match['crop_id'] for match in output['matches']]
    require(set(selected) <= allowed, f'{output_name}: invented reference')

normalized = documents['fixtures/normalized_page.example.json']
require(normalized['width_px'] is None and normalized['coordinate_space'] == 'unknown', 'Unknown dimensions must not imply verified geometry')
require(normalized['blocks'][0]['provider_block_id'] == 15, 'Normalized seal provenance missing')
require(normalized['crops'][0]['block_id'] == normalized['blocks'][0]['block_id'], 'Crop/block mismatch')

main = (ROOT/'docs/01_requirements.md').read_text()
require('版本：V0.5' in main, 'Requirement version mismatch')
require(all('AC'+str(i).zfill(2) in main for i in range(1,46)), 'Baseline acceptance case missing')
require('最多5人' in main and '置灰' in main, 'Latest user answers missing')
require(not (ROOT/'.env').exists(), 'Real .env must not be packaged')

manifest_path = ROOT/'MANIFEST.sha256'
if manifest_path.exists():
    for line in manifest_path.read_text().splitlines():
        digest,relative = line.split('  ',1)
        file = ROOT/relative
        require(file.is_file() and hashlib.sha256(file.read_bytes()).hexdigest()==digest, f'Manifest mismatch: {relative}')

report = dict(json_documents=len(documents),markdown_links=links,checklist_leaves=len(checks),synthetic_results=len(results),openapi_paths=len(oas['paths']),openapi_operations=operation_count,openapi_schemas=len(oas['components']['schemas']),errors=errors,application_tested=False,external_services_tested=False)
print(json.dumps(report,ensure_ascii=False,indent=2))
raise SystemExit(1 if errors else 0)
