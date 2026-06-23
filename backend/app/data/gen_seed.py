"""生成标准科目种子 Python 模块"""
import os, sys

# 找到桌面上的 Excel 源文件
desktop = os.path.join(os.environ['USERPROFILE'], 'Desktop')
source = None
for f in os.listdir(desktop):
    if '科目' in f and f.endswith('.xlsx'):
        source = os.path.join(desktop, f)
        break

if not source:
    print("ERROR: 找不到 科目余额表.xlsx")
    sys.exit(1)

print(f"Reading: {source}")

import openpyxl
wb = openpyxl.load_workbook(source, read_only=True, data_only=True)
ws = wb.active

accounts = []
for row in ws.iter_rows(min_row=2, values_only=True):  # skip header
    vals = [str(v).strip() if v is not None else '' for v in row]
    if len(vals) < 4:
        vals.extend([''] * (4 - len(vals)))
    code = vals[0] if len(vals) > 0 else ''
    name = vals[1] if len(vals) > 1 else ''
    direction = vals[2] if len(vals) > 2 else ''
    category = vals[3] if len(vals) > 3 else ''
    
    if not code and not name:
        continue
    
    # Normalize direction
    if direction in ('借', '借方'):
        direction = 'debit'
    elif direction in ('贷', '贷方'):
        direction = 'credit'
    elif not direction:
        direction = None
    
    if not category:
        category = None
    
    accounts.append({
        'account_code': code,
        'account_name': name,
        'balance_direction': direction,
        'account_category': category,
    })

wb.close()
print(f"Extracted {len(accounts)} accounts")

# Write to project — use relative path
target = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'standard_accounts_seed.py')

with open(target, 'w', encoding='utf-8') as f:
    f.write('# 系统内置标准科目种子数据 — 从 科目余额表.xlsx 生成\n')
    f.write('# 请勿手动编辑，由系统维护脚本更新\n\n')
    f.write('SEED_ACCOUNTS = ')
    f.write(repr(accounts))
    f.write('\n')

print(f"Written to: {target}")
print(f"First: {accounts[0]}")
print(f"Last: {accounts[-1]}")
