"""标准科目与标准科目余额表 Schema — 创建/更新/响应"""

import uuid
from typing import Literal
from datetime import datetime
from decimal import Decimal
from pydantic import BaseModel, Field, field_validator


VALID_DATA_TYPES = ("trial_balance", "journal", "subsidiary")
VALID_SCOPES = ("global", "company")
VALID_BATCH_STATUSES = ("draft", "processing", "completed", "failed")
VALID_MAPPING_STATUSES = ("pending", "mapped", "unmapped", "ignored")
VALID_DIRECTIONS = ("debit", "credit")
VALID_CATEGORIES = ("asset", "liability", "equity", "revenue", "expense", "profit_loss")


# ── StandardAccount ──────────────────────────────────

class StandardAccountCreate(BaseModel):
    """创建标准科目"""
    account_code: str = Field(..., min_length=1, max_length=50, description="科目代码")
    account_name: str = Field(..., min_length=1, max_length=200, description="科目名称")
    account_category: str | None = Field(None, max_length=50, description="科目类别")
    balance_direction: str | None = Field(None, max_length=20, description="余额方向")
    level: int | None = Field(None, ge=1, description="科目层级")
    parent_id: uuid.UUID | None = Field(None, description="上级科目ID")
    is_leaf: bool = Field(True, description="是否末级")
    is_active: bool = Field(True, description="是否启用")
    source_row_index: int | None = Field(None, ge=0, description="导入来源行序号")

    @field_validator("account_category")
    @classmethod
    def check_category(cls, v: str | None) -> str | None:
        if v is not None and v not in VALID_CATEGORIES:
            raise ValueError(f"不支持的科目类别: {v}，可选: {', '.join(VALID_CATEGORIES)}")
        return v

    @field_validator("balance_direction")
    @classmethod
    def check_direction(cls, v: str | None) -> str | None:
        if v is not None and v not in VALID_DIRECTIONS:
            raise ValueError(f"不支持的余额方向: {v}，可选: {', '.join(VALID_DIRECTIONS)}")
        return v


class StandardAccountUpdate(BaseModel):
    """更新标准科目"""
    account_name: str | None = Field(None, min_length=1, max_length=200)
    account_category: str | None = Field(None, max_length=50)
    balance_direction: str | None = Field(None, max_length=20)
    level: int | None = Field(None, ge=1)
    parent_id: uuid.UUID | None = Field(None)
    is_leaf: bool | None = Field(None)
    is_active: bool | None = Field(None)

    @field_validator("account_category")
    @classmethod
    def check_category(cls, v: str | None) -> str | None:
        if v is not None and v not in VALID_CATEGORIES:
            raise ValueError(f"不支持的科目类别: {v}，可选: {', '.join(VALID_CATEGORIES)}")
        return v

    @field_validator("balance_direction")
    @classmethod
    def check_direction(cls, v: str | None) -> str | None:
        if v is not None and v not in VALID_DIRECTIONS:
            raise ValueError(f"不支持的余额方向: {v}，可选: {', '.join(VALID_DIRECTIONS)}")
        return v


class StandardAccountResponse(BaseModel):
    """标准科目响应"""
    id: uuid.UUID
    account_code: str
    account_name: str
    account_category: str | None
    balance_direction: str | None
    level: int | None
    parent_id: uuid.UUID | None
    is_leaf: bool
    is_active: bool
    source_row_index: int | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class StandardAccountListResponse(BaseModel):
    """标准科目列表响应"""
    items: list[StandardAccountResponse]
    total: int


# ── ClientAccountMapping ──────────────────────────────

class ClientAccountMappingCreate(BaseModel):
    """创建客户科目映射经验"""
    data_type: str = Field(..., description="数据类型")
    customer_label: str | None = Field(None, max_length=200)
    source_label: str | None = Field(None, max_length=200)
    client_account_code: str | None = Field(None, max_length=100)
    client_account_name: str | None = Field(None, max_length=500)
    normalized_client_account_name: str | None = Field(None, max_length=500)
    client_account_full_path: str | None = Field(None, max_length=2000)
    standard_account_id: uuid.UUID | None = Field(None)
    standard_account_code_snapshot: str | None = Field(None, max_length=50)
    standard_account_name_snapshot: str | None = Field(None, max_length=200)
    confidence: float = Field(0.0, ge=0.0, le=1.0)
    scope: str = Field("global", description="经验范围")
    mapping_kind: str = Field("anchor", description="映射类型: anchor / override")

    @field_validator("data_type")
    @classmethod
    def check_data_type(cls, v: str) -> str:
        if v not in VALID_DATA_TYPES:
            raise ValueError(f"不支持的数据类型: {v}，可选: trial_balance / journal / subsidiary")
        return v

    @field_validator("scope")
    @classmethod
    def check_scope(cls, v: str) -> str:
        if v not in VALID_SCOPES:
            raise ValueError(f"不支持的经验范围: {v}，可选: global / company")
        return v


class ClientAccountMappingResponse(BaseModel):
    """客户科目映射经验响应"""
    id: uuid.UUID
    data_type: str
    customer_label: str | None
    source_label: str | None
    client_account_code: str | None
    client_account_name: str | None
    normalized_client_account_name: str | None
    client_account_full_path: str | None = None
    standard_account_id: uuid.UUID | None
    standard_account_code_snapshot: str | None
    standard_account_name_snapshot: str | None
    confidence: float
    scope: str
    mapping_kind: str = "anchor"
    usage_count: int
    last_used_at: datetime | None
    is_active: bool
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


# ── StandardTrialBalanceImportBatch ───────────────────

class ImportBatchCreate(BaseModel):
    """创建导入批次"""
    file_name: str = Field(..., min_length=1, max_length=500)
    customer_label: str | None = Field(None, max_length=200)
    source_label: str | None = Field(None, max_length=200)
    fiscal_year: int | None = Field(None)
    period: int | None = Field(None, ge=1, le=12)
    field_mapping: dict | None = Field(None)
    amount_mapping_config: dict | None = Field(None)
    hierarchy_config: dict | None = Field(None)


class ImportBatchResponse(BaseModel):
    """导入批次响应"""
    id: uuid.UUID
    file_name: str
    customer_label: str | None
    source_label: str | None
    fiscal_year: int | None
    period: int | None
    status: str
    field_mapping: dict | None
    amount_mapping_config: dict | None
    hierarchy_config: dict | None
    warnings: dict | None
    errors: dict | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


# ── StandardTrialBalanceRawRow ────────────────────────

class RawRowResponse(BaseModel):
    """原始行快照响应"""
    id: uuid.UUID
    batch_id: uuid.UUID
    row_index: int
    raw_values: dict
    client_account_code: str | None
    client_account_name: str | None
    client_balance_direction: str | None
    client_account_category: str | None
    detected_level: int | None
    parent_raw_row_id: uuid.UUID | None
    is_leaf: bool
    mapped_standard_account_id: uuid.UUID | None
    mapping_status: str
    # ANCHOR-INHERITANCE-MAPPING：映射角色与追溯字段
    mapping_role: str | None = None
    mapping_mode: str | None = None
    mapping_source: str | None = None
    mapping_anchor_raw_row_id: uuid.UUID | None = None
    inheritance_reason: str | None = None
    inheritance_break_reason: str | None = None
    requires_manual_confirmation: bool = False
    warnings: dict | None
    created_at: datetime

    model_config = {"from_attributes": True}


# ── StandardTrialBalanceEntry ─────────────────────────

class TrialBalanceEntryCreate(BaseModel):
    """创建标准科目余额表明细"""
    batch_id: uuid.UUID
    raw_row_id: uuid.UUID | None = None
    standard_account_id: uuid.UUID
    standard_account_code_snapshot: str = Field(..., min_length=1, max_length=50)
    standard_account_name_snapshot: str = Field(..., min_length=1, max_length=200)
    standard_account_category_snapshot: str | None = Field(None, max_length=50)
    standard_balance_direction_snapshot: str | None = Field(None, max_length=20)
    client_account_code: str | None = Field(None, max_length=100)
    client_account_name: str | None = Field(None, max_length=500)
    fiscal_year: int
    period: int = Field(..., ge=1, le=12)
    opening_debit: Decimal = Field(Decimal("0"), description="期初借方余额")
    opening_credit: Decimal = Field(Decimal("0"), description="期初贷方余额")
    current_debit: Decimal = Field(Decimal("0"), description="本期借方发生额")
    current_credit: Decimal = Field(Decimal("0"), description="本期贷方发生额")
    ending_debit: Decimal = Field(Decimal("0"), description="期末借方余额")
    ending_credit: Decimal = Field(Decimal("0"), description="期末贷方余额")


class TrialBalanceEntryResponse(BaseModel):
    """标准科目余额表明细响应"""
    id: uuid.UUID
    batch_id: uuid.UUID
    raw_row_id: uuid.UUID | None
    standard_account_id: uuid.UUID
    standard_account_code_snapshot: str
    standard_account_name_snapshot: str
    standard_account_category_snapshot: str | None
    standard_balance_direction_snapshot: str | None
    client_account_code: str | None
    client_account_name: str | None
    # ANCHOR-INHERITANCE-MAPPING：映射来源快照
    mapping_mode_snapshot: str | None = None
    mapping_source_snapshot: str | None = None
    mapping_anchor_client_account_code_snapshot: str | None = None
    mapping_anchor_client_account_name_snapshot: str | None = None
    fiscal_year: int
    period: int
    opening_debit: Decimal
    opening_credit: Decimal
    current_debit: Decimal
    current_credit: Decimal
    ending_debit: Decimal
    ending_credit: Decimal
    created_at: datetime

    model_config = {"from_attributes": True}


class TrialBalanceEntryListResponse(BaseModel):
    """标准科目余额表明细列表响应"""
    items: list[TrialBalanceEntryResponse]
    total: int


# ── Client Account Mapping Recommendation ─────────────

class ClientAccountMappingCandidate(BaseModel):
    """单个映射候选"""
    standard_account_id: str
    standard_account_code: str
    standard_account_name: str
    standard_balance_direction: str | None = None
    score: float
    source: str  # company_history / global_history / code_match / name_exact / name_similarity / code_prefix_parent / code_category_anchor / name_anchor
    reason: str
    warning: str | None = None


class ClientAccountMappingRecommendInput(BaseModel):
    """推荐请求：客户端科目列表"""
    client_account_code: str | None = Field(None, max_length=100)
    client_account_name: str | None = Field(None, max_length=500)


class ClientAccountMappingRecommendRequest(BaseModel):
    """映射推荐请求"""
    data_type: str = Field(..., description="数据类型: trial_balance / journal / subsidiary")
    customer_label: str | None = Field(None, max_length=200, description="客户标识")
    source_label: str | None = Field(None, max_length=200, description="来源标识")
    client_accounts: list[ClientAccountMappingRecommendInput] = Field(
        ..., min_length=1, max_length=500, description="客户端科目列表"
    )

    @field_validator("data_type")
    @classmethod
    def check_data_type(cls, v: str) -> str:
        if v not in VALID_DATA_TYPES:
            raise ValueError(f"不支持的数据类型: {v}，可选: trial_balance / journal / subsidiary")
        return v


class MappingRecommendEntry(BaseModel):
    """单个客户科目的推荐结果"""
    row_index: int | None = Field(None, ge=0, description="原始数据行序号")
    client_account_code: str | None
    client_account_name: str | None
    client_account_full_path: str | None = None
    parent_row_index: int | None = None
    parent_client_account_code: str | None = None
    parent_client_account_name: str | None = None
    is_leaf: bool | None = Field(None, description="是否为末级客户科目行")
    is_summary: bool | None = Field(None, description="是否为汇总父级行")
    participates_in_entry: bool | None = Field(None, description="是否参与生成标准余额表条目")
    # ANCHOR-INHERITANCE-MAPPING：映射角色与模式
    mapping_role: str | None = None
    mapping_mode: str | None = None
    requires_confirmation: bool = False
    anchor_row_index: int | None = None
    anchor_client_account_code: str | None = None
    anchor_client_account_name: str | None = None
    resolved_standard_account_id: str | None = None
    resolved_standard_account_code: str | None = None
    resolved_standard_account_name: str | None = None
    # TASK-092：suggested 是未确认的最高分候选，resolved 才是真正确认的
    suggested_standard_account_id: str | None = None
    suggested_standard_account_code: str | None = None
    suggested_standard_account_name: str | None = None
    resolution_source: str | None = None
    resolution_reason: str | None = None
    inheritance_break_reason: str | None = None
    inheritance_evidence: list[str] = []
    descendant_leaf_count: int = 0
    candidates: list[ClientAccountMappingCandidate] = []
    auto_confirm_candidate: ClientAccountMappingCandidate | None = None
    auto_confirm_status: str | None = None
    auto_confirm_reason: str | None = None


class ClientAccountMappingRecommendResponse(BaseModel):
    """映射推荐响应"""
    items: list[MappingRecommendEntry]


class ClientAccountMappingConfirmRequest(BaseModel):
    """确认保存映射请求"""
    data_type: str = Field(..., description="数据类型: trial_balance / journal / subsidiary")
    customer_label: str | None = Field(None, max_length=200, description="客户标识")
    client_account_code: str | None = Field(None, max_length=100)
    client_account_name: str | None = Field(None, max_length=500)
    standard_account_id: uuid.UUID = Field(..., description="标准科目 ID")
    standard_account_code: str = Field(..., min_length=1, max_length=50, description="标准科目代码快照")
    standard_account_name: str = Field(..., min_length=1, max_length=200, description="标准科目名称快照")
    source: str = Field("user_confirmed", description="来源: user_confirmed / user_corrected")
    confidence: float = Field(1.0, ge=0.0, le=1.0)
    allow_overwrite: bool = Field(False, description="是否允许覆盖冲突映射")

    @field_validator("data_type")
    @classmethod
    def check_data_type(cls, v: str) -> str:
        if v not in VALID_DATA_TYPES:
            raise ValueError(f"不支持的数据类型: {v}，可选: trial_balance / journal / subsidiary")
        return v

    @field_validator("source")
    @classmethod
    def check_source(cls, v: str) -> str:
        if v not in ("user_confirmed", "user_corrected"):
            raise ValueError(f"不支持的来源: {v}，可选: user_confirmed / user_corrected")
        return v


class ClientAccountMappingConfirmResponse(BaseModel):
    """确认保存映射响应"""
    status: str  # created / updated / conflict
    mapping_id: str | None = None
    conflict_detail: dict | None = None


# ── 数据查看: 批次列表 ──────────────────────────────

class BatchFilterParams(BaseModel):
    """批次列表筛选参数"""
    customer_label: str | None = Field(None, description="客户标识（模糊匹配）")
    fiscal_year: int | None = Field(None, description="会计年度")
    period: int | None = Field(None, ge=1, le=12, description="会计期间")
    import_start: datetime | None = Field(None, description="导入时间起")
    import_end: datetime | None = Field(None, description="导入时间止")


class BatchListItem(BaseModel):
    """批次列表项"""
    id: uuid.UUID
    file_name: str
    customer_label: str | None
    source_label: str | None
    fiscal_year: int | None
    period: int | None
    status: str
    entry_count: int = Field(0, description="标准化条目数")
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class BatchListResponse(BaseModel):
    """批次列表响应"""
    items: list[BatchListItem]
    total: int


# ── 数据查看: 树形视图 ──────────────────────────────

class TreeNodeResponse(BaseModel):
    """树形节点响应 — 递归结构，包含标准科目节点与客户明细节点"""
    # 节点标识与类型
    node_id: str
    node_type: Literal["account", "client_group", "entry"] = "account"

    # 标准科目信息
    standard_account_id: uuid.UUID
    account_code: str
    account_name: str
    account_category: str | None = None
    balance_direction: str | None = None
    level: int | None = None
    is_leaf: bool = False

    # 客户明细节点专属（account 节点为 None）
    entry_id: uuid.UUID | None = None
    client_account_code: str | None = None
    client_account_name: str | None = None
    # entry 节点的标准科目快照（account 节点为 None），用于前端展示「标准：141101 包装物」
    standard_account_code: str | None = None
    standard_account_name: str | None = None

    # 汇总金额（六列标准借贷）
    opening_debit: Decimal = Decimal("0")
    opening_credit: Decimal = Decimal("0")
    current_debit: Decimal = Decimal("0")
    current_credit: Decimal = Decimal("0")
    ending_debit: Decimal = Decimal("0")
    ending_credit: Decimal = Decimal("0")

    # 子树
    children: list["TreeNodeResponse"] = Field(default_factory=list)
    entry_count: int = 0
    has_children: bool = False


class TreeResponse(BaseModel):
    """树形视图响应"""
    items: list[TreeNodeResponse]
    total_nodes: int


# ── 数据查看: 明细列表 ──────────────────────────────

class EntryFilterParams(BaseModel):
    """明细列表筛选参数"""
    standard_account_code: str | None = Field(None, description="标准科目代码（模糊匹配）")
    client_account_code: str | None = Field(None, description="客户科目代码（模糊匹配）")
    fiscal_year: int | None = Field(None, description="会计年度")
    period: int | None = Field(None, ge=1, le=12, description="会计期间")
    batch_id: uuid.UUID | None = Field(None, description="批次ID")


# ── 标准化导入 API ──────────────────────────────────

VALID_IMPORT_STATUSES = ("previewed", "analyzed", "blocked", "executed", "failed")
VALID_HIERARCHY_MODES = ("auto", "code", "indent", "flat")


class FinColumnMapping(BaseModel):
    """单个金额列的字段映射配置"""
    column_id: str = Field(..., description="数据列 ID")
    field_name: str = Field(..., description="映射到的标准字段名")
    period_type: str | None = Field(None, description="期间类型: opening/current/ending（金额列必填）")
    split_mode: str | None = Field(None, description="拆分模式: two_column/single_by_direction/single_as_debit/single_as_credit")
    debit_column_id: str | None = Field(None, description="two_column 模式下对应的借方列 ID")
    credit_column_id: str | None = Field(None, description="two_column 模式下对应的贷方列 ID")


class PreviewRequest(BaseModel):
    """预览请求"""
    fiscal_year: int | None = Field(None, description="模板或手动指定的会计年度")
    period: int | None = Field(None, ge=1, le=12, description="模板或手动指定的会计期间")
    customer_label: str | None = Field(None, max_length=200, description="客户标识（被审计单位名称）")
    source_label: str | None = Field(None, max_length=200, description="来源标识（财务软件名称）")


class ColumnInfo(BaseModel):
    """列信息"""
    column_id: str
    header_text: str
    column_index: int


class PreviewResponse(BaseModel):
    """预览响应"""
    batch_id: uuid.UUID
    file_name: str
    columns: list[ColumnInfo]
    sample_rows: list[dict]
    total_rows: int
    fiscal_year: int | None
    period: int | None
    customer_label: str | None


class FinFieldMappingEntry(BaseModel):
    """字段映射条目"""
    column_id: str
    field_name: str
    period_type: str | None = None
    split_mode: str | None = None
    debit_column_id: str | None = None
    credit_column_id: str | None = None
    direction_column_id: str | None = None  # 源方向列 (single_by_source_direction 模式)


class AnalyzeRequest(BaseModel):
    """分析请求"""
    field_mappings: list[FinFieldMappingEntry] = Field(..., min_length=1, description="字段映射列表")
    fiscal_year: int = Field(..., description="会计年度")
    period: int = Field(..., ge=1, le=12, description="会计期间")
    customer_label: str | None = Field(None, max_length=200, description="客户标识")
    source_label: str | None = Field(None, max_length=200, description="来源标识")
    hierarchy_mode: str = Field("auto", description="层级识别模式: auto/code/indent/flat")

    @field_validator("hierarchy_mode")
    @classmethod
    def check_hierarchy_mode(cls, v: str) -> str:
        if v not in VALID_HIERARCHY_MODES:
            raise ValueError(f"不支持的层级模式: {v}，可选: {', '.join(VALID_HIERARCHY_MODES)}")
        return v


class HierarchyInfo(BaseModel):
    """单行层级信息"""
    row_index: int
    client_account_code: str | None
    client_account_name: str | None
    level: int | None
    parent_key: str | None
    is_leaf: bool
    is_summary: bool
    level_source: str


class AmountInfo(BaseModel):
    """单行金额信息"""
    row_index: int
    opening_debit: Decimal = Decimal("0")
    opening_credit: Decimal = Decimal("0")
    current_debit: Decimal = Decimal("0")
    current_credit: Decimal = Decimal("0")
    ending_debit: Decimal = Decimal("0")
    ending_credit: Decimal = Decimal("0")
    warnings: list[str] = []
    errors: list[str] = []


class BlockingError(BaseModel):
    """阻止入库的错误"""
    row_index: int | None = None
    code: str = ""
    message: str
    category: str  # unmapped_account / no_direction / missing_amount / missing_code_and_name


class WarningItem(BaseModel):
    """需确认的警告"""
    row_index: int | None = None
    code: str = ""
    message: str
    category: str  # parent_amount_mismatch / negative_amount / indent_suggested / disabled_standard_account


class MappingPlanSummary(BaseModel):
    """ANCHOR-INHERITANCE-MAPPING：映射计划统计。"""
    total_nodes: int = 0
    structural_summary_count: int = 0
    anchor_count: int = 0
    inherited_count: int = 0
    breakpoint_count: int = 0
    explicit_override_count: int = 0
    unresolved_count: int = 0
    confirmation_required_count: int = 0
    participating_leaf_count: int = 0
    resolved_participating_leaf_count: int = 0
    # TASK-092 性能指标
    full_recommendation_node_count: int = 0
    light_signal_node_count: int = 0
    inherited_without_recommendation_count: int = 0


class AnalyzeResponse(BaseModel):
    """分析响应"""
    batch_id: uuid.UUID
    status: str
    hierarchy: list[HierarchyInfo]
    mapping_recommendations: list[MappingRecommendEntry]
    amounts: list[AmountInfo]
    errors: list[BlockingError]
    warnings: list[WarningItem]
    mapping_summary: MappingPlanSummary | None = None
    mapping_strategy: str = "anchor_inheritance_v2"


class ConfirmedMapping(BaseModel):
    """用户确认的映射（锚点 / 显式覆盖）。

    新语义：只提交锚点、中断点和显式覆盖；普通继承行不需要提交。
    """
    row_index: int
    client_account_code: str | None = None
    client_account_name: str | None = None
    standard_account_id: uuid.UUID
    standard_account_code: str
    standard_account_name: str
    mapping_action: str = Field("anchor", description="anchor / override")
    apply_to_descendants: bool = Field(True, description="override 时是否向其后代传播")
    selection_source: str = Field(
        "user_confirmed",
        description="auto_confirmed / user_confirmed / user_corrected",
    )


class ExecuteRequest(BaseModel):
    """执行导入请求

    新语义：confirmed_mappings 只提交锚点 / 中断点 / 显式覆盖；
    普通 inherited 行不需要提交（execute 自动从树继承解析）。
    """
    confirmed_mappings: list[ConfirmedMapping] = Field(
        ..., min_length=0, description="确认的锚点 / 显式覆盖映射"
    )
    ignored_rows: list[int] = Field(default_factory=list, description="用户忽略的原始行序号列表")
    warnings_confirmed: bool = Field(False, description="是否确认所有警告，确认后继续")
    save_mapping_experience: bool = Field(True, description="是否保存映射经验")
    mapping_strategy_version: int = Field(
        2, description="映射策略版本号；与 analyze 不一致则拒绝"
    )

    @field_validator("ignored_rows")
    @classmethod
    def check_ignored_rows(cls, v: list[int]) -> list[int]:
        invalid = [row_index for row_index in v if row_index < 0]
        if invalid:
            raise ValueError("ignored_rows 只能包含非负行序号")
        if len(set(v)) != len(v):
            raise ValueError("ignored_rows 不能包含重复行序号")
        return v


class MappingSavedInfo(BaseModel):
    """映射保存结果"""
    client_account_code: str | None
    standard_account_code: str
    status: str  # created / updated / conflict
    mapping_kind: str = "anchor"  # anchor / override
    client_account_full_path: str | None = None


class ExecuteResponse(BaseModel):
    """执行导入响应"""
    batch_id: uuid.UUID
    status: str
    entry_count: int
    raw_row_count: int
    mapping_saved_count: int
    mapping_saved: list[MappingSavedInfo] = []
    anchor_count: int = 0
    breakpoint_count: int = 0
    inherited_count: int = 0
    explicit_override_count: int = 0
    unresolved_leaf_count: int = 0
    mapping_strategy_version: int = 2
