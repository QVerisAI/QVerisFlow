# 完整使用示例

## 1. 快速开始

### 1.1 安装和初始化

```python
# 初始化框架
from src.core import BaseAgent
from src.workspace import AgentWorkspace, WorkspaceConfig
from src.definitions import (
    # 定义组件
    AgentDefinition,
    AgentExecutionType,
    AgentDomainType,
    BackgroundInstruction,
    OutputInstruction,
    UserInstruction,
    ModelConfig,
    ToolReference,
    ToolReferenceType,
)
from src.tools import (
    # 工具组件
    ToolRegistry,
    tool,
    ToolCategory,
)
from src.verification import (
    # 验证组件
    CompositeVerifier,
    RuleBasedVerifier,
    JSONFormatRule,
    RequiredFieldsRule,
    LLMJudgeVerifier,
)
from src.orchestration import (
    # 编排组件
    WorkflowEngine,
    SmartRouter,
)
from src.registry import AgentRegistry

# 初始化工具注册表
tool_registry = ToolRegistry()

# 内置工具已自动注册（file_ls, file_read, file_write, bash_execute 等）
from src.tools import file_ls, file_read, file_write, bash_execute
```

### 1.2 创建简单 Agent

```python
# 方式一：代码定义
from src.definitions import (
    AgentDefinition,
    AgentExecutionType,
    AgentDomainType,
    BackgroundInstruction,
    OutputInstruction,
    UserInstruction,
    ModelConfig,
)

agent_def = AgentDefinition(
    agent_id="simple_analyst",
    name="简单分析师",
    description="一个简单的金融分析 Agent",
    execution_type=AgentExecutionType.EXECUTOR,
    domain_type=AgentDomainType.FINANCIAL_ANALYSIS,
    
    background_instruction=BackgroundInstruction(
        role_description="你是一位专业的金融分析师",
        core_capability="你擅长分析公司基本面和投资价值",
        task_context="在本任务中，你需要分析用户指定的公司"
    ),
    
    output_instruction=OutputInstruction(
        format_type="json",
        format_requirements=[
            "输出标准 JSON 格式",
            "不要使用 markdown 代码块"
        ],
        style_requirements=[
            "语言专业、客观",
            "结论有数据支撑"
        ]
    ),
    
    user_instruction=UserInstruction(
        task_description="请分析目标公司的投资价值",
        tool_references=["@财务数据", "@公告搜索"],
        context_references=[]
    ),
    
    # 注意：使用 llm_config 而不是 model_config
    llm_config=ModelConfig(
        model_name="deepseek/deepseek-v3",
        temperature=0.3,
        max_iterations=5
    )
)

# 方式二：YAML 文件定义
agent_def = AgentDefinition.from_yaml_file("examples/agents/simple_analyst.yaml")
```

---

## 2. 金融分析 Agent 完整示例

### 2.1 Agent 定义 (YAML)

```yaml
# examples/agents/financial_analyst.yaml

agent_id: financial_analyst_v1
name: 金融分析师
description: 专业的公司投资价值分析 Agent
version: 1.0.0

execution_type: reasoning_executor
domain_type: financial_analysis

background_instruction:
  role_description: |
    你是一位资深的金融分析师，拥有超过 10 年的 A 股市场研究经验。
    你的分析风格客观、专业，善于从多维度评估公司价值。
  
  core_capability: |
    你的核心能力包括：
    - 财务报表深度分析（三表联动）
    - 估值模型构建（PE/PB/DCF）
    - 行业比较分析
    - 风险识别与评估
  
  task_context: |
    在当前分析任务中，你需要综合运用各项分析能力，
    对目标公司进行全面的投资价值评估。

output_instruction:
  format_type: json
  format_requirements:
    - "输出标准 JSON 格式，不要包含 markdown 代码块"
    - "所有数字保留两位小数"
    - "百分比使用小数表示，如 0.15 表示 15%"
  style_requirements:
    - "分析逻辑清晰，层次分明"
    - "每个结论都有数据支撑"
    - "风险提示明确具体"
  output_schema:
    type: object
    required:
      - company_name
      - ticker
      - analysis_date
      - executive_summary
      - financial_analysis
      - valuation_analysis
      - risk_analysis
      - investment_opinion
    properties:
      company_name:
        type: string
      ticker:
        type: string
      analysis_date:
        type: string
      executive_summary:
        type: string
        description: 200字以内的执行摘要
      financial_analysis:
        type: object
        properties:
          revenue_growth:
            type: number
          net_profit_margin:
            type: number
          roe:
            type: number
          commentary:
            type: string
      valuation_analysis:
        type: object
        properties:
          current_pe:
            type: number
          historical_pe_percentile:
            type: number
          fair_value:
            type: number
          commentary:
            type: string
      risk_analysis:
        type: object
        properties:
          key_risks:
            type: array
            items:
              type: string
          risk_level:
            type: string
            enum: [高, 中, 低]
      investment_opinion:
        type: object
        properties:
          rating:
            type: string
            enum: [强烈推荐, 推荐, 中性, 谨慎, 回避]
          target_price:
            type: number
          rationale:
            type: string

user_instruction:
  task_description: |
    请对目标公司进行全面的投资价值分析，包括：
    
    1. **财务分析**
       - 分析最近4个季度的营收和利润趋势
       - 计算关键财务指标（ROE、净利率、资产负债率等）
       - 评估财务健康状况
    
    2. **估值分析**
       - 计算当前PE/PB及其历史分位
       - 与同行业公司对比
       - 给出合理估值区间
    
    3. **风险分析**
       - 识别主要风险因素
       - 评估风险等级
    
    4. **投资建议**
       - 给出评级和目标价
       - 说明投资逻辑
  
  tool_references:
    - "@财务数据"
    - "@股票价格"
    - "@公告搜索"
    - "@研报搜索"
  
  context_references: []

# 注意：使用 llm_config 而不是 model_config
llm_config:
  model_name: deepseek/deepseek-v3
  temperature: 0.3
  max_tokens: 4096
  max_iterations: 5

tool_references:
  - tool_id: financial_data
    alias: 财务数据
    reference_type: builtin
    enabled: true
  - tool_id: stock_price
    alias: 股票价格
    reference_type: builtin
    enabled: true
  - tool_id: announcement_search
    alias: 公告搜索
    reference_type: builtin
    enabled: true
  - tool_id: research_report_search
    alias: 研报搜索
    reference_type: builtin
    enabled: true

tags:
  - financial
  - analysis
  - investment
```

### 2.2 创建验证器

```python
# examples/agent_with_verification.py

from src.verification import (
    CompositeVerifier,
    RuleBasedVerifier,
    LLMJudgeVerifier,
    JSONFormatRule,
    RequiredFieldsRule,
)


def create_financial_analyst_verifier(llm_client=None) -> CompositeVerifier:
    """创建金融分析师验证器"""
    
    # 规则验证器
    rule_verifier = RuleBasedVerifier([
        JSONFormatRule(),
        RequiredFieldsRule([
            "company_name",
            "ticker",
            "executive_summary",
            "financial_analysis",
            "valuation_analysis",
            "risk_analysis",
            "investment_opinion"
        ]),
    ])
    
    verifiers = [rule_verifier]
    
    # 如果提供了 LLM 客户端，添加 LLM 评判验证器
    if llm_client:
        llm_verifier = LLMJudgeVerifier(
            llm_client=llm_client,
            criteria=[
                "分析逻辑是否清晰，各部分衔接是否自然",
                "数据引用是否准确，是否有明显的计算错误",
                "风险分析是否全面，是否遗漏重要风险",
                "投资建议是否与分析结论一致"
            ],
            threshold=0.7
        )
        verifiers.append(llm_verifier)
    
    # 注意：使用 mode 参数而不是 strategy
    return CompositeVerifier(
        verifiers=verifiers,
        mode="all",  # 所有验证器都必须通过
        short_circuit=True  # 第一个失败就停止
    )
```

### 2.3 使用 Agent

```python
# examples/simple_agent.py

import asyncio
from datetime import datetime
from typing import Any

from src.core import BaseAgent
from src.definitions import AgentDefinition
from src.workspace import AgentWorkspace, WorkspaceConfig
from src.tools import ToolRegistry


async def analyze_company(
    company: str,
    ticker: str,
    llm_client: Any,
    tool_registry: ToolRegistry = None,
):
    """分析公司投资价值"""
    
    # 1. 加载 Agent 定义
    agent_def = AgentDefinition.from_yaml_file(
        "examples/agents/financial_analyst.yaml"
    )
    
    # 2. 创建工作空间
    workspace_config = WorkspaceConfig(
        base_path="./workspaces",
        task_id=f"analysis_{ticker}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    )
    workspace = AgentWorkspace(workspace_config)
    
    # 3. 创建验证器
    from examples.agent_with_verification import create_financial_analyst_verifier
    verifier = create_financial_analyst_verifier(llm_client)
    
    # 4. 创建 Agent
    agent = BaseAgent(
        definition=agent_def,
        workspace=workspace,
        tool_registry=tool_registry or ToolRegistry(),
        verifier=verifier,
        llm_client=llm_client,
    )
    
    # 5. 运行 Agent
    result = await agent.run(
        task_description=f"分析 {company} 的投资价值",
        input_data={
            "company": company,
            "ticker": ticker
        }
    )
    
    # 6. 输出结果
    print(f"分析完成: {result['success']}")
    print(f"迭代次数: {result['iterations']}")
    
    if result['success'] and result.get('result'):
        analysis = result['result']
        print(f"\n=== {analysis.get('company_name', company)} 投资分析 ===")
        if 'investment_opinion' in analysis:
            print(f"评级: {analysis['investment_opinion'].get('rating', 'N/A')}")
            print(f"目标价: {analysis['investment_opinion'].get('target_price', 'N/A')}")
        if 'risk_analysis' in analysis:
            print(f"风险等级: {analysis['risk_analysis'].get('risk_level', 'N/A')}")
        if 'executive_summary' in analysis:
            print(f"\n执行摘要:\n{analysis['executive_summary']}")
    
    return result


# 运行分析
if __name__ == "__main__":
    # 使用 Mock LLM 进行演示
    from examples.utils.mock_llm import MockLLMClient
    
    mock_llm = MockLLMClient()
    
    result = asyncio.run(analyze_company(
        company="贵州茅台",
        ticker="600519.SH",
        llm_client=mock_llm,
    ))
```

---

## 3. 注册自定义工具

### 3.1 使用装饰器注册工具

```python
# examples/agent_with_tools.py

from src.tools import tool, ToolRegistry, ToolCategory
from src.definitions import ToolDefinition

# 获取或创建工具注册表
registry = ToolRegistry()


@tool(
    tool_id="stock_price",
    name="股票价格查询",
    alias="股票价格",
    description="查询股票实时价格和历史行情",
    category=ToolCategory.STOCK_DATA,
    input_schema={
        "type": "object",
        "properties": {
            "ticker": {
                "type": "string",
                "description": "股票代码，如 600519.SH"
            },
            "period": {
                "type": "string",
                "description": "时间周期：daily, weekly, monthly",
                "default": "daily"
            }
        },
        "required": ["ticker"]
    },
    output_schema={
        "type": "object",
        "properties": {
            "ticker": {"type": "string"},
            "price": {"type": "number"},
            "change": {"type": "number"},
            "volume": {"type": "number"}
        }
    },
    registry=registry  # 指定注册到哪个注册表
)
async def get_stock_price(ticker: str, period: str = "daily", **kwargs) -> dict:
    """查询股票价格（示例实现）"""
    # 实际实现中应调用真实的数据 API
    return {
        "ticker": ticker,
        "price": 1850.00,
        "change": 0.02,
        "volume": 5000000,
        "period": period
    }


@tool(
    tool_id="financial_data",
    name="财务数据查询",
    alias="财务数据",
    description="查询公司财务报表数据",
    category=ToolCategory.FINANCIAL_DATA,
    input_schema={
        "type": "object",
        "properties": {
            "ticker": {
                "type": "string",
                "description": "股票代码"
            },
            "report_type": {
                "type": "string",
                "description": "报表类型：income, balance, cashflow",
                "default": "income"
            },
            "periods": {
                "type": "integer",
                "description": "查询期数",
                "default": 4
            }
        },
        "required": ["ticker"]
    },
    registry=registry
)
async def get_financial_data(
    ticker: str,
    report_type: str = "income",
    periods: int = 4,
    **kwargs
) -> dict:
    """查询财务数据（示例实现）"""
    return {
        "ticker": ticker,
        "report_type": report_type,
        "data": [
            {"period": "2024Q1", "revenue": 100, "profit": 20},
            {"period": "2023Q4", "revenue": 95, "profit": 18},
        ]
    }


# 手动注册工具
def register_custom_tool():
    """手动注册工具的示例"""
    
    # 定义工具
    tool_def = ToolDefinition(
        tool_id="news_search",
        name="新闻搜索",
        alias="新闻搜索",
        description="搜索相关新闻和公告",
        category=ToolCategory.SEARCH,
        input_schema={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "搜索关键词"},
                "limit": {"type": "integer", "default": 10}
            },
            "required": ["query"]
        }
    )
    
    # 实现函数
    async def search_news(query: str, limit: int = 10, **kwargs) -> dict:
        return {
            "query": query,
            "results": [
                {"title": f"新闻 {i}", "summary": f"关于 {query} 的新闻"}
                for i in range(limit)
            ]
        }
    
    # 注册到注册表
    registry.register(tool_def, search_news)
    
    print(f"已注册工具: {tool_def.name}")
```

### 3.2 执行工具

```python
# 执行工具示例
async def execute_tools_example():
    """执行工具示例"""
    
    # 通过 tool_id 执行
    result = await registry.execute(
        tool_id="stock_price",
        params={"ticker": "600519.SH"},
        context={"workspace": workspace}  # 可选：传递工作空间用于日志
    )
    print(f"股票价格: {result}")
    
    # 通过别名执行
    tool_def = registry.get_by_alias("财务数据")
    if tool_def:
        result = await registry.execute(
            tool_id=tool_def.tool_id,
            params={"ticker": "600519.SH", "periods": 4}
        )
        print(f"财务数据: {result}")
    
    # 列出所有工具
    all_tools = registry.list_all()
    print(f"\n已注册工具 ({len(all_tools)}):")
    for t in all_tools:
        print(f"  - {t['name']} (@{t['alias']})")
```

---

## 4. 多 Agent 工作流示例

### 4.1 工作流定义

```yaml
# examples/workflows/comprehensive_analysis.yaml

workflow_id: comprehensive_analysis_v1
name: 综合投资分析工作流
description: 多 Agent 协作完成公司综合分析
version: 1.0.0

# 入口和出口节点
entry_node: start
exit_nodes:
  - end

nodes:
  - node_id: start
    name: 开始
    node_type: start

  - node_id: collect_data
    name: 数据收集
    node_type: agent
    agent_id: data_collector
    dependencies: []
    user_override: |
      收集目标公司的基础数据，包括：
      - 财务数据
      - 市场数据
      - 新闻公告
    timeout: 120

  - node_id: financial_analysis
    name: 财务分析
    node_type: agent
    agent_id: financial_analyst
    dependencies:
      - collect_data
    input_mappings:
      - source_node: collect_data
        source_field: output.data
        target_field: input.financial_data
    context_refs:
      - "#collect_data"
    timeout: 180

  - node_id: risk_assessment
    name: 风险评估
    node_type: agent
    agent_id: risk_analyst
    dependencies:
      - financial_analysis
    input_mappings:
      - source_node: financial_analysis
        source_field: output.risk_factors
        target_field: input.financial_risks
    context_refs:
      - "#financial_analysis"
    timeout: 180

  - node_id: generate_report
    name: 生成报告
    node_type: agent
    agent_id: report_generator
    dependencies:
      - financial_analysis
      - risk_assessment
    input_mappings:
      - source_node: financial_analysis
        source_field: output
        target_field: input.financial
      - source_node: risk_assessment
        source_field: output
        target_field: input.risk
    context_refs:
      - "#financial_analysis"
      - "#risk_assessment"
    timeout: 300

  - node_id: end
    name: 结束
    node_type: end
    dependencies:
      - generate_report

edges:
  - from_node: start
    to_node: collect_data

  - from_node: collect_data
    to_node: financial_analysis

  - from_node: financial_analysis
    to_node: risk_assessment

  - from_node: risk_assessment
    to_node: generate_report

  - from_node: generate_report
    to_node: end

global_context:
  default_model: deepseek/deepseek-v3

workspace_path: ./workspaces/comprehensive
```

### 4.2 执行工作流

```python
# examples/workflow_example.py

import asyncio
from typing import Any

from src.definitions import WorkflowDefinition
from src.orchestration import WorkflowEngine
from src.registry import AgentRegistry
from src.tools import ToolRegistry


async def run_comprehensive_analysis(
    company: str,
    ticker: str,
    llm_client: Any,
):
    """执行综合分析工作流"""
    
    # 1. 加载工作流定义
    workflow = WorkflowDefinition.from_yaml_file(
        "examples/workflows/comprehensive_analysis.yaml"
    )
    
    # 2. 初始化 Agent 注册表
    agent_registry = AgentRegistry()
    
    # 注册所需的 Agent（从 YAML 目录批量注册）
    agent_registry.register_from_yaml("examples/agents/")
    
    # 3. 初始化工具注册表
    tool_registry = ToolRegistry()
    
    # 4. 创建工作流引擎
    engine = WorkflowEngine(
        workflow=workflow,
        agent_registry=agent_registry,
        tool_registry=tool_registry,
        llm_client=llm_client,
        base_workspace_path="./workspaces",
    )
    
    # 5. 执行工作流
    result = await engine.execute(
        initial_input={
            "task": f"综合分析 {company} 的投资价值",
            "company": company,
            "ticker": ticker
        }
    )
    
    # 6. 输出结果
    print(f"工作流完成: {result.status}")
    print(f"耗时: {result.total_duration_ms / 1000:.2f} 秒")
    
    if result.status.value == "completed":
        print("\n节点执行结果:")
        for node_id, node_result in result.node_results.items():
            print(f"  - {node_id}: {node_result.status}")
    
    return result


# 运行
if __name__ == "__main__":
    from examples.utils.mock_llm import MockLLMClient
    
    mock_llm = MockLLMClient()
    
    result = asyncio.run(run_comprehensive_analysis(
        company="宁德时代",
        ticker="300750.SZ",
        llm_client=mock_llm,
    ))
```

---

## 5. 智能演化示例

### 5.1 使用 Meta Agent 创建新 Agent

```python
# examples/meta_agent_example.py

import asyncio
from typing import Any

from src.evolution import MetaAgent
from src.definitions import AgentExecutionType, AgentDomainType
from src.registry import AgentRegistry


async def create_custom_agent(llm_client: Any):
    """使用 Meta Agent 创建自定义 Agent"""
    
    # 初始化 Agent 注册表（用于参考已有 Agent）
    agent_registry = AgentRegistry()
    
    # 创建 Meta Agent
    meta_agent = MetaAgent(
        llm_client=llm_client,
        agent_registry=agent_registry,
        temperature=0.3,
        max_tokens=4000,
    )
    
    # 根据需求描述创建 Agent
    new_agent = await meta_agent.create_agent(
        task_description="""
        我需要一个专门分析新能源汽车行业的 Agent，它应该能够：
        
        1. 分析产业链上下游公司
        2. 跟踪行业政策变化
        3. 对比主要公司的竞争力
        4. 预测行业发展趋势
        
        输出应该是结构化的行业分析报告。
        """,
        reference_agents=["financial_analyst"],  # 参考已有 Agent
        tools=["news_search", "research_report_search", "financial_data"],
        constraints={
            "max_iterations": 5,
            "domain": AgentDomainType.FINANCIAL_ANALYSIS.value,
        }
    )
    
    print(f"创建的 Agent: {new_agent.name}")
    print(f"Agent ID: {new_agent.agent_id}")
    
    # 保存到文件
    new_agent.to_yaml_file(f"examples/agents/{new_agent.agent_id}.yaml")
    print(f"已保存到: examples/agents/{new_agent.agent_id}.yaml")
    
    return new_agent


async def generate_workflow(llm_client: Any):
    """使用 Meta Agent 生成工作流"""
    
    agent_registry = AgentRegistry()
    agent_registry.register_from_yaml("examples/agents/")
    
    meta_agent = MetaAgent(
        llm_client=llm_client,
        agent_registry=agent_registry,
    )
    
    # 生成工作流
    workflow = await meta_agent.generate_workflow(
        task_description="端到端的股票分析报告生成流程",
        available_agents=[
            "data_collector",
            "financial_analyst", 
            "risk_analyst",
            "report_generator"
        ],
    )
    
    print(f"生成的工作流: {workflow.name}")
    print(f"节点数量: {len(workflow.nodes)}")
    
    # 保存工作流
    workflow.to_yaml_file("examples/workflows/generated_workflow.yaml")
    
    return workflow


# 运行
if __name__ == "__main__":
    from examples.utils.mock_llm import MockLLMClient
    
    mock_llm = MockLLMClient()
    
    print("=== 创建自定义 Agent ===")
    new_agent = asyncio.run(create_custom_agent(mock_llm))
    
    print("\n=== 生成工作流 ===")
    workflow = asyncio.run(generate_workflow(mock_llm))
```

### 5.2 A/B 测试和优化

```python
# examples/ab_testing_example.py

import asyncio
import time
from typing import Any, Dict

from src.evolution import (
    ABTestingFramework,
    PromptOptimizer,
    VersionControl,
    OptimizationType,
)


async def run_ab_test_example():
    """运行 A/B 测试示例"""
    
    # 1. 创建 A/B 测试框架
    ab_framework = ABTestingFramework()
    
    # 2. 创建实验
    experiment = ab_framework.create_experiment(
        experiment_id="analyst_v1_vs_v2",
        name="金融分析师 V1 vs V2",
        description="测试优化后的 Prompt 是否提升分析质量",
        variants={"v1": 0.5, "v2": 0.5},  # 50/50 流量分配
        metrics=["quality_score", "latency", "token_usage"]
    )
    
    print(f"创建实验: {experiment.name}")
    print(f"实验 ID: {experiment.experiment_id}")
    
    # 3. 启动实验
    ab_framework.start_experiment(experiment.experiment_id)
    
    # 4. 模拟运行测试
    test_cases = [
        {"company": "贵州茅台", "ticker": "600519.SH"},
        {"company": "宁德时代", "ticker": "300750.SZ"},
        {"company": "比亚迪", "ticker": "002594.SZ"},
    ]
    
    for i, case in enumerate(test_cases):
        user_id = f"test_user_{i}"
        
        # 获取分配的变体
        variant = ab_framework.get_variant(experiment.experiment_id, user_id)
        print(f"\n用户 {user_id} 分配到变体: {variant}")
        
        # 模拟执行
        start_time = time.time()
        # result = await run_analysis_with_variant(case, variant)
        latency = time.time() - start_time
        
        # 记录指标
        ab_framework.record_metric(
            experiment.experiment_id,
            user_id,
            "latency",
            latency
        )
        
        ab_framework.record_metric(
            experiment.experiment_id,
            user_id,
            "quality_score",
            0.85 if variant == "v2" else 0.75  # 模拟 v2 效果更好
        )
        
        # 记录转化
        ab_framework.record_conversion(experiment.experiment_id, user_id)
    
    # 5. 获取实验结果
    results = ab_framework.get_results(experiment.experiment_id)
    print(f"\n实验结果:")
    for variant_id, result in results.items():
        print(f"  {variant_id}:")
        print(f"    转化率: {result.conversion_rate:.2%}")
        print(f"    样本数: {result.impressions}")
    
    # 6. 结束实验
    ab_framework.conclude_experiment(experiment.experiment_id)
    print(f"\n实验已结束，获胜者: {experiment.winner}")
    
    return experiment


async def optimize_prompt_example(llm_client: Any):
    """Prompt 优化示例"""
    
    # 1. 创建优化器
    optimizer = PromptOptimizer(llm_client)
    
    # 2. 注册要优化的 Prompt
    original_prompt = """
    请分析目标公司的投资价值，输出 JSON 格式的分析报告。
    """
    
    optimizer.register_prompt(
        prompt_id="financial_analyst_v1",
        prompt_text=original_prompt,
    )
    
    # 3. 优化 Prompt
    optimized = await optimizer.optimize(
        prompt_id="financial_analyst_v1",
        optimization_type=OptimizationType.QUALITY,
    )
    
    print(f"原始 Prompt:\n{original_prompt}")
    print(f"\n优化后 Prompt:\n{optimized.prompt_text}")
    
    return optimized


async def version_control_example():
    """版本控制示例"""
    
    # 1. 创建版本控制器
    vc = VersionControl(storage_path="./versions")
    
    # 2. 提交新版本
    from src.definitions import AgentDefinition
    
    agent_def = AgentDefinition.from_yaml_file(
        "examples/agents/financial_analyst.yaml"
    )
    
    version = vc.commit(
        agent_id="financial_analyst",
        definition=agent_def.model_dump(),
        version="1.0.0",
        message="初始版本",
    )
    print(f"提交版本: {version.version}")
    
    # 3. 获取版本历史
    history = vc.get_history("financial_analyst")
    print(f"\n版本历史 ({len(history)} 个版本):")
    for v in history:
        print(f"  - {v.version}: {v.message}")
    
    # 4. 回滚到指定版本
    # vc.rollback("financial_analyst", "1.0.0")
    
    return history


# 运行
if __name__ == "__main__":
    print("=== A/B 测试示例 ===")
    asyncio.run(run_ab_test_example())
    
    print("\n" + "=" * 50)
    print("=== 版本控制示例 ===")
    asyncio.run(version_control_example())
```

---

## 6. 性能监控示例

```python
# examples/performance_monitoring.py

import asyncio
from datetime import datetime, timedelta

from src.evolution import (
    AgentPerformanceMonitor,
    AgentMetrics,
    AlertRule,
    AlertSeverity,
    LogNotificationChannel,
)


async def performance_monitoring_example():
    """性能监控示例"""
    
    # 1. 创建监控器
    monitor = AgentPerformanceMonitor()
    
    # 2. 添加通知渠道
    monitor.add_channel(LogNotificationChannel())
    
    # 3. 注册告警规则
    monitor.register_rule(AlertRule(
        rule_id="low_success_rate",
        name="低成功率告警",
        description="Agent 成功率低于 80%",
        metric_name="success_rate",
        condition="< 0.8",
        severity=AlertSeverity.WARNING,
        cooldown_seconds=300,
    ))
    
    monitor.register_rule(AlertRule(
        rule_id="high_latency",
        name="高延迟告警",
        description="平均执行时间超过 10 秒",
        metric_name="avg_duration_seconds",
        condition="> 10",
        severity=AlertSeverity.CRITICAL,
        cooldown_seconds=60,
    ))
    
    # 4. 记录指标
    agent_id = "financial_analyst"
    
    # 模拟记录一些执行
    for i in range(10):
        success = i < 7  # 70% 成功率
        duration = 5.0 + i * 0.5  # 递增的执行时间
        
        monitor.record_execution(
            agent_id=agent_id,
            success=success,
            duration_seconds=duration,
            iterations=3,
            error_type=None if success else "ValidationError",
            cost=0.01,
        )
    
    # 5. 收集指标
    metrics = monitor.collect_metrics(agent_id)
    
    print(f"Agent: {agent_id}")
    print(f"  成功率: {metrics.success_rate:.2%}")
    print(f"  平均执行时间: {metrics.avg_duration_seconds:.2f}s")
    print(f"  总执行次数: {metrics.total_executions}")
    print(f"  总成本: ${metrics.total_cost:.4f}")
    
    # 6. 检查告警
    alerts = monitor.check_alerts(agent_id)
    
    if alerts:
        print(f"\n触发的告警 ({len(alerts)}):")
        for alert in alerts:
            print(f"  - [{alert.severity.value}] {alert.rule.name}: {alert.message}")
    
    # 7. 生成报告
    report = monitor.generate_report(
        agent_id=agent_id,
        start_time=datetime.now() - timedelta(hours=1),
        end_time=datetime.now(),
    )
    
    print(f"\n性能报告:")
    print(f"  时间范围: {report.start_time} - {report.end_time}")
    print(f"  总执行: {report.metrics.total_executions}")
    print(f"  成功率: {report.metrics.success_rate:.2%}")
    
    return report


# 运行
if __name__ == "__main__":
    asyncio.run(performance_monitoring_example())
```

---

## 7. CLI 使用

框架提供了命令行接口，方便快速体验各种示例：

```bash
# 查看所有可用示例
python -m examples --list

# 运行简单 Agent 示例
python -m examples simple

# 运行工具集成示例
python -m examples tools

# 运行验证器示例
python -m examples verification

# 运行工作流示例
python -m examples workflow

# 运行 Meta Agent 示例
python -m examples meta

# 运行 A/B 测试示例
python -m examples ab

# 运行性能监控示例
python -m examples monitor
```

---

## 8. 最佳实践总结

### 8.1 Agent 设计原则

1. **单一职责**：每个 Agent 专注于一个领域
2. **明确输入输出**：使用 Schema 定义清晰的接口
3. **三层 Prompt**：背景、输出、用户指令分离
4. **工具引用**：使用 `@工具名` 语法，便于管理
5. **使用 `llm_config`**：配置模型参数时使用 `llm_config` 字段

### 8.2 工作流设计原则

1. **数据驱动**：节点间通过文件系统传递数据
2. **并行优先**：独立任务并行执行
3. **容错设计**：支持 `continue_on_error`
4. **可观测性**：记录执行日志和进度
5. **依赖明确**：使用 `dependencies` 定义节点执行顺序

### 8.3 验证设计原则

1. **规则优先**：能用规则检查的用规则
2. **分层验证**：规则 → LLM 评判
3. **快速失败**：使用 `short_circuit=True`
4. **反馈闭环**：验证反馈用于下次迭代
5. **使用 `mode` 参数**：`CompositeVerifier` 使用 `mode="all"` 或 `mode="any"`

### 8.4 演化设计原则

1. **版本控制**：所有变更都有版本
2. **A/B 测试**：数据驱动决策
3. **持续优化**：自动收集反馈并优化
4. **可回滚**：支持快速回滚到稳定版本
5. **性能监控**：实时监控 Agent 性能指标

### 8.5 代码组织建议

```
my_project/
├── agents/                    # Agent YAML 定义
│   ├── simple_analyst.yaml
│   └── financial_analyst.yaml
├── workflows/                 # 工作流 YAML 定义
│   └── analysis_workflow.yaml
├── tools/                     # 自定义工具
│   ├── __init__.py
│   └── custom_tools.py
├── verifiers/                 # 自定义验证器
│   ├── __init__.py
│   └── custom_rules.py
├── workspaces/               # 工作空间（运行时生成）
└── main.py                   # 主入口
```