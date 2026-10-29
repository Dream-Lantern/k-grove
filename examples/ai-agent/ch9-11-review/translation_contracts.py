"""One-term, two-chapter deterministic lesson; not an LLM translation system."""
import hashlib
import json
import re


def fingerprint(text):
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def term_metrics(chapters):
    """Chapter-level lexical metrics for token→词元 vs 标记, not semantic quality."""
    covered = hits = mixed = strict = 0
    for text in chapters.values():
        # Intentionally narrow teaching parser, not a full Markdown grammar.
        text = re.sub(r'```.*?```', ' ', text, flags=re.S)
        text = re.sub(r'`[^`]*`', ' ', text)
        mandated, default = '词元' in text, '标记' in text
        if mandated or default:
            covered += 1
            hits += mandated
            mixed += mandated and default
            strict += mandated and not default
    return {'chapters': len(chapters), 'covered': covered,
            'coverage': covered/len(chapters) if chapters else None,
            'hit_rate': hits/covered if covered else None,
            'mixed_rate': mixed/covered if covered else None,
            'strict_rate': strict/covered if covered else None}


def submit_revision(index, name, expected_hash, text, remaining):
    if remaining <= 0:
        raise ValueError('revision budget exhausted: needs human review')
    current = index[name]
    if current['sha256'] != expected_hash:
        raise ValueError('stale revision: do not overwrite a newer artifact')
    return {**index, name: {'version': current['version'] + 1,
                            'sha256': fingerprint(text), 'text': text}}


def demo():
    chapters = {'ch1': '词元决定序列长度。', 'ch2': '先统计词元，再合并标记。'}
    index = {k: {'version': 1, 'sha256': fingerprint(v), 'text': v} for k, v in chapters.items()}
    report = {'status': 'NEEDS_REVISION', 'glossary_version': 'g-v1',
              'input_hashes': {k: v['sha256'] for k, v in index.items()},
              'issues': [{'chapter': 'ch2', 'expected': '词元', 'observed': '标记'}],
              'revision_budget': 1}
    revised = submit_revision(index, 'ch2', report['input_hashes']['ch2'],
                              '先统计词元，再合并词元。', 1)
    return {'data_kind': 'fixed synthetic chapters; no model calls',
            'before': term_metrics(chapters), 'proofreading': report,
            'after': term_metrics({k: v['text'] for k, v in revised.items()}),
            'file_index': {k: {f: v[f] for f in ('version', 'sha256')} for k, v in revised.items()},
            'status': 'READY_FOR_HUMAN', 'semantic_quality': 'NOT_EVALUATED'}


if __name__ == '__main__':
    print(json.dumps(demo(), ensure_ascii=False, indent=2))
