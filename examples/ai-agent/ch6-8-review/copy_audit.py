"""Byte audit only: no tokenizer/model loading or implicit normalization."""
import hashlib
import json
import unicodedata


def audit(prediction: str, target: str):
    pred_bytes, target_bytes = prediction.encode('utf-8'), target.encode('utf-8')
    first = next((i for i, (a, b) in enumerate(zip(pred_bytes, target_bytes)) if a != b),
                 min(len(pred_bytes), len(target_bytes)) if pred_bytes != target_bytes else None)
    return {
        'prediction': prediction, 'target': target,
        'prediction_bytes': len(pred_bytes), 'target_bytes': len(target_bytes),
        'prediction_sha256': hashlib.sha256(pred_bytes).hexdigest(),
        'target_sha256': hashlib.sha256(target_bytes).hexdigest(),
        'raw_exact': pred_bytes == target_bytes,
        'normalized_exact': prediction.strip().encode('utf-8') == target_bytes,
        # A diagnostic only. It does not alter the acceptance criterion.
        'nfc_diagnostic_equal': unicodedata.normalize('NFC', prediction) ==
                                unicodedata.normalize('NFC', target),
        'raw_first_diff_byte': first,
    }


def demo():
    source = '中文\né'
    wire = json.dumps({'value': source}, ensure_ascii=True)
    decoded = json.loads(wire)['value']
    return {
        'data_kind': 'synthetic teaching data',
        'audits': [audit(' abc\n', 'abc'), audit('abc', ' abc '),
                   audit('\u00e9', 'e\u0301'), audit(decoded, source),
                   audit('a\r\nb', 'a\nb')],
        'json_wire': wire,
        'wire_differs_from_unescaped_json': wire.encode('utf-8') !=
            json.dumps({'value': source}, ensure_ascii=False).encode('utf-8'),
    }


if __name__ == '__main__':
    print(json.dumps(demo(), ensure_ascii=False, indent=2))
