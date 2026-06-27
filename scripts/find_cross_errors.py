import sys, json
sys.path.insert(0, 'tests')
from fixture_governance import validate_fixture_mapping_semantics, MappingPair

for fk in ['chengdu_dikang', '112', '205201', 'huizhan', 'tb_2023', 'yiliao']:
    d = json.load(open(f'tests/fixtures/task_093_confirmations/{fk}.json', encoding='utf-8'))
    for i, m in enumerate(d['confirmed_mappings']):
        pair = MappingPair(
            m.get('source_account_code') or '',
            m.get('source_account_name_masked') or '',
            m.get('standard_account_code') or '',
            m.get('standard_account_name') or '',
            m.get('row_index'),
        )
        errs = validate_fixture_mapping_semantics(pair)
        if errs:
            src = m.get('source_account_code')
            tgt = m.get('standard_account_code')
            name = m.get('source_account_name_masked')
            print(f"{fk}#{i} {src} ({name}) -> {tgt}: {errs}")