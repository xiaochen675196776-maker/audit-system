"""标准科目服务 — Excel 导入解析、层级推断、全量同步、内置种子数据"""

import uuid
import logging
from pathlib import Path

import openpyxl
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.standard_account import StandardAccount

logger = logging.getLogger(__name__)

# 标准模板中标准科目相关列
STANDARD_ACCOUNT_HEADERS = ["科目代码", "科目名称", "余额方向", "科目类别"]

# 科目代码层级推断的分隔符
CODE_SEPARATORS = ["-", ".", "_"]


def _read_excel_headers_and_rows(file_path: str) -> tuple[list[str], list[list]]:
    """读取 Excel 第一行作为表头，后续行作为数据。返回 (headers, rows)。"""
    wb = openpyxl.load_workbook(file_path, read_only=True, data_only=True)
    ws = wb.active

    rows_iter = ws.iter_rows(min_row=1, values_only=True)
    headers_raw = next(rows_iter, None)
    if headers_raw is None:
        wb.close()
        raise ValueError("Excel 文件为空，没有表头行")

    # 清洗表头
    headers = [_clean_header(h) for h in headers_raw]
    # 读取数据行
    data_rows = []
    for row in rows_iter:
        # 跳过完全空行
        if row is None or all(_is_blank(cell) for cell in row):
            continue
        data_rows.append([_cell_str(cell) for cell in row])
    wb.close()
    return headers, data_rows


def _clean_header(value) -> str:
    """清洗表头字符串"""
    if value is None:
        return ""
    s = str(value).strip()
    # 去除 BOM 和零宽字符
    s = s.replace("\ufeff", "").replace("\u200b", "")
    return s


def _is_blank(value) -> bool:
    """判断单元格是否为空"""
    if value is None:
        return True
    return str(value).strip() == ""


def _cell_str(value) -> str:
    """将单元格值转为字符串"""
    if value is None:
        return ""
    s = str(value).strip()
    return s


def _build_column_index(headers: list[str]) -> dict[str, int]:
    """根据表头文本建立列名 → 列序号的映射。"""
    idx = {}
    for i, h in enumerate(headers):
        if h and h not in idx:
            idx[h] = i
    return idx


def parse_standard_accounts_excel(file_path: str) -> tuple[list[dict], list[dict]]:
    """
    解析标准科目 Excel 文件。

    返回:
        (accounts: list[dict], errors: list[dict])
        每个 account dict 包含: row_index, account_code, account_name,
                                 balance_direction, account_category
        每个 error dict 包含: row_index, reason
    """
    headers, rows = _read_excel_headers_and_rows(file_path)
    col_idx = _build_column_index(headers)

    # 检查必要表头
    has_code = "科目代码" in col_idx
    has_name = "科目名称" in col_idx

    if not has_code and not has_name:
        raise ValueError("Excel 文件缺少必要表头：至少需要「科目代码」或「科目名称」中的一列")

    # 获取可选列表头位置
    code_col = col_idx.get("科目代码")
    name_col = col_idx.get("科目名称")
    direction_col = col_idx.get("余额方向")
    category_col = col_idx.get("科目类别")

    accounts = []
    errors = []

    for row_idx, row in enumerate(rows):
        code = row[code_col] if code_col is not None and code_col < len(row) else ""
        name = row[name_col] if name_col is not None and name_col < len(row) else ""
        direction = row[direction_col] if direction_col is not None and direction_col < len(row) else ""
        category = row[category_col] if category_col is not None and category_col < len(row) else ""

        # 跳过完全空行（已在读取时跳过，此处双重保险）
        if not code and not name:
            continue

        # 缺代码行必须报错
        if not code:
            errors.append({
                "row_index": row_idx,
                "reason": f"第 {row_idx + 2} 行缺少科目代码，该行科目名称为「{name}」",
            })
            continue

        accounts.append({
            "row_index": row_idx,
            "account_code": code,
            "account_name": name,
            "balance_direction": direction if direction else None,
            "account_category": category if category else None,
        })

    return accounts, errors


def infer_hierarchy(accounts: list[dict]) -> list[dict]:
    """
    根据科目代码推断层级关系。

    策略：
    1. 按代码长度和分隔符推断 level（顶级=1）
    2. 为每个科目找到最接近的上级科目（代码为当前代码前缀，且比当前短）
    3. 标记 is_leaf（没有其他科目以当前代码为前缀）

    返回: 更新了 level, parent_code, is_leaf 的 accounts 列表。
    """
    if not accounts:
        return accounts

    # 先按代码建立索引（code → account）
    code_map = {a["account_code"]: a for a in accounts}
    codes = sorted(code_map.keys(), key=lambda c: len(c))

    # 计算 level：基于代码结构
    for a in accounts:
        code = a["account_code"]
        # 计算分隔符出现次数作为基础层级
        sep_count = 0
        for sep in CODE_SEPARATORS:
            sep_count = max(sep_count, code.count(sep))
        # 层级 = 分隔符数 + 1
        a["level"] = sep_count + 1

    # 推断 parent：找最长的、是当前代码前缀的其他代码
    for a in accounts:
        code = a["account_code"]
        # 找所有可能的父级（代码是当前代码的前缀，且长度更短）
        candidates = []
        for other_code in codes:
            if other_code == code:
                continue
            if len(other_code) >= len(code):
                continue
            if code.startswith(other_code):
                candidates.append(other_code)

        if candidates:
            # 选最长的前缀（最近的父级）
            parent_code = max(candidates, key=len)
            a["parent_code"] = parent_code
        else:
            a["parent_code"] = None

    # 标记 is_leaf：没有任何其他科目以此代码为前缀
    for a in accounts:
        code = a["account_code"]
        is_parent = any(
            other.startswith(code) and other != code
            for other in codes
        )
        a["is_leaf"] = not is_parent

    return accounts


async def import_standard_accounts(
    db: AsyncSession,
    file_path: str,
) -> dict:
    """
    全量同步导入标准科目表。

    规则：
    - 同代码已存在：更新
    - 新代码：新增
    - 旧代码不在本次 Excel：置 is_active=false

    返回: {
        created_count, updated_count, deactivated_count,
        error_rows, warning_rows
    }
    """
    # 1. 解析 Excel
    accounts, errors = parse_standard_accounts_excel(file_path)

    # 2. 检查上传文件内重复代码
    code_seen = {}
    duplicates = []
    for a in accounts:
        code = a["account_code"]
        if code in code_seen:
            duplicates.append({
                "row_index": a["row_index"],
                "reason": f"科目代码「{code}」在第 {code_seen[code] + 2} 行和第 {a['row_index'] + 2} 行重复",
            })
        else:
            code_seen[code] = a["row_index"]

    if duplicates:
        errors.extend(duplicates)
        return {
            "created_count": 0,
            "updated_count": 0,
            "deactivated_count": 0,
            "error_rows": errors,
            "warning_rows": [],
        }

    # 3. 推断层级
    accounts = infer_hierarchy(accounts)

    # 4. 查询现有标准科目
    result = await db.execute(select(StandardAccount))
    existing_list = result.scalars().all()
    existing_map = {sa.account_code: sa for sa in existing_list}

    # 5. 本次上传的代码集合
    uploaded_codes = {a["account_code"] for a in accounts}

    # 6. 构建 parent_id 查找（需要两次遍历：先创建/更新，再关联 parent_id）
    code_to_id: dict[str, uuid.UUID] = {}

    created_count = 0
    updated_count = 0
    warning_rows = []

    for a in accounts:
        code = a["account_code"]
        parent_code = a.get("parent_code")

        if code in existing_map:
            # 更新已有科目
            sa = existing_map[code]
            sa.account_name = a["account_name"] or sa.account_name
            if a["balance_direction"] is not None:
                sa.balance_direction = a["balance_direction"]
            if a["account_category"] is not None:
                sa.account_category = a["account_category"]
            sa.level = a.get("level")
            sa.is_leaf = a.get("is_leaf", True)
            sa.source_row_index = a.get("row_index")
            # 如果之前被停用，重新启用
            if not sa.is_active:
                sa.is_active = True
            updated_count += 1
        else:
            # 新增
            sa = StandardAccount(
                account_code=code,
                account_name=a["account_name"] or "",
                balance_direction=a.get("balance_direction"),
                account_category=a.get("account_category"),
                level=a.get("level"),
                is_leaf=a.get("is_leaf", True),
                is_active=True,
                source_row_index=a.get("row_index"),
            )
            db.add(sa)
            created_count += 1

        # 暂存，flush 后有 id
        code_to_id[code] = sa
        existing_map[code] = sa

    await db.flush()

    # 7. 补 parent_id（需要在 flush 后获取 ID）
    for a in accounts:
        code = a["account_code"]
        parent_code = a.get("parent_code")
        if parent_code and parent_code in code_to_id:
            sa = code_to_id[code]
            parent_sa = code_to_id[parent_code]
            sa.parent_id = parent_sa.id

    # 8. 无法推断父级时记录 warning
    for a in accounts:
        code = a["account_code"]
        parent_code = a.get("parent_code")
        if parent_code and parent_code not in code_to_id:
            warning_rows.append({
                "row_index": a["row_index"],
                "code": code,
                "reason": f"科目「{code}」的推断父级代码「{parent_code}」不存在，保留为顶级科目",
            })

    await db.flush()

    # 9. 停用未出现在本次上传中的科目
    deactivated_count = 0
    for code, sa in existing_map.items():
        if code not in uploaded_codes and sa.is_active:
            sa.is_active = False
            deactivated_count += 1

    await db.flush()

    return {
        "created_count": created_count,
        "updated_count": updated_count,
        "deactivated_count": deactivated_count,
        "error_rows": errors,
        "warning_rows": warning_rows,
    }


async def get_standard_accounts(
    db: AsyncSession,
    *,
    is_active: bool | None = None,
    account_category: str | None = None,
    balance_direction: str | None = None,
    keyword: str | None = None,
) -> list[StandardAccount]:
    """查询标准科目列表，支持筛选。"""
    query = select(StandardAccount)

    if is_active is not None:
        query = query.where(StandardAccount.is_active == is_active)
    if account_category:
        query = query.where(StandardAccount.account_category == account_category)
    if balance_direction:
        query = query.where(StandardAccount.balance_direction == balance_direction)
    if keyword:
        like = f"%{keyword}%"
        query = query.where(
            StandardAccount.account_code.ilike(like)
            | StandardAccount.account_name.ilike(like)
        )

    query = query.order_by(StandardAccount.account_code)
    result = await db.execute(query)
    return list(result.scalars().all())


async def get_standard_account(
    db: AsyncSession,
    account_id: uuid.UUID,
) -> StandardAccount | None:
    """查询单个标准科目。"""
    result = await db.execute(
        select(StandardAccount).where(StandardAccount.id == account_id)
    )
    return result.scalar_one_or_none()


# ── 内置种子数据 ──────────────────────────────────

def load_seed_accounts_from_resource() -> list[dict]:
    """
    从内置 Python 种子数据模块加载标准科目。

    返回: account dict 列表，每个包含 account_code, account_name,
           balance_direction, account_category。
    如果模块不存在或格式错误，返回空列表。
    """
    try:
        from app.data.standard_accounts_seed import SEED_ACCOUNTS
    except ImportError:
        logger.warning("内置标准科目种子模块 app.data.standard_accounts_seed 不存在")
        return []

    if not SEED_ACCOUNTS:
        logger.warning("内置标准科目种子数据为空")
        return []

    # 校验和规范化
    valid = []
    for a in SEED_ACCOUNTS:
        code = (a.get("account_code") or "").strip()
        name = (a.get("account_name") or "").strip()
        if not code:
            continue
        direction = a.get("balance_direction") or None
        if direction and direction not in ("debit", "credit"):
            # 兼容中文方向表示
            if direction in ("借", "借方"):
                direction = "debit"
            elif direction in ("贷", "贷方"):
                direction = "credit"
            else:
                direction = None
        category = a.get("account_category") or None
        valid.append({
            "account_code": code,
            "account_name": name,
            "balance_direction": direction,
            "account_category": category,
        })

    return valid


async def seed_standard_accounts(db: AsyncSession) -> dict:
    """
    初始化标准科目主数据（仅当库中无数据时执行）。

    从内置 JSON 资源加载，解析层级，写入标准科目表。

    返回: {
        created_count: int,
        skipped: bool  # True 表示数据库已有数据，跳过初始化
    }
    """
    # 检查是否已有数据
    result = await db.execute(select(func.count(StandardAccount.id)))
    count = result.scalar()
    if count and count > 0:
        logger.info("标准科目表已有 %d 条数据，跳过初始化", count)
        return {"created_count": 0, "skipped": True}

    # 加载种子数据
    accounts = load_seed_accounts_from_resource()
    if not accounts:
        logger.warning("没有可用的内置标准科目种子数据")
        return {"created_count": 0, "skipped": True}

    # 检查种子数据内重复代码
    code_seen: dict[str, int] = {}
    for i, a in enumerate(accounts):
        code = a["account_code"]
        if code in code_seen:
            logger.error(
                "内置种子数据存在重复科目代码「%s」（第 %d、%d 条），跳过初始化",
                code, code_seen[code] + 1, i + 1,
            )
            return {"created_count": 0, "skipped": True}
        code_seen[code] = i

    # 推断层级
    accounts = infer_hierarchy(accounts)

    created = 0
    code_to_id: dict[str, uuid.UUID] = {}

    for a in accounts:
        sa = StandardAccount(
            account_code=a["account_code"],
            account_name=a["account_name"] or "",
            balance_direction=a.get("balance_direction"),
            account_category=a.get("account_category"),
            level=a.get("level"),
            is_leaf=a.get("is_leaf", True),
            is_active=True,
            source_row_index=a.get("row_index"),
        )
        db.add(sa)
        code_to_id[a["account_code"]] = sa
        created += 1

    await db.flush()

    # 补 parent_id
    for a in accounts:
        parent_code = a.get("parent_code")
        if parent_code and parent_code in code_to_id:
            sa = code_to_id[a["account_code"]]
            sa.parent_id = code_to_id[parent_code].id

    await db.flush()

    logger.info("标准科目表初始化完成，共创建 %d 条", created)
    return {"created_count": created, "skipped": False}
