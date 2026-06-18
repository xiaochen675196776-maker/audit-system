"""审计相关枚举"""

import enum


class AccountDirection(str, enum.Enum):
    """科目余额方向"""
    DEBIT = "debit"    # 借方
    CREDIT = "credit"  # 贷方


class AccountCategory(str, enum.Enum):
    """科目类别"""
    ASSET = "asset"             # 资产
    LIABILITY = "liability"     # 负债
    EQUITY = "equity"           # 权益
    REVENUE = "revenue"         # 收入
    EXPENSE = "expense"         # 费用/成本
    PROFIT_LOSS = "profit_loss" # 损益


class AuxiliaryType(str, enum.Enum):
    """辅助核算类型"""
    CUSTOMER = "customer"         # 客户
    SUPPLIER = "supplier"         # 供应商
    DEPARTMENT = "department"     # 部门
    PROJECT = "project"           # 项目
    PERSON = "person"             # 个人
    INVENTORY = "inventory"       # 存货
    OTHER = "other"               # 其他
