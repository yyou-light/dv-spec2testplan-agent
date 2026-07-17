from pydantic import BaseModel, Field
from typing import List, Literal, Dict, Any

# =====================================================================
# [Step 2] 智能探路与切块规划层 (The Planner) 的数据结构
# =====================================================================
class SpecFact(BaseModel):
    fact_id: str = Field(
        description="全局事实稳定编号，例如 GF-RESET-001、GF-AXI-001。"
    )
    topic: str = Field(
        description="事实主题，例如 clock_reset、interface、address、timing、constraint、error_response。"
    )
    subject: str = Field(
        description="事实主体，例如 aresetn、AXI data width、maximum burst length。"
    )
    value: str = Field(
        description="Spec 已确认的事实内容，不得补写 Spec 没有给出的设计结论。"
    )
    section: str = Field(
        description="事实所在的 Markdown 章节标题。"
    )
    evidence: str = Field(
        description="能够直接支持该事实的一字不差 Spec 原文。"
    )


class GlobalSpecContext(BaseModel):
    module_name: str = Field(
        default="",
        description="Spec 描述的模块或 IP 名称。"
    )
    module_summary: str = Field(
        default="",
        description="模块职责的简短摘要，只陈述 Spec 已确认内容。"
    )
    confirmed_facts: List[SpecFact] = Field(
        default_factory=list,
        description="从完整 Spec 跨章节提取的已确认事实，必须带章节和原文证据。"
    )
    unresolved_questions: List[str] = Field(
        default_factory=list,
        description="Spec 确实存在且会影响已声明功能验证的问题；不要罗列协议所有可选能力。"
    )


class MergeGroup(BaseModel):
    group_name: str = Field(
        description="合并后的逻辑块名称，例如：'全局接口与复位' 或 '中断处理机制'"
    )
    sections: List[str] = Field(
        description="建议合并在一起的原始 Markdown 标题名或章节号列表。例如：['1.1 接口信号', '1.2 复位行为']"
    )

class SemanticChunkingPlan(BaseModel):
    global_context: GlobalSpecContext = Field(
        description="从完整 Spec 提取的结构化全局事实表，供每个 Chunk 共享。"
    )
    merge_groups: List[MergeGroup] = Field(
        description="语义合并切块方案列表。指导 Python 如何将高内聚的短章节合并为处理单元。"
    )
    planning_reasoning: str = Field(
        description="简要说明切分和合并的理由，方便人工 Debug。"
    )


# =====================================================================
# [Step 4] 扁平化循环提取层 (The Extractor) 的数据结构
# =====================================================================
class RawTestpoint(BaseModel):
    raw_tag: str = Field(description="极简的特征标签，如'AXI写异常'")
    summary: str = Field(description="测试点的一句话摘要")
    details: str = Field(description="详细的测试行为描述")
    spec_quote: str = Field(description="依据反标。优先填写一字不差的 Spec 原文；如果是 skill 经验补充且无合适 Spec 反标，填写 skill 规则反标。")
    
    # 👇 把原来的 section_path 这一行彻底删掉 👇
    
    priority: Literal['P0', 'P1', 'P2'] = Field(description="测试点优先级")
    is_spec_ambiguous: bool = Field(description="如果原文描述存在矛盾、条件缺失或模糊不清，设为 True")
    ambiguity_note: str = Field(description="如果 is_spec_ambiguous 为 True，简述缺陷。否则填空字符串。")

class RawTestpointList(BaseModel):
    testpoints: List[RawTestpoint]


# =====================================================================
# [Step 5] 完整测试点分类与建树层的数据结构
# =====================================================================
PrimaryCategory = Literal[
    "1.接口类",
    "2.功能类",
    "3.场景类",
    "4.异常类",
    "5.上报类",
    "6.corner类",
]

LegalityClass = Literal[
    "legal_supported",
    "defined_error_condition",
    "unsupported_or_illegal",
    "spec_ambiguous",
]

VerificationIntent = Literal[
    "interface_contract",
    "normal_function",
    "workflow_scenario",
    "error_handling",
    "reporting",
    "corner_interaction",
]

CornerTrigger = Literal[
    "resource_saturation",
    "sustained_stall_recovery",
    "concurrent_conflict",
    "critical_state_transition",
    "multi_constraint_extreme",
    "multiple_error_interaction",
]

OutcomeFocus = Literal[
    "normal_supported_behavior",
    "single_error_handling",
    "workflow_behavior",
    "reporting_behavior",
    "state_or_resource_interaction",
    "multiple_error_interaction",
]


class IndexedTestpoint(BaseModel):
    testpoint_id: str = Field(
        description="分类前分配的稳定内部编号，例如 RTP_0001。"
    )
    source_chunk: str = Field(
        description="生成该测试点的原始 Chunk 名称。"
    )
    testpoint: RawTestpoint


class RawTestpointBundle(BaseModel):
    source_path: str
    global_context: Dict[str, Any]
    audit_enabled: bool
    indexed_testpoints: List[IndexedTestpoint]


class SecondaryCategory(BaseModel):
    category_id: str = Field(
        description="稳定二级目录编号，例如 FUNC-SRAM-READ。"
    )
    primary_category: PrimaryCategory
    name: str = Field(
        description="简短、可复用的二级目录名称。"
    )
    description: str = Field(
        description="该二级目录负责收纳的测试意图边界。"
    )


class ClassificationTaxonomy(BaseModel):
    secondary_categories: List[SecondaryCategory] = Field(
        default_factory=list,
        description="在固定六个一级目录下，为当前 DUT 建立的有限二级目录。"
    )


class TestpointAssignment(BaseModel):
    testpoint_id: str
    primary_category: PrimaryCategory
    secondary_category_id: str
    category_fit: bool = Field(
        description="现有二级目录的名称和描述是否准确覆盖该测试点主意图。"
    )
    category_fit_reason: str = Field(
        description="说明为何现有目录匹配；不匹配时说明缺失的验证主题。"
    )
    proposed_secondary_category: SecondaryCategory | None = Field(
        default=None,
        description="category_fit=False 时提出的新二级目录，否则必须为空。"
    )
    legality: LegalityClass = Field(
        description="刺激属于合法正常、Spec已定义错误、非法/不支持或待澄清。"
    )
    verification_intent: VerificationIntent = Field(
        description="决定一级目录的主验证意图。"
    )
    outcome_focus: OutcomeFocus = Field(
        description=(
            "该测试点最终要确认的结果域，用于区分正常行为、单一错误机制、"
            "完整场景、上报、状态/资源交互和多错误机制交互。"
        )
    )
    error_mechanisms: List[str] = Field(
        default_factory=list,
        description=(
            "single_error_handling 填一个主要错误机制；"
            "multiple_error_interaction 填至少两个相互独立的错误机制。"
        )
    )
    corner_triggers: List[CornerTrigger] = Field(
        default_factory=list,
        description="仅 corner_interaction 可填写的真实 corner 触发条件。"
    )
    corner_evidence: str = Field(
        default="",
        description="仅 corner_interaction 填写，说明具体极限、冲突、恢复或状态交互。"
    )
    reasoning: str = Field(
        description="根据完整测试意图和 Spec 合法范围给出的简短分类依据。"
    )
    confidence: Literal["high", "medium", "low"]
    needs_split: bool = Field(
        default=False,
        description="兼容审计字段。原子性由分类前独立阶段处理，分类输出必须为 False。"
    )
    split_reason: str = Field(
        default="",
        description="needs_split 为 True 时说明混合了哪些不同验证意图。"
    )


class TestpointClassificationResult(BaseModel):
    assignments: List[TestpointAssignment] = Field(
        default_factory=list,
        description="每条内部测试点 ID 的唯一分类结果。"
    )


class TestpointSplit(BaseModel):
    original_testpoint_id: str
    rationale: str = Field(
        description="为什么原测试点包含不同合法性或不同预期响应。"
    )
    normal_completion_present: bool = Field(
        description="原测试点是否明确包含合法事务正常完成、正常数据或OKAY等成功预期。"
    )
    error_response_present: bool = Field(
        description="原测试点是否明确包含SLVERR、DECERR或拒绝不支持操作等错误响应预期。"
    )
    single_invariant_or_scenario: bool = Field(
        description="多个条件是否共同定义一个信号不变量或一个不可拆的完整场景。"
    )
    unresolved_design_alternatives: bool = Field(
        description="分支是否只是Spec未决的互斥设计选择，拆分不能解决该歧义。"
    )
    separable_stimulus_classes: bool = Field(
        description=(
            "是否能按客观输入条件切分为合法/非法等不同刺激域；"
            "即使具体边界或错误码待澄清，也可为True。"
        )
    )
    replacements: List[RawTestpoint] = Field(
        description="语义完整、验证意图单一且不丢失原内容的替代测试点。"
    )


class TestpointKeepDecision(BaseModel):
    testpoint_id: str
    rationale: str = Field(
        description="为什么该测试点作为一个完整验证意图保留。"
    )
    normal_completion_present: bool
    error_response_present: bool
    single_invariant_or_scenario: bool
    unresolved_design_alternatives: bool
    separable_stimulus_classes: bool


class TestpointAtomicityReview(BaseModel):
    splits: List[TestpointSplit] = Field(
        default_factory=list,
        description="独立原子性审查确认必须拆分的测试点。"
    )
    kept_testpoints: List[TestpointKeepDecision] = Field(
        default_factory=list,
        description="逐条确认保留的测试点，和splits共同完整覆盖全部输入ID。"
    )

# =====================================================================
# [Step 6] 找茬大模型 (The AI Critic) 的审计报告数据结构
# =====================================================================
class OmissionEvidence(BaseModel):
    missed_sentence: str = Field(
        description="Spec 原文中被遗漏的、包含关键硬件行为的具体句子。"
    )
    reasoning: str = Field(
        description="详细解释为什么这句话对应一个独立的测试点，以及漏测风险。"
    )

class AuditReport(BaseModel):
    is_passed: bool = Field(
        description="审计是否通过。True 表示未发现明显漏测；False 表示发现漏测证据。"
    )
    omissions: List[OmissionEvidence] = Field(
        default=[],
        description="如果审计未通过，列出所有发现的漏测证据。"
    )
    critic_notes: str = Field(
        description="Critic 对本次审计的整体评价。"
    )


# =====================================================================
# [Step 4A] 全局 Skill 规则分配计划
# =====================================================================
class SkillRuleApplication(BaseModel):
    rule_ref: str = Field(
        description="Skill 规则引用，例如 axi.md#AXI-IMP-004。"
    )
    target_chunks: List[str] = Field(
        description="负责落实该规则的 Chunk 名称。默认一个；仅不同验证对象确有必要时允许多个。"
    )
    rationale: str = Field(
        description="为什么该规则应分配给这些 Chunk。"
    )
    coverage_targets: List[str] = Field(
        default_factory=list,
        description="需要覆盖的不同对象，例如 AW/W/B/AR/R；不是测试点固定写作模板。"
    )


class SkillRoutingPlan(BaseModel):
    applications: List[SkillRuleApplication] = Field(
        default_factory=list,
        description="候选 Skill 规则到 Chunk 的全局分配结果。"
    )
