#!/usr/bin/env python3
"""Evidence-extraction reference adapter; never represents semantic fact validation."""
import argparse
from collections import Counter, defaultdict
from difflib import SequenceMatcher
import hashlib
import json
from pathlib import Path
import random
import re
import shutil
import sys
import unicodedata
from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[1]
SPLITS = ('train', 'validation', 'test', 'evaluation')


def digest(data):
    return hashlib.sha256(data).hexdigest()


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def write(path, obj):
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def lines(path, required=True):
    if not path.exists() and not required:
        return []
    rows = []
    for i, line in enumerate(path.read_text(encoding='utf-8').splitlines(), 1):
        if not line.strip():
            continue
        try:
            rows.append(json.loads(line))
        except ValueError as exc:
            raise ValueError(f'{path.name}:{i}: invalid JSON: {exc}') from exc
    return rows


def jsonl(path, rows):
    path.write_text(''.join(json.dumps(x, ensure_ascii=False) + '\n' for x in rows), encoding='utf-8')


def norm(text):
    return re.sub(r'\s+', '', unicodedata.normalize('NFKC', text).casefold())


def config(inp):
    t, r = read(inp / 'template.json'), read(inp / 'rules.json')
    ratios = t['split_ratios']
    if set(ratios) != set(SPLITS) or any(type(v) not in (int, float) or v <= 0 for v in ratios.values()) or abs(sum(ratios.values()) - 1) > 1e-8:
        raise ValueError('split_ratios must contain four positive probabilities summing to 1')
    target = t['target_labels']
    if not target or any(type(v) not in (int, float) or v <= 0 for v in target.values()) or abs(sum(target.values()) - 1) > 1e-8:
        raise ValueError('target_labels must be positive probabilities summing to 1')
    for key in ('distribution_tolerance', 'max_synthetic_ratio'):
        if not 0 <= t[key] <= 1:
            raise ValueError(f'{key} must be in [0,1]')
    for key in ('review_per_stratum', 'near_duplicate_limit'):
        if type(t[key]) is not int or t[key] < 1:
            raise ValueError(f'{key} must be a positive integer')
    if '{text}' not in t['prompt']:
        raise ValueError('extraction prompt must contain {text}')
    return t, r


def assigned(group, t):
    value = int(digest(f"{t['seed']}:{group}".encode()), 16) / 2**256
    cumulative = 0
    for split in SPLITS:
        cumulative += t['split_ratios'][split]
        if value < cumulative:
            return split
    return SPLITS[-1]


def fingerprint(inp, out):
    paths = [inp / x for x in ('sources.jsonl', 'template.json', 'rules.json', 'golden.jsonl', 'model_outputs.jsonl')]
    paths += [out / 'dataset.jsonl', ROOT / 'assets/sample.schema.json', Path(__file__)]
    return digest(json.dumps({p.name: digest(p.read_bytes()) if p.exists() else None for p in paths}, sort_keys=True).encode())


def build(inp, out):
    t, _ = config(inp)
    if (out / 'dataset.jsonl').exists():
        raise ValueError('output dataset exists; use a new output directory')
    rows = []
    for s in lines(inp / 'sources.jsonl'):
        rows.append(dict(id='seed-' + s['source_id'], task_id=t['task_id'], source_id=s['source_id'], group_id=s['group_id'], split=assigned(s['group_id'], t), prompt=t['prompt'].replace('{text}', s['text']), answer=s['evidence'], evidence=s['evidence'], label=s['label'], kind='seed', parent_id=None, generator=None))
    rows += lines(inp / 'golden.jsonl', False) + lines(inp / 'model_outputs.jsonl', False)
    out.mkdir(parents=True, exist_ok=True)
    jsonl(out / 'dataset.jsonl', rows)
    return check(inp, out)


def check(inp, out):
    t, rules = config(inp)
    issues = []
    def issue(code, ids, detail, severity='error'):
        issues.append(dict(code=code, sample_ids=ids, detail=detail, severity=severity))
    validator = Draft202012Validator(read(ROOT / 'assets/sample.schema.json'))
    valid = []
    for i, line in enumerate((out / 'dataset.jsonl').read_text(encoding='utf-8').splitlines(), 1):
        if not line.strip():
            issue('EMPTY_LINE', [], f'line {i}')
            continue
        try:
            row = json.loads(line)
        except ValueError:
            issue('INVALID_JSON', [], f'line {i}')
            continue
        errors = sorted(validator.iter_errors(row), key=lambda e: str(e.path))
        if errors:
            issue('SCHEMA', [row.get('id', f'line:{i}')] if isinstance(row, dict) else [], '; '.join(e.message for e in errors))
            continue
        valid.append(row)
    source_rows = lines(inp / 'sources.jsonl')
    sources = {}
    for s in source_rows:
        if not isinstance(s, dict) or not all(isinstance(s.get(k), str) and s[k] for k in ('source_id', 'group_id', 'text', 'evidence', 'label', 'provenance')):
            raise ValueError('source records require nonempty source_id/group_id/text/evidence/label/provenance')
        if s['source_id'] in sources:
            issue('DUPLICATE_SOURCE_ID', [], s['source_id'])
        sources[s['source_id']] = s
    by_id = {}
    for x in valid:
        if x['id'] in by_id:
            issue('DUPLICATE_ID', [x['id']], 'sample id is not unique')
        by_id[x['id']] = x
    buckets = {k: defaultdict(list) for k in ('source_id', 'group_id', 'prompt_hash', 'pair_hash')}
    for x in valid:
        ids = [x['id']]
        s = sources.get(x['source_id'])
        if not s:
            issue('SOURCE_MISSING', ids, x['source_id'])
        else:
            if s.get('licensed') is not True or s.get('deidentified') is not True:
                issue('GOVERNANCE', ids, 'source lacks licensed/deidentified=true declaration')
            if x['group_id'] != s['group_id'] or x['split'] != assigned(s['group_id'], t):
                issue('SPLIT_ASSIGNMENT', ids, 'source group or deterministic split mismatch')
            if x['evidence'] not in s['text'] or x['answer'] != x['evidence']:
                issue('EVIDENCE', ids, 'extraction answer not identical to cited source span')
            if s['text'] not in x['prompt']:
                issue('PROMPT_CONTEXT', ids, 'extraction prompt does not contain source text')
            if x['label'] != s['label']:
                issue('SOURCE_LABEL', ids, 'label differs from governed source label')
        if x['task_id'] != t['task_id'] or x['label'] not in t['target_labels']:
            issue('TASK_LABEL', ids, 'unknown task or label')
        if any(norm(term) in norm(x['prompt'] + x['answer']) for term in rules['forbidden_terms']):
            issue('BUSINESS_RULE', ids, 'forbidden term matched')
        if x['kind'] in ('augmented', 'hard'):
            parent = by_id.get(x['parent_id'])
            if not parent:
                issue('PARENT_MISSING', ids, 'synthetic sample needs existing parent')
            elif parent['split'] != 'train' or x['split'] != 'train' or parent['group_id'] != x['group_id'] or parent['source_id'] != x['source_id']:
                issue('LINEAGE_LEAKAGE', ids + [parent['id']], 'synthetic sample must inherit training parent source and group')
            seen = {x['id']}
            current = parent
            while current:
                if current['id'] in seen:
                    issue('LINEAGE_CYCLE', ids, 'cyclic lineage')
                    break
                seen.add(current['id'])
                current = by_id.get(current['parent_id'])
        for key in ('source_id', 'group_id'):
            buckets[key][x[key]].append(x)
        buckets['prompt_hash'][digest(norm(x['prompt']).encode())].append(x)
        buckets['pair_hash'][digest((norm(x['prompt']) + '\0' + norm(x['answer'])).encode())].append(x)
    for key, groups in buckets.items():
        for group in groups.values():
            if len(group) > 1:
                ids = [x['id'] for x in group]
                if len({x['split'] for x in group}) > 1:
                    issue('CROSS_SPLIT_LEAKAGE', ids, f'shared {key}')
                if key == 'pair_hash':
                    issue('EXACT_DUPLICATE', ids, 'normalized prompt and answer are identical')
                if key == 'prompt_hash' and len({x['answer'] for x in group}) > 1:
                    issue('ANSWER_CONFLICT', ids, 'same prompt has different answers')
    near_complete = len(valid) <= t['near_duplicate_limit']
    if not near_complete:
        issue('NEAR_CHECK_INCOMPLETE', [], 'too many rows; external indexed similarity scan required', 'warning')
    else:
        for i, a in enumerate(valid):
            for b in valid[i + 1:]:
                if a['group_id'] != b['group_id'] and SequenceMatcher(None, norm(a['prompt']), norm(b['prompt'])).ratio() >= t.get('near_duplicate_threshold', 0.92):
                    issue('NEAR_DUPLICATE', [a['id'], b['id']], 'character similarity candidate; expert review required', 'warning')
    distributions = {}
    for split in SPLITS:
        subset = [x for x in valid if x['split'] == split]
        jsonl(out / (split + '.jsonl'), subset)
        counts = Counter(x['label'] for x in subset)
        distributions[split] = dict(count=len(subset), labels=dict(counts))
        if not subset:
            issue('EMPTY_SPLIT', [], split)
            continue
        distance = sum(abs(counts[k] / len(subset) - t['target_labels'].get(k, 0)) for k in set(counts) | set(t['target_labels'])) / 2
        distributions[split]['label_total_variation'] = distance
        if distance > t['distribution_tolerance'] or set(t['target_labels']) - set(counts):
            issue('DISTRIBUTION', [], f'{split}: label distance={distance:.4f} or missing labels')
    synthetic = sum(x['kind'] in ('augmented', 'hard') for x in valid) / max(1, len(valid))
    if synthetic > t['max_synthetic_ratio']:
        issue('SYNTHETIC_RATIO', [], str(synthetic))
    report = dict(status='blocked' if issues else 'machine_pass', fingerprint=fingerprint(inp, out), valid_count=len(valid), synthetic_ratio=synthetic, distributions=distributions, errors=sum(x['severity'] == 'error' for x in issues), warnings=sum(x['severity'] == 'warning' for x in issues), near_scan_complete=near_complete, not_checked=['semantic factual entailment', 'semantic/multilingual duplicates', 'external benchmark/training history contamination', 'real identity/PII detection', 'time/entity relations absent from group_id'], scope='evidence-extraction reference adapter; machine pass is not expert approval')
    jsonl(out / 'issues.jsonl', issues)
    write(out / 'report.json', report)
    return report


def tasks_for(inp, out):
    t, _ = config(inp)
    strata = defaultdict(list)
    for x in lines(out / 'dataset.jsonl'):
        strata[(x['split'], x['label'], x['kind'])].append(x)
    rng = random.Random(t['seed'])
    selected = {}
    for key in sorted(strata):
        group = sorted(strata[key], key=lambda x: x['id'])
        for x in rng.sample(group, min(len(group), t['review_per_stratum'])):
            selected[x['id']] = x
        for x in group:
            if x['kind'] != 'seed':
                selected[x['id']] = x
    return [dict(sample_id=x['id'], prompt=x['prompt'], source_id=x['source_id'], instructions='独立作答后核对候选答案与标签，填写 reviews.json；记录证据与规则依据。') for x in sorted(selected.values(), key=lambda x: x['id'])]


def review(inp, out):
    report = check(inp, out)
    if report['status'] != 'machine_pass':
        raise ValueError('resolve machine issues before issuing review tasks')
    if (out / 'review_batch.json').exists():
        raise ValueError('review batch exists; use a new output directory for changed data')
    tasks = tasks_for(inp, out)
    jsonl(out / 'annotation_tasks.jsonl', tasks)
    write(out / 'review_batch.json', dict(fingerprint=report['fingerprint'], task_hash=digest((out / 'annotation_tasks.jsonl').read_bytes())))
    write(out / 'reviews.json', {x['sample_id']: dict(decision='pending', reviewer='', notes='') for x in tasks})
    return dict(status='awaiting_experts', tasks=len(tasks))


def seal(inp, out, version):
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]{0,63}', version):
        raise ValueError('invalid version name')
    report = check(inp, out)
    if report['status'] != 'machine_pass':
        raise ValueError('machine issues block release')
    batch = read(out / 'review_batch.json')
    tasks = lines(out / 'annotation_tasks.jsonl')
    if batch['fingerprint'] != report['fingerprint'] or batch['task_hash'] != digest((out / 'annotation_tasks.jsonl').read_bytes()) or tasks != tasks_for(inp, out):
        raise ValueError('stale or changed review batch')
    reviews = read(out / 'reviews.json')
    for task in tasks:
        result = reviews.get(task['sample_id'], {})
        if result.get('decision') != 'approve' or not str(result.get('reviewer', '')).strip() or not str(result.get('notes', '')).strip():
            raise ValueError(f"expert approval missing: {task['sample_id']}")
    dest = out / 'releases' / version
    dest.mkdir(parents=True, exist_ok=False)
    for name in ['dataset.jsonl', 'issues.jsonl', 'report.json', 'annotation_tasks.jsonl', 'review_batch.json', 'reviews.json'] + [s + '.jsonl' for s in SPLITS]:
        shutil.copy2(out / name, dest / name)
    (dest / 'inputs').mkdir()
    for name in ('sources.jsonl', 'template.json', 'rules.json', 'golden.jsonl', 'model_outputs.jsonl'):
        if (inp / name).exists():
            shutil.copy2(inp / name, dest / 'inputs' / name)
    shutil.copy2(ROOT / 'assets/sample.schema.json', dest / 'sample.schema.json')
    shutil.copy2(Path(__file__), dest / 'dataset_qa.py')
    write(dest / 'manifest.json', dict(version=version, fingerprint=report['fingerprint'], expert_reviewed=len(tasks), checks_scope=report['scope'], not_checked=report['not_checked'], files={str(p.relative_to(dest)): digest(p.read_bytes()) for p in sorted(dest.rglob('*')) if p.is_file()}))
    return dict(status='sealed', path=str(dest))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['build', 'check', 'review', 'seal'])
    parser.add_argument('--input', required=True, type=Path)
    parser.add_argument('--out', required=True, type=Path)
    parser.add_argument('--version')
    args = parser.parse_args()
    try:
        if args.command == 'seal':
            if not args.version:
                raise ValueError('--version required')
            result = seal(args.input, args.out, args.version)
        else:
            result = globals()[args.command](args.input, args.out)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 1 if result.get('status') == 'blocked' else 0
    except (ValueError, KeyError, TypeError, OSError) as exc:
        print(f'ERROR: {exc}', file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main())
