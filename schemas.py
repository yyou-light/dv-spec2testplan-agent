from pydantic import BaseModel, Field
from typing import List, Literal, Optional, Dict, Any

# =====================================================================
# [Step 2] 智能探路与切块规划层 (The Planner) 的数据结构
# =====================================================================
class MergeGroup(BaseModel):
    group_name: str = Field(
        description="合并后的逻辑块名称，例如：'全局接口与复位' 或 '中断处理机制'"
    )
    sections: List[str] = Field(
        description="建议合并在一起的原始 Markdown 标题名或章节号列表。例如：['1.1 接口信号', '1.2 复位行为']"
    )

class SemanticChunkingPlan(BaseModel):
    global_context: Dict[str, str] = Field(
        description="全局上下文信息字典。必须提取全局时钟、复位信号(含有效电平)、基地址等。例如：{'clk': 'aclk', 'rst': 'aresetn (低有效)'}"
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
    spec_quote: str = Field(description="一字不差的原文反标")
    
    # 👇 把原来的 section_path 这一行彻底删掉 👇
    
    priority: Literal['P0', 'P1', 'P2'] = Field(description="测试点优先级")
    is_spec_ambiguous: bool = Field(description="如果原文描述存在矛盾、条件缺失或模糊不清，设为 True")
    ambiguity_note: str = Field(description="如果 is_spec_ambiguous 为 True，简述缺陷。否则填空字符串。")

class RawTestpointList(BaseModel):
    testpoints: List[RawTestpoint]


# =====================================================================
# [Step 5] 后置标签聚合与建树层 (The Clustering LLM) 的数据结构
# =====================================================================
class TagMapping(BaseModel):
    mapping_dict: Dict[str, str] = Field(
        description="""
        标签映射字典。
        键(Key)为输入提供的原始 raw_tag（如 'AXI响应'）。
        值(Value)必须符合 'X.基石分类-X.Y 统一二级分类' 的格式。
        基石分类仅限：接口类, 功能类, 场景类, 异常类, 上报类, corner类。
        例如：{'AXI响应': '2.功能类-2.1 AXI总线控制'}
        """
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