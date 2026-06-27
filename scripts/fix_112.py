import json, hashlib

d = json.load(open('tests/fixtures/task_093_confirmations/112.json', encoding='utf-8'))

for i, m in enumerate(d['confirmed_mappings']):
    src = m.get('source_account_code')
    if src in ('2171.001.001.001', '2171.001.001.004', '2171.001.004.004'):
        old_tgt = m['standard_account_code']
        m['standard_account_code'] = '2221'
        m['standard_account_name'] = '应交税费'
        if src == '2171.001.001.001':
            m['source_account_name_masked'] = '进项税额-原材料'
            m['review_reason'] = "源科目 2171.001.001.001 属于应交税费-进项税额下挂的原材料采购明细,统一映射至 2221 '应交税费',反映增值税进项税余额。注:旧 fixture 错误映射至 1403 原材料,TASK-094A 修正为正确目标。"
        elif src == '2171.001.001.004':
            m['source_account_name_masked'] = '进项税额-固定资产'
            m['review_reason'] = "源科目 2171.001.001.004 属于应交税费-进项税额下挂的固定资产采购明细,统一映射至 2221 '应交税费',反映固定资产入账相关进项税余额。注:旧 fixture 错误映射至 160101 固定资产-原值,TASK-094A 修正为正确目标。"
        elif src == '2171.001.004.004':
            m['source_account_name_masked'] = '销售固定资产-进项税'
            m['review_reason'] = "源科目 2171.001.004.004 属于应交税费-进项税额下挂的销售固定资产明细,统一映射至 2221 '应交税费'。注:旧 fixture 错误映射至 160101 固定资产-原值,TASK-094A 修正为正确目标。"
        new_key = 'sha256:' + hashlib.sha256(f'112|{src}|{m["source_account_name_masked"]}'.encode()).hexdigest()[:32]
        m['row_key'] = new_key
        print(f'fixed #{i} {src}: {old_tgt} -> 2221')

# 1701.002 固定资产清理-收入 错误映射到 160101,修正到 1606 固定资产清理
for i, m in enumerate(d['confirmed_mappings']):
    src = m.get('source_account_code')
    if src == '1701.002':
        old_tgt = m['standard_account_code']
        m['standard_account_code'] = '1606'
        m['standard_account_name'] = '固定资产清理'
        m['source_account_name_masked'] = '固定资产清理-清理收入'
        m['review_reason'] = "源科目 1701.002 属于固定资产清理(客户原账下的'固定资产清理-收入'子目),统一映射至 1606 '固定资产清理',反映企业因出售/报废/毁损转入清理的固定资产账面价值,余额方向借方。注:旧 fixture 错误映射至 160101 固定资产-原值,TASK-094A 修正为正确目标。"
        new_key = 'sha256:' + hashlib.sha256(f'112|{src}|{m["source_account_name_masked"]}'.encode()).hexdigest()[:32]
        m['row_key'] = new_key
        print(f'fixed #{i} {src}: {old_tgt} -> 1606')

json.dump(d, open('tests/fixtures/task_093_confirmations/112.json', 'w', encoding='utf-8'), ensure_ascii=False, indent=2)
print('saved')