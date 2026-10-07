"""Read saved briefing references and recompute retained course inputs.

This diagnostic never creates grants, enables schedules, calls a model, queries
historical batches or writes school tables. Authentication is passed in memory
through environment variables, never copied to the output file.
"""
import argparse
import json
import os
from pathlib import Path
import sys
import urllib.request

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--publication', required=True)
    parser.add_argument('--base-url', default='http://127.0.0.1:8011/api/admin/expert-resources')
    parser.add_argument('--output')
    args = parser.parse_args()
    token = os.environ.get('EXPERT_VERIFY_TOKEN', '')
    identity = os.environ.get('EXPERT_VERIFY_IDENTITY', '')
    if not token or not identity:
        raise SystemExit('Provide the existing test identity through EXPERT_VERIFY_TOKEN/EXPERT_VERIFY_IDENTITY; secrets are not written.')
    headers = {'Authorization': token if token.startswith('Bearer ') else 'Bearer ' + token, 'X-Active-Identity': identity}
    def get(path):
        request = urllib.request.Request(args.base_url.rstrip('/') + path, headers=headers)
        with urllib.request.urlopen(request, timeout=25) as response:
            return json.load(response)
    path = '/briefing/publications/' + args.publication
    envelope = get(path)
    if envelope.get('code') not in {0, 200} or not envelope.get('data'):
        raise SystemExit('Publication was not authorized or could not be read.')
    publication = envelope['data']
    result = (publication.get('outcome') or {}).get('result') or {}
    basis = result.get('validationBasis') or {}
    records, total = [], None
    evidence_id = (basis.get('frozenInput') or {}).get('evidenceId')
    if evidence_id:
        while total is None or len(records) < total:
            page = get(path + '/evidence/' + evidence_id + '?offset=' + str(len(records)) + '&limit=100')['data']
            total = page['totalRows']
            if not page['rows'] and len(records) < total:
                raise SystemExit('Retained evidence is incomplete; no successful recomputation claimed.')
            records.extend(page['rows'])
    recomputed = None
    if records:
        from backend.expert_resources.course_observation import calculate, independent_recompute
        recomputed = calculate(records, publication['semesterId'])
        independent = independent_recompute(records, publication['semesterId'], recomputed)
    else:
        independent = {'state': 'not_available'}
    report = {'publicationId': publication['publicationId'], 'resultId': publication['resultId'],
              'status': publication['status'], 'revision': publication['revision'],
              'publicationSequence': publication['publicationSequence'],
              'publishMode': result.get('publishMode'), 'applicable': publication['applicable'],
              'firstAttemptSemantics': basis.get('firstAttemptSemantics', {}).get('state'),
              'savedIndependentRecompute': basis.get('independentRecompute'), 'diagnosticRecompute': independent,
              'threeLayerCheck': basis.get('threeLayerCheck'), 'metricRefs': basis.get('metricRefs'),
              'mappingRef': basis.get('mappingRef'), 'scope': publication['scope'],
              'explanationState': publication['explanationState'], 'workerFinished': publication['workerFinished'],
              'checks': {'resultReference': result.get('resultId') == publication['resultId'],
                         'registeredObservation': result.get('publishMode') != 'observation' or basis.get('metricRegistration') is True,
                         'currentInputRecompute': result.get('publishMode') != 'observation' or independent.get('state') == 'passed',
                         'frozenEvidenceMatches': result.get('publishMode') != 'observation' or (recomputed or {}).get('inputSha256') == basis.get('frozenInput', {}).get('sha256'),
                         'savedObservationSetMatches': result.get('publishMode') != 'observation' or (recomputed or {}).get('observations') == result.get('observations')}}
    report['statusCheck'] = 'passed' if all(report['checks'].values()) else 'failed'
    text = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        Path(args.output).write_text(text, encoding='utf-8')
    else:
        print(text)


if __name__ == '__main__':
    main()
