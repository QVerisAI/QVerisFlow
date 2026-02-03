# 智能演化与持续优化

## 1. 设计理念

智能演化层的核心目标是让 Agent 系统能够**在使用中不断改进**：

```
┌─────────────────────────────────────────────────────────────┐
│                    智能演化闭环                              │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│      ┌──────────┐      ┌──────────┐      ┌──────────┐      │
│      │  执行    │─────▶│  反馈    │─────▶│  优化    │      │
│      │ Execute  │      │ Feedback │      │ Optimize │      │
│      └──────────┘      └──────────┘      └──────────┘      │
│           ▲                                    │            │
│           └────────────────────────────────────┘            │
│                        部署新版本                           │
│                                                              │
│  支持的优化维度：                                            │
│  • Prompt 自动调优                                          │
│  • Agent 智能生成                                           │
│  • 工作流自动编排                                            │
│  • A/B 测试与灰度                                           │
│  • 版本管理与回滚                                            │
│                                                              │
└─────────────────────────────────────────────────────────────┘
```

---

## 2. Meta Agent：智能生成

```python
# etf_common/agent_framework/evolution/meta_agent.py

from typing import Dict, Any, List, Optional
from datetime import datetime
import json
import yaml

from ..definitions import (
    AgentDefinition,
    AgentExecutionType,
    AgentDomainType,
    BackgroundInstruction,
    OutputInstruction,
    UserInstruction,
    ModelConfig,
    ToolReference
)
from ..tools import ToolRegistry


class MetaAgent:
    """
    Meta Agent - 用于创建和优化其他 Agent
    
    能力：
    1. 根据需求描述生成新 Agent 定义
    2. 分析现有 Agent 并提出优化建议
    3. 自动优化 Prompt
    4. 生成工作流编排
    """
    
    def __init__(
        self,
        llm_client: Any,
        tool_registry: ToolRegistry,
        template_library: Dict[str, AgentDefinition] = None
    ):
        self.llm_client = llm_client
        self.tool_registry = tool_registry
        self.template_library = template_library or {}
    
    async def create_agent(
        self,
        requirement: str,
        domain: AgentDomainType = None,
        execution_type: AgentExecutionType = None,
        available_tools: List[str] = None,
        reference_agents: List[str] = None
    ) -> AgentDefinition:
        """
        根据需求描述创建新 Agent
        
        Args:
            requirement: 需求描述
            domain: 领域类型
            execution_type: 执行类型
            available_tools: 可用工具列表
            reference_agents: 参考的现有 Agent
            
        Returns:
            生成的 Agent 定义
        """
        # 获取可用工具描述
        tools_desc = ""
        if available_tools:
            tools_desc = self.tool_registry.to_prompt_descriptions(available_tools)
        else:
            tools_desc = self.tool_registry.to_prompt_descriptions()
        
        # 获取参考 Agent 描述
        refs_desc = ""
        if reference_agents:
            refs = [self.template_library.get(r) for r in reference_agents if r in self.template_library]
            refs_desc = "\n\n".join([
                f"### {r.name}\n{r.to_yaml()[:2000]}" for r in refs if r
            ])
        
        prompt = f"""你是一个专业的 Agent 设计师。请根据以下需求创建一个新的 Agent 定义。

## 需求描述
{requirement}

## 领域类型
{domain.value if domain else "自动判断"}

## 执行类型
{execution_type.value if execution_type else "自动判断"}

## 可用工具
{tools_desc}

## 参考 Agent
{refs_desc if refs_desc else "无"}

请生成完整的 Agent 定义（YAML 格式），包括：
1. 基本信息（agent_id, name, description）
2. 背景指令（role_description, core_capability, task_context）
3. 输出指令（format_type, format_requirements, style_requirements）
4. 用户指令（task_description, tool_references）
5. 模型配置
6. 工具引用

直接输出 YAML，不要包含代码块标记。
"""
        
        response = await self.llm_client.generate(prompt)
        
        # 清理响应
        yaml_content = self._clean_yaml_response(response)
        
        # 解析并验证
        try:
            data = yaml.safe_load(yaml_content)
            return AgentDefinition(**data)
        except Exception as e:
            raise ValueError(f"生成的 Agent 定义无效: {e}\n{yaml_content[:500]}")
    
    async def optimize_agent(
        self,
        agent: AgentDefinition,
        feedback: List[Dict[str, Any]],
        optimization_goals: List[str] = None
    ) -> AgentDefinition:
        """
        根据反馈优化 Agent
        
        Args:
            agent: 现有 Agent 定义
            feedback: 反馈列表，包含成功/失败案例
            optimization_goals: 优化目标
            
        Returns:
            优化后的 Agent 定义
        """
        # 分析反馈
        success_cases = [f for f in feedback if f.get("success")]
        failure_cases = [f for f in feedback if not f.get("success")]
        
        feedback_summary = f"""
成功案例数: {len(success_cases)}
失败案例数: {len(failure_cases)}

失败案例分析：
{self._summarize_failures(failure_cases)}
"""
        
        prompt = f"""你是一个 Agent 优化专家。请分析以下 Agent 的执行反馈，并提出优化建议。

## 当前 Agent 定义
```yaml
{agent.to_yaml()}
```

## 执行反馈
{feedback_summary}

## 优化目标
{optimization_goals if optimization_goals else ['提高成功率', '减少迭代次数', '提升输出质量']}

请生成优化后的 Agent 定义（完整的 YAML），主要优化：
1. Prompt 表述更清晰
2. 输出格式更明确
3. 工具使用更合理
4. 验证规则更完善

直接输出 YAML，不要包含代码块标记。
"""
        
        response = await self.llm_client.generate(prompt)
        yaml_content = self._clean_yaml_response(response)
        
        try:
            data = yaml.safe_load(yaml_content)
            optimized = AgentDefinition(**data)
            # 保留原有 ID，更新版本
            optimized.agent_id = agent.agent_id
            optimized.version = self._increment_version(agent.version)
            return optimized
        except Exception as e:
            raise ValueError(f"优化后的 Agent 定义无效: {e}")
    
    async def generate_workflow(
        self,
        task_description: str,
        available_agents: List[AgentDefinition],
        constraints: Dict[str, Any] = None
    ) -> Dict[str, Any]:
        """
        自动生成工作流编排
        
        Args:
            task_description: 任务描述
            available_agents: 可用的 Agent 列表
            constraints: 约束条件
            
        Returns:
            工作流定义（字典格式）
        """
        agents_desc = "\n".join([
            f"- {a.agent_id}: {a.name} - {a.description}"
            for a in available_agents
        ])
        
        prompt = f"""你是一个工作流设计专家。请根据任务需求设计一个多 Agent 协作的工作流。

## 任务描述
{task_description}

## 可用 Agent
{agents_desc}

## 约束条件
{json.dumps(constraints, ensure_ascii=False) if constraints else "无"}

请设计工作流并输出 YAML 格式，包括：
1. workflow_id 和 name
2. nodes 列表（包含 start, end 和 agent 节点）
3. edges 列表（定义节点间的连接和条件）
4. input_mappings（数据传递）

输出格式示例：
workflow_id: xxx
name: xxx
nodes:
  - node_id: start
    node_type: start
  - node_id: agent1
    node_type: agent
    agent_id: xxx
  ...
edges:
  - from_node: start
    to_node: agent1
  ...

直接输出 YAML。
"""
        
        response = await self.llm_client.generate(prompt)
        yaml_content = self._clean_yaml_response(response)
        
        return yaml.safe_load(yaml_content)
    
    def _clean_yaml_response(self, response: str) -> str:
        """清理 YAML 响应"""
        # 移除代码块标记
        if "```yaml" in response:
            start = response.find("```yaml") + 7
            end = response.find("```", start)
            if end > start:
                return response[start:end].strip()
        if "```" in response:
            start = response.find("```") + 3
            end = response.find("```", start)
            if end > start:
                return response[start:end].strip()
        return response.strip()
    
    def _summarize_failures(self, failures: List[Dict]) -> str:
        """总结失败案例"""
        if not failures:
            return "无失败案例"
        
        error_types = {}
        for f in failures:
            error = f.get("error", "unknown")
            error_types[error] = error_types.get(error, 0) + 1
        
        return "\n".join([
            f"- {error}: {count} 次"
            for error, count in sorted(error_types.items(), key=lambda x: -x[1])[:5]
        ])
    
    def _increment_version(self, version: str) -> str:
        """递增版本号"""
        parts = version.split(".")
        parts[-1] = str(int(parts[-1]) + 1)
        return ".".join(parts)
```

---

## 3. Prompt 自动优化器

```python
# etf_common/agent_framework/evolution/prompt_optimizer.py

from typing import Dict, Any, List, Optional, Tuple
from dataclasses import dataclass
from datetime import datetime
import json


@dataclass
class PromptVariant:
    """Prompt 变体"""
    variant_id: str
    prompt_text: str
    created_at: datetime
    performance_score: float = 0.0
    execution_count: int = 0
    success_count: int = 0
    avg_latency: float = 0.0
    avg_tokens: int = 0


class PromptOptimizer:
    """
    Prompt 自动优化器
    
    策略：
    1. 基于反馈的迭代优化
    2. 多变体 A/B 测试
    3. 自动选择最佳变体
    """
    
    def __init__(
        self,
        llm_client: Any,
        optimization_interval: int = 100  # 每 N 次执行后触发优化
    ):
        self.llm_client = llm_client
        self.optimization_interval = optimization_interval
        
        # 存储 Prompt 变体
        self.variants: Dict[str, List[PromptVariant]] = {}
        
        # 执行记录
        self.execution_logs: Dict[str, List[Dict]] = {}
    
    def register_prompt(
        self,
        prompt_id: str,
        initial_prompt: str
    ) -> str:
        """注册初始 Prompt"""
        variant = PromptVariant(
            variant_id=f"{prompt_id}_v1",
            prompt_text=initial_prompt,
            created_at=datetime.now()
        )
        self.variants[prompt_id] = [variant]
        self.execution_logs[prompt_id] = []
        return variant.variant_id
    
    def get_best_variant(self, prompt_id: str) -> Optional[PromptVariant]:
        """获取最佳变体"""
        variants = self.variants.get(prompt_id, [])
        if not variants:
            return None
        
        # 过滤执行次数足够的变体
        eligible = [v for v in variants if v.execution_count >= 10]
        if not eligible:
            return variants[0]  # 返回原始变体
        
        # 按性能得分排序
        return max(eligible, key=lambda v: v.performance_score)
    
    def get_variant_for_ab_test(
        self,
        prompt_id: str,
        exploration_rate: float = 0.1
    ) -> PromptVariant:
        """
        获取用于 A/B 测试的变体
        
        使用 epsilon-greedy 策略：
        - 以 exploration_rate 概率随机选择
        - 否则选择最佳变体
        """
        import random
        
        variants = self.variants.get(prompt_id, [])
        if not variants:
            raise ValueError(f"Prompt {prompt_id} 未注册")
        
        if random.random() < exploration_rate:
            return random.choice(variants)
        
        return self.get_best_variant(prompt_id)
    
    def record_execution(
        self,
        prompt_id: str,
        variant_id: str,
        success: bool,
        latency: float,
        tokens_used: int,
        output_quality: float = None,
        feedback: str = None
    ):
        """记录执行结果"""
        # 更新变体统计
        for variant in self.variants.get(prompt_id, []):
            if variant.variant_id == variant_id:
                variant.execution_count += 1
                if success:
                    variant.success_count += 1
                
                # 更新平均值
                n = variant.execution_count
                variant.avg_latency = (variant.avg_latency * (n-1) + latency) / n
                variant.avg_tokens = int((variant.avg_tokens * (n-1) + tokens_used) / n)
                
                # 计算性能得分
                variant.performance_score = self._calculate_score(variant, output_quality)
                break
        
        # 记录日志
        self.execution_logs[prompt_id].append({
            "variant_id": variant_id,
            "success": success,
            "latency": latency,
            "tokens": tokens_used,
            "quality": output_quality,
            "feedback": feedback,
            "timestamp": datetime.now().isoformat()
        })
        
        # 检查是否需要触发优化
        if len(self.execution_logs[prompt_id]) % self.optimization_interval == 0:
            return True  # 表示需要优化
        return False
    
    async def optimize(
        self,
        prompt_id: str,
        optimization_type: str = "quality"
    ) -> PromptVariant:
        """
        执行 Prompt 优化
        
        Args:
            prompt_id: Prompt ID
            optimization_type: 优化类型
                - "quality": 优化输出质量
                - "efficiency": 优化效率（减少 tokens）
                - "reliability": 优化可靠性（提高成功率）
        """
        variants = self.variants.get(prompt_id, [])
        if not variants:
            raise ValueError(f"Prompt {prompt_id} 未注册")
        
        # 获取最佳变体作为基准
        best = self.get_best_variant(prompt_id)
        
        # 获取最近的执行日志
        recent_logs = self.execution_logs[prompt_id][-50:]
        
        # 分析失败案例
        failures = [l for l in recent_logs if not l["success"]]
        low_quality = [l for l in recent_logs if l.get("quality", 1) < 0.7]
        
        prompt = f"""你是一个 Prompt 优化专家。请分析以下 Prompt 的执行情况并生成优化版本。

## 当前 Prompt
```
{best.prompt_text}
```

## 性能统计
- 执行次数: {best.execution_count}
- 成功率: {best.success_count / max(best.execution_count, 1):.2%}
- 平均延迟: {best.avg_latency:.2f}s
- 平均 tokens: {best.avg_tokens}

## 优化目标
{optimization_type}

## 失败案例分析
失败次数: {len(failures)}
常见反馈: {self._extract_common_feedback(failures)}

## 低质量输出分析
低质量次数: {len(low_quality)}
常见问题: {self._extract_common_feedback(low_quality)}

请生成优化后的 Prompt，要求：
1. 保持原有功能不变
2. 针对失败案例进行改进
3. 使表述更清晰准确
4. {'减少不必要的指令以节省 tokens' if optimization_type == 'efficiency' else ''}
5. {'增加错误处理指导' if optimization_type == 'reliability' else ''}

直接输出优化后的 Prompt 文本，不要包含解释。
"""
        
        response = await self.llm_client.generate(prompt)
        
        # 创建新变体
        new_variant = PromptVariant(
            variant_id=f"{prompt_id}_v{len(variants) + 1}",
            prompt_text=response.strip(),
            created_at=datetime.now()
        )
        
        self.variants[prompt_id].append(new_variant)
        
        return new_variant
    
    def _calculate_score(
        self,
        variant: PromptVariant,
        latest_quality: float = None
    ) -> float:
        """计算性能得分"""
        if variant.execution_count == 0:
            return 0.0
        
        # 成功率权重 40%
        success_rate = variant.success_count / variant.execution_count
        
        # 效率权重 30%（tokens 越少越好）
        max_tokens = 10000
        efficiency = 1 - min(variant.avg_tokens / max_tokens, 1)
        
        # 延迟权重 10%
        max_latency = 60
        latency_score = 1 - min(variant.avg_latency / max_latency, 1)
        
        # 质量权重 20%
        quality_score = latest_quality if latest_quality is not None else 0.7
        
        return (
            success_rate * 0.4 +
            efficiency * 0.3 +
            latency_score * 0.1 +
            quality_score * 0.2
        )
    
    def _extract_common_feedback(self, logs: List[Dict]) -> str:
        """提取常见反馈"""
        feedbacks = [l.get("feedback", "") for l in logs if l.get("feedback")]
        if not feedbacks:
            return "无反馈"
        
        # 简单统计
        from collections import Counter
        words = []
        for f in feedbacks:
            words.extend(f.split()[:10])
        
        common = Counter(words).most_common(5)
        return ", ".join([w for w, _ in common])
```

---

## 4. 版本控制

```python
# etf_common/agent_framework/evolution/version_control.py

from typing import Dict, Any, List, Optional
from datetime import datetime
from pathlib import Path
import json
import hashlib
import shutil


class AgentVersion:
    """Agent 版本信息"""
    
    def __init__(
        self,
        version_id: str,
        agent_id: str,
        version: str,
        definition: Dict[str, Any],
        created_at: datetime,
        author: str = "system",
        message: str = "",
        parent_version: str = None
    ):
        self.version_id = version_id
        self.agent_id = agent_id
        self.version = version
        self.definition = definition
        self.created_at = created_at
        self.author = author
        self.message = message
        self.parent_version = parent_version
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "version_id": self.version_id,
            "agent_id": self.agent_id,
            "version": self.version,
            "definition": self.definition,
            "created_at": self.created_at.isoformat(),
            "author": self.author,
            "message": self.message,
            "parent_version": self.parent_version
        }
    
    @classmethod
    def from_dict(cls, data: Dict) -> "AgentVersion":
        return cls(
            version_id=data["version_id"],
            agent_id=data["agent_id"],
            version=data["version"],
            definition=data["definition"],
            created_at=datetime.fromisoformat(data["created_at"]),
            author=data.get("author", "system"),
            message=data.get("message", ""),
            parent_version=data.get("parent_version")
        )


class VersionControl:
    """
    Agent 版本控制系统
    
    功能：
    - 版本存储和检索
    - 版本比较
    - 版本回滚
    - 版本发布（灰度）
    """
    
    def __init__(self, storage_path: str = "./agent_versions"):
        self.storage_path = Path(storage_path)
        self.storage_path.mkdir(parents=True, exist_ok=True)
        
        # 索引文件
        self.index_file = self.storage_path / "index.json"
        self.index = self._load_index()
    
    def _load_index(self) -> Dict[str, Any]:
        """加载版本索引"""
        if self.index_file.exists():
            with open(self.index_file, 'r') as f:
                return json.load(f)
        return {"agents": {}, "active_versions": {}}
    
    def _save_index(self):
        """保存版本索引"""
        with open(self.index_file, 'w') as f:
            json.dump(self.index, f, indent=2, ensure_ascii=False)
    
    def commit(
        self,
        agent_id: str,
        definition: Dict[str, Any],
        version: str,
        author: str = "system",
        message: str = ""
    ) -> AgentVersion:
        """
        提交新版本
        
        Args:
            agent_id: Agent ID
            definition: Agent 定义
            version: 版本号
            author: 作者
            message: 提交信息
            
        Returns:
            创建的版本对象
        """
        # 生成版本 ID
        content_hash = hashlib.sha256(
            json.dumps(definition, sort_keys=True).encode()
        ).hexdigest()[:12]
        version_id = f"{agent_id}_{version}_{content_hash}"
        
        # 获取父版本
        parent_version = None
        if agent_id in self.index["active_versions"]:
            parent_version = self.index["active_versions"][agent_id]
        
        # 创建版本对象
        agent_version = AgentVersion(
            version_id=version_id,
            agent_id=agent_id,
            version=version,
            definition=definition,
            created_at=datetime.now(),
            author=author,
            message=message,
            parent_version=parent_version
        )
        
        # 保存版本文件
        version_file = self.storage_path / f"{version_id}.json"
        with open(version_file, 'w') as f:
            json.dump(agent_version.to_dict(), f, indent=2, ensure_ascii=False)
        
        # 更新索引
        if agent_id not in self.index["agents"]:
            self.index["agents"][agent_id] = []
        self.index["agents"][agent_id].append(version_id)
        self.index["active_versions"][agent_id] = version_id
        self._save_index()
        
        return agent_version
    
    def get_version(self, version_id: str) -> Optional[AgentVersion]:
        """获取指定版本"""
        version_file = self.storage_path / f"{version_id}.json"
        if not version_file.exists():
            return None
        
        with open(version_file, 'r') as f:
            return AgentVersion.from_dict(json.load(f))
    
    def get_active_version(self, agent_id: str) -> Optional[AgentVersion]:
        """获取 Agent 的活跃版本"""
        version_id = self.index["active_versions"].get(agent_id)
        if not version_id:
            return None
        return self.get_version(version_id)
    
    def list_versions(self, agent_id: str) -> List[AgentVersion]:
        """列出 Agent 的所有版本"""
        version_ids = self.index["agents"].get(agent_id, [])
        versions = []
        for vid in version_ids:
            v = self.get_version(vid)
            if v:
                versions.append(v)
        return sorted(versions, key=lambda v: v.created_at, reverse=True)
    
    def rollback(self, agent_id: str, version_id: str) -> AgentVersion:
        """
        回滚到指定版本
        
        Args:
            agent_id: Agent ID
            version_id: 目标版本 ID
            
        Returns:
            回滚后的版本
        """
        version = self.get_version(version_id)
        if not version:
            raise ValueError(f"版本 {version_id} 不存在")
        
        if version.agent_id != agent_id:
            raise ValueError(f"版本 {version_id} 不属于 Agent {agent_id}")
        
        # 更新活跃版本
        self.index["active_versions"][agent_id] = version_id
        self._save_index()
        
        return version
    
    def diff(
        self,
        version_id_1: str,
        version_id_2: str
    ) -> Dict[str, Any]:
        """比较两个版本的差异"""
        v1 = self.get_version(version_id_1)
        v2 = self.get_version(version_id_2)
        
        if not v1 or not v2:
            raise ValueError("版本不存在")
        
        def find_diff(d1: Dict, d2: Dict, path: str = "") -> List[Dict]:
            diffs = []
            all_keys = set(d1.keys()) | set(d2.keys())
            
            for key in all_keys:
                current_path = f"{path}.{key}" if path else key
                
                if key not in d1:
                    diffs.append({"path": current_path, "type": "added", "value": d2[key]})
                elif key not in d2:
                    diffs.append({"path": current_path, "type": "removed", "value": d1[key]})
                elif d1[key] != d2[key]:
                    if isinstance(d1[key], dict) and isinstance(d2[key], dict):
                        diffs.extend(find_diff(d1[key], d2[key], current_path))
                    else:
                        diffs.append({
                            "path": current_path,
                            "type": "changed",
                            "old": d1[key],
                            "new": d2[key]
                        })
            
            return diffs
        
        return {
            "version_1": version_id_1,
            "version_2": version_id_2,
            "differences": find_diff(v1.definition, v2.definition)
        }
```

---

## 5. A/B 测试框架

```python
# etf_common/agent_framework/evolution/ab_testing.py

from typing import Dict, Any, List, Optional, Callable
from datetime import datetime
from dataclasses import dataclass, field
import random
import json


@dataclass
class Experiment:
    """A/B 测试实验"""
    experiment_id: str
    name: str
    description: str
    variants: Dict[str, float]  # variant_id -> 流量比例
    metrics: List[str]
    start_time: datetime
    end_time: Optional[datetime] = None
    status: str = "running"  # running, paused, completed
    results: Dict[str, Dict] = field(default_factory=dict)


class ABTestingFramework:
    """
    A/B 测试框架
    
    支持：
    - 多变体实验
    - 流量分配
    - 指标收集
    - 统计分析
    """
    
    def __init__(self):
        self.experiments: Dict[str, Experiment] = {}
        self.user_assignments: Dict[str, Dict[str, str]] = {}  # user_id -> {exp_id -> variant_id}
    
    def create_experiment(
        self,
        experiment_id: str,
        name: str,
        description: str,
        variants: Dict[str, float],
        metrics: List[str]
    ) -> Experiment:
        """
        创建实验
        
        Args:
            experiment_id: 实验 ID
            name: 实验名称
            description: 描述
            variants: 变体及其流量比例 {"control": 0.5, "treatment": 0.5}
            metrics: 关注的指标列表
            
        Returns:
            创建的实验对象
        """
        # 验证流量比例
        total = sum(variants.values())
        if abs(total - 1.0) > 0.01:
            raise ValueError(f"流量比例总和必须为 1.0，当前为 {total}")
        
        experiment = Experiment(
            experiment_id=experiment_id,
            name=name,
            description=description,
            variants=variants,
            metrics=metrics,
            start_time=datetime.now()
        )
        
        # 初始化结果
        for variant_id in variants:
            experiment.results[variant_id] = {
                "impressions": 0,
                "conversions": 0,
                "metrics": {m: [] for m in metrics}
            }
        
        self.experiments[experiment_id] = experiment
        return experiment
    
    def get_variant(
        self,
        experiment_id: str,
        user_id: str
    ) -> str:
        """
        获取用户的实验变体（确保同一用户始终看到相同变体）
        
        Args:
            experiment_id: 实验 ID
            user_id: 用户 ID
            
        Returns:
            分配的变体 ID
        """
        experiment = self.experiments.get(experiment_id)
        if not experiment or experiment.status != "running":
            return "control"  # 默认返回控制组
        
        # 检查是否已分配
        if user_id in self.user_assignments:
            if experiment_id in self.user_assignments[user_id]:
                return self.user_assignments[user_id][experiment_id]
        
        # 分配变体
        variant_id = self._assign_variant(experiment)
        
        if user_id not in self.user_assignments:
            self.user_assignments[user_id] = {}
        self.user_assignments[user_id][experiment_id] = variant_id
        
        # 记录曝光
        experiment.results[variant_id]["impressions"] += 1
        
        return variant_id
    
    def _assign_variant(self, experiment: Experiment) -> str:
        """根据流量比例分配变体"""
        r = random.random()
        cumulative = 0
        
        for variant_id, ratio in experiment.variants.items():
            cumulative += ratio
            if r < cumulative:
                return variant_id
        
        return list(experiment.variants.keys())[-1]
    
    def record_metric(
        self,
        experiment_id: str,
        user_id: str,
        metric_name: str,
        value: float
    ):
        """
        记录指标
        
        Args:
            experiment_id: 实验 ID
            user_id: 用户 ID
            metric_name: 指标名称
            value: 指标值
        """
        experiment = self.experiments.get(experiment_id)
        if not experiment:
            return
        
        # 获取用户的变体
        variant_id = self.user_assignments.get(user_id, {}).get(experiment_id)
        if not variant_id:
            return
        
        # 记录指标
        if metric_name in experiment.results[variant_id]["metrics"]:
            experiment.results[variant_id]["metrics"][metric_name].append(value)
    
    def record_conversion(
        self,
        experiment_id: str,
        user_id: str
    ):
        """记录转化"""
        experiment = self.experiments.get(experiment_id)
        if not experiment:
            return
        
        variant_id = self.user_assignments.get(user_id, {}).get(experiment_id)
        if variant_id:
            experiment.results[variant_id]["conversions"] += 1
    
    def get_results(self, experiment_id: str) -> Dict[str, Any]:
        """
        获取实验结果
        
        Returns:
            包含各变体统计数据和显著性分析的结果
        """
        experiment = self.experiments.get(experiment_id)
        if not experiment:
            return {}
        
        results = {
            "experiment_id": experiment_id,
            "name": experiment.name,
            "status": experiment.status,
            "duration_hours": (
                datetime.now() - experiment.start_time
            ).total_seconds() / 3600,
            "variants": {}
        }
        
        for variant_id, data in experiment.results.items():
            impressions = data["impressions"]
            conversions = data["conversions"]
            
            variant_results = {
                "impressions": impressions,
                "conversions": conversions,
                "conversion_rate": conversions / max(impressions, 1),
                "metrics": {}
            }
            
            # 计算各指标的统计量
            for metric_name, values in data["metrics"].items():
                if values:
                    import statistics
                    variant_results["metrics"][metric_name] = {
                        "count": len(values),
                        "mean": statistics.mean(values),
                        "std": statistics.stdev(values) if len(values) > 1 else 0,
                        "min": min(values),
                        "max": max(values)
                    }
            
            results["variants"][variant_id] = variant_results
        
        # 添加显著性分析
        results["significance"] = self._calculate_significance(experiment)
        
        return results
    
    def _calculate_significance(self, experiment: Experiment) -> Dict[str, Any]:
        """计算统计显著性（简化版）"""
        variants = list(experiment.variants.keys())
        if len(variants) < 2:
            return {"significant": False, "reason": "变体数量不足"}
        
        # 比较第一个变体（控制组）和其他变体
        control = variants[0]
        control_data = experiment.results[control]
        
        significance_results = {}
        
        for variant in variants[1:]:
            variant_data = experiment.results[variant]
            
            # 转化率比较
            control_rate = control_data["conversions"] / max(control_data["impressions"], 1)
            variant_rate = variant_data["conversions"] / max(variant_data["impressions"], 1)
            
            lift = (variant_rate - control_rate) / max(control_rate, 0.001)
            
            significance_results[f"{control}_vs_{variant}"] = {
                "control_rate": control_rate,
                "variant_rate": variant_rate,
                "lift": lift,
                "significant": abs(lift) > 0.05 and min(
                    control_data["impressions"],
                    variant_data["impressions"]
                ) > 100
            }
        
        return significance_results
    
    def conclude_experiment(
        self,
        experiment_id: str,
        winner: str = None
    ) -> Dict[str, Any]:
        """
        结束实验并选择获胜变体
        
        Args:
            experiment_id: 实验 ID
            winner: 获胜变体（可选，不指定则自动选择）
            
        Returns:
            实验结论
        """
        experiment = self.experiments.get(experiment_id)
        if not experiment:
            raise ValueError(f"实验 {experiment_id} 不存在")
        
        experiment.status = "completed"
        experiment.end_time = datetime.now()
        
        results = self.get_results(experiment_id)
        
        # 自动选择获胜者
        if not winner:
            best_rate = 0
            for variant_id, data in results["variants"].items():
                if data["conversion_rate"] > best_rate:
                    best_rate = data["conversion_rate"]
                    winner = variant_id
        
        return {
            "experiment_id": experiment_id,
            "winner": winner,
            "results": results,
            "conclusion": f"实验结束，获胜变体: {winner}"
        }
```

---

## 6. 使用示例

```python
# 示例：Agent 智能演化流程

async def evolution_example():
    from etf_common.agent_framework.evolution import (
        MetaAgent,
        PromptOptimizer,
        VersionControl,
        ABTestingFramework
    )
    
    # 1. 使用 Meta Agent 创建新 Agent
    meta_agent = MetaAgent(llm_client, tool_registry)
    
    new_agent = await meta_agent.create_agent(
        requirement="""
        我需要一个专门分析上市公司财务健康状况的 Agent，
        它应该能够：
        1. 分析三大财务报表
        2. 计算关键财务指标
        3. 评估财务风险
        4. 给出财务健康评分
        """,
        domain=AgentDomainType.FINANCIAL_ANALYSIS
    )
    
    # 2. 保存版本
    version_control = VersionControl()
    version = version_control.commit(
        agent_id=new_agent.agent_id,
        definition=new_agent.model_dump(),
        version="1.0.0",
        message="初始版本"
    )
    
    # 3. 创建 A/B 测试
    ab_framework = ABTestingFramework()
    experiment = ab_framework.create_experiment(
        experiment_id="agent_optimization_001",
        name="财务分析 Agent 优化测试",
        description="测试优化后的 Prompt 是否提升输出质量",
        variants={"control": 0.5, "optimized": 0.5},
        metrics=["quality_score", "latency", "success_rate"]
    )
    
    # 4. 执行并收集反馈
    prompt_optimizer = PromptOptimizer(llm_client)
    prompt_optimizer.register_prompt(
        "financial_analysis_prompt",
        new_agent.user_instruction.task_description
    )
    
    # 模拟执行
    for i in range(100):
        user_id = f"user_{i}"
        variant = ab_framework.get_variant(experiment.experiment_id, user_id)
        
        # 执行 Agent
        success = random.random() > 0.2
        quality = random.uniform(0.6, 1.0) if success else 0
        latency = random.uniform(1, 5)
        
        # 记录指标
        ab_framework.record_metric(experiment.experiment_id, user_id, "quality_score", quality)
        ab_framework.record_metric(experiment.experiment_id, user_id, "latency", latency)
        
        if success:
            ab_framework.record_conversion(experiment.experiment_id, user_id)
        
        # 记录到 Prompt 优化器
        prompt_optimizer.record_execution(
            "financial_analysis_prompt",
            variant,
            success,
            latency,
            tokens_used=random.randint(500, 2000),
            output_quality=quality
        )
    
    # 5. 分析结果并优化
    results = ab_framework.get_results(experiment.experiment_id)
    print(f"实验结果: {json.dumps(results, indent=2)}")
    
    # 6. 自动优化 Prompt
    optimized_variant = await prompt_optimizer.optimize(
        "financial_analysis_prompt",
        optimization_type="quality"
    )
    
    # 7. 提交优化后的版本
    new_agent.user_instruction.task_description = optimized_variant.prompt_text
    version_control.commit(
        agent_id=new_agent.agent_id,
        definition=new_agent.model_dump(),
        version="1.1.0",
        message="基于 A/B 测试结果优化 Prompt"
    )
```

---

## 7. 工作流自动生成

### 7.1 设计目标

MetaAgent 不仅能创建单个 Agent，还能根据复杂任务描述自动生成多 Agent 协作的工作流。

### 7.2 工作流生成实现

```python
# src/evolution/meta_agent.py (扩展)

class MetaAgent:
    # ... 现有代码 ...
    
    async def generate_workflow(
        self,
        task_description: str,
        available_agents: List[str],
        constraints: Optional[Dict[str, Any]] = None,
    ) -> WorkflowDefinition:
        """
        根据任务描述自动生成工作流
        
        Args:
            task_description: 任务描述
            available_agents: 可用的 Agent ID 列表
            constraints: 约束条件（如最大并行度、超时等）
            
        Returns:
            生成的工作流定义
        """
        # 获取可用 Agent 的详细信息
        agents_info = []
        for agent_id in available_agents:
            agent_def = self.agent_registry.get(agent_id)
            if agent_def:
                agents_info.append({
                    "id": agent_id,
                    "name": agent_def.name,
                    "description": agent_def.description,
                    "capabilities": agent_def.get_capabilities(),
                })
        
        prompt = f"""你是一个工作流设计专家。请根据任务需求设计一个多 Agent 协作的工作流。

## 任务描述
{task_description}

## 可用 Agent
{json.dumps(agents_info, ensure_ascii=False, indent=2)}

## 约束条件
{json.dumps(constraints, ensure_ascii=False, indent=2) if constraints else "无"}

请设计工作流并输出 JSON 格式，包括：
1. workflow_id 和 name
2. nodes 列表（包含 start, end 和 agent 节点）
3. edges 列表（定义节点间的连接和条件）
4. 并行执行的节点（如果有）

输出格式：
{{
    "workflow_id": "xxx",
    "name": "xxx",
    "description": "xxx",
    "nodes": [
        {{"node_id": "start", "node_type": "start"}},
        {{"node_id": "node1", "node_type": "agent", "agent_id": "xxx"}},
        ...
    ],
    "edges": [
        {{"from_node": "start", "to_node": "node1"}},
        {{"from_node": "node1", "to_node": "node2", "condition": "xxx"}}
    ],
    "parallel_groups": [["node1", "node2"]]  // 可并行的节点组
}}
"""
        
        response = await self.llm_client.generate(prompt)
        
        # 解析响应
        workflow_data = self._parse_json_response(response)
        
        # 构建 WorkflowDefinition
        nodes = [
            WorkflowNode(
                node_id=n["node_id"],
                node_type=n["node_type"],
                agent_id=n.get("agent_id"),
                config=n.get("config", {})
            )
            for n in workflow_data["nodes"]
        ]
        
        edges = [
            WorkflowEdge(
                from_node=e["from_node"],
                to_node=e["to_node"],
                condition=e.get("condition")
            )
            for e in workflow_data["edges"]
        ]
        
        return WorkflowDefinition(
            workflow_id=workflow_data["workflow_id"],
            name=workflow_data["name"],
            description=workflow_data.get("description", ""),
            nodes=nodes,
            edges=edges,
            metadata={
                "generated_by": "meta_agent",
                "task_description": task_description,
                "parallel_groups": workflow_data.get("parallel_groups", [])
            }
        )
```

### 7.3 使用示例

```python
# 自动生成投资分析工作流
meta_agent = MetaAgent(llm_client, agent_registry)

workflow = await meta_agent.generate_workflow(
    task_description="""
    对一家上市公司进行全面的投资分析，包括：
    1. 基本面分析（财务、估值）
    2. 技术面分析（K线形态、趋势）
    3. 舆情分析（新闻、公告）
    4. 综合评估和投资建议
    """,
    available_agents=[
        "fundamental_analyst",
        "technical_analyst", 
        "sentiment_analyst",
        "investment_advisor"
    ],
    constraints={
        "max_parallel": 3,
        "timeout_seconds": 300
    }
)

print(f"生成工作流: {workflow.name}")
print(f"节点数: {len(workflow.nodes)}")
```

---

## 8. Agent 性能监控与告警

### 8.1 设计目标

实现自动化的 Agent 性能监控和告警系统，及时发现性能问题并触发告警。

### 8.2 性能监控实现

```python
# src/evolution/performance_monitor.py

from typing import Dict, Any, List, Optional
from datetime import datetime, timedelta
from dataclasses import dataclass, field
from enum import Enum


class AlertSeverity(Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


@dataclass
class AgentMetrics:
    """Agent 性能指标"""
    total_runs: int = 0
    successful_runs: int = 0
    failed_runs: int = 0
    avg_duration_ms: float = 0.0
    avg_iterations: float = 0.0
    error_types: Dict[str, int] = field(default_factory=dict)
    success_rate: float = 0.0
    
    def calculate_success_rate(self):
        if self.total_runs > 0:
            self.success_rate = self.successful_runs / self.total_runs


@dataclass
class Alert:
    """告警"""
    rule_name: str
    severity: AlertSeverity
    message: str
    timestamp: datetime = field(default_factory=datetime.now)
    agent_id: Optional[str] = None
    metric_value: Optional[Any] = None


@dataclass
class AlertRule:
    """告警规则"""
    name: str
    condition: str  # e.g., "success_rate < 0.8"
    severity: AlertSeverity
    notification_channels: List[str] = field(default_factory=list)


@dataclass
class PerformanceReport:
    """性能报告"""
    agent_id: str
    time_window: timedelta
    metrics: AgentMetrics
    alerts: List[Alert]
    recommendations: List[str]


class AgentPerformanceMonitor:
    """
    Agent 性能监控器
    
    功能：
    - 收集 Agent 执行指标
    - 检查告警规则
    - 生成性能报告
    - 发送告警通知
    """
    
    def __init__(self, agent_registry: "AgentRegistry"):
        self.agent_registry = agent_registry
        self.alert_rules: List[AlertRule] = self._default_alert_rules()
        self._metrics_cache: Dict[str, AgentMetrics] = {}
    
    def _default_alert_rules(self) -> List[AlertRule]:
        """默认告警规则"""
        return [
            AlertRule(
                name="low_success_rate",
                condition="success_rate < 0.8",
                severity=AlertSeverity.HIGH,
                notification_channels=["email", "slack"]
            ),
            AlertRule(
                name="high_latency",
                condition="avg_duration_ms > 30000",
                severity=AlertSeverity.MEDIUM,
                notification_channels=["slack"]
            ),
            AlertRule(
                name="high_iteration_count",
                condition="avg_iterations > 5",
                severity=AlertSeverity.LOW,
                notification_channels=["slack"]
            ),
            AlertRule(
                name="critical_failure_rate",
                condition="success_rate < 0.5",
                severity=AlertSeverity.CRITICAL,
                notification_channels=["email", "slack", "pagerduty"]
            )
        ]
    
    async def collect_metrics(
        self,
        agent_id: str,
        time_window: timedelta
    ) -> AgentMetrics:
        """收集 Agent 指标"""
        # 从追踪存储获取执行记录
        from ..persistence import TraceStorage
        storage = TraceStorage()
        
        start_time = datetime.now() - time_window
        executions = await storage.get_agent_executions(
            agent_id=agent_id,
            start_time=start_time
        )
        
        metrics = AgentMetrics()
        total_duration = 0.0
        total_iterations = 0
        
        for execution in executions:
            metrics.total_runs += 1
            
            if execution.get("success"):
                metrics.successful_runs += 1
            else:
                metrics.failed_runs += 1
                error_type = execution.get("error_type", "unknown")
                metrics.error_types[error_type] = metrics.error_types.get(error_type, 0) + 1
            
            total_duration += execution.get("duration_ms", 0)
            total_iterations += execution.get("iterations", 0)
        
        if metrics.total_runs > 0:
            metrics.avg_duration_ms = total_duration / metrics.total_runs
            metrics.avg_iterations = total_iterations / metrics.total_runs
            metrics.calculate_success_rate()
        
        self._metrics_cache[agent_id] = metrics
        return metrics
    
    def check_alerts(
        self,
        agent_id: str,
        metrics: AgentMetrics
    ) -> List[Alert]:
        """检查告警规则"""
        alerts = []
        
        for rule in self.alert_rules:
            if self._evaluate_condition(rule.condition, metrics):
                alert = Alert(
                    rule_name=rule.name,
                    severity=rule.severity,
                    message=f"Agent {agent_id}: {rule.name} triggered",
                    agent_id=agent_id,
                    metric_value=self._get_metric_value(rule.condition, metrics)
                )
                alerts.append(alert)
                
                # 发送告警
                self._send_alert(alert, rule.notification_channels)
        
        return alerts
    
    def _evaluate_condition(
        self,
        condition: str,
        metrics: AgentMetrics
    ) -> bool:
        """评估告警条件"""
        # 简单的条件解析
        parts = condition.split()
        if len(parts) != 3:
            return False
        
        metric_name, operator, threshold = parts
        metric_value = getattr(metrics, metric_name, None)
        
        if metric_value is None:
            return False
        
        threshold = float(threshold)
        
        if operator == "<":
            return metric_value < threshold
        elif operator == ">":
            return metric_value > threshold
        elif operator == "<=":
            return metric_value <= threshold
        elif operator == ">=":
            return metric_value >= threshold
        elif operator == "==":
            return metric_value == threshold
        
        return False
    
    def _get_metric_value(
        self,
        condition: str,
        metrics: AgentMetrics
    ) -> Any:
        """获取条件中的指标值"""
        parts = condition.split()
        if parts:
            return getattr(metrics, parts[0], None)
        return None
    
    def _send_alert(
        self,
        alert: Alert,
        channels: List[str]
    ):
        """发送告警通知"""
        for channel in channels:
            if channel == "email":
                self._send_email_alert(alert)
            elif channel == "slack":
                self._send_slack_alert(alert)
            elif channel == "pagerduty":
                self._send_pagerduty_alert(alert)
    
    def _send_email_alert(self, alert: Alert):
        """发送邮件告警"""
        logger.warning(f"Email alert: {alert.message}")
        # 实际实现中调用邮件服务
    
    def _send_slack_alert(self, alert: Alert):
        """发送 Slack 告警"""
        logger.warning(f"Slack alert: {alert.message}")
        # 实际实现中调用 Slack API
    
    def _send_pagerduty_alert(self, alert: Alert):
        """发送 PagerDuty 告警"""
        logger.warning(f"PagerDuty alert: {alert.message}")
        # 实际实现中调用 PagerDuty API
    
    def generate_recommendations(
        self,
        metrics: AgentMetrics,
        alerts: List[Alert]
    ) -> List[str]:
        """生成优化建议"""
        recommendations = []
        
        if metrics.success_rate < 0.8:
            recommendations.append(
                f"成功率较低 ({metrics.success_rate:.1%})，建议检查 Agent 定义和验证规则"
            )
        
        if metrics.avg_iterations > 5:
            recommendations.append(
                f"平均迭代次数较高 ({metrics.avg_iterations:.1f})，"
                "建议优化 Prompt 或调整验证阈值"
            )
        
        if metrics.avg_duration_ms > 30000:
            recommendations.append(
                f"平均执行时间较长 ({metrics.avg_duration_ms/1000:.1f}s)，"
                "建议检查工具性能或减少上下文大小"
            )
        
        # 分析错误类型
        if metrics.error_types:
            top_error = max(metrics.error_types.items(), key=lambda x: x[1])
            recommendations.append(
                f"最常见错误类型: {top_error[0]} ({top_error[1]} 次)，"
                "建议针对性优化"
            )
        
        return recommendations
    
    async def generate_report(
        self,
        agent_id: str,
        time_window: timedelta = timedelta(hours=24)
    ) -> PerformanceReport:
        """生成性能报告"""
        metrics = await self.collect_metrics(agent_id, time_window)
        alerts = self.check_alerts(agent_id, metrics)
        recommendations = self.generate_recommendations(metrics, alerts)
        
        return PerformanceReport(
            agent_id=agent_id,
            time_window=time_window,
            metrics=metrics,
            alerts=alerts,
            recommendations=recommendations
        )
```

### 8.3 MetaAgent 集成性能监控

```python
class MetaAgent:
    # ... 现有代码 ...
    
    async def monitor_agent_performance(
        self,
        agent_id: str,
        time_window: timedelta = timedelta(hours=24),
    ) -> PerformanceReport:
        """
        监控 Agent 性能
        
        Args:
            agent_id: Agent ID
            time_window: 监控时间窗口
            
        Returns:
            性能报告
        """
        monitor = AgentPerformanceMonitor(self.agent_registry)
        return await monitor.generate_report(agent_id, time_window)
    
    async def auto_optimize_if_needed(
        self,
        agent_id: str,
        performance_threshold: float = 0.8
    ) -> Optional[AgentDefinition]:
        """
        根据性能自动优化 Agent
        
        如果 Agent 性能低于阈值，自动触发优化流程
        """
        report = await self.monitor_agent_performance(agent_id)
        
        if report.metrics.success_rate < performance_threshold:
            logger.info(
                f"Agent {agent_id} 性能低于阈值 "
                f"({report.metrics.success_rate:.1%} < {performance_threshold:.1%})，"
                "触发自动优化"
            )
            
            # 获取当前定义
            current_def = self.agent_registry.get(agent_id)
            
            # 构建反馈
            feedback = [{
                "success": False,
                "error": report.recommendations[0] if report.recommendations else "性能不达标"
            }]
            
            # 优化
            optimized_def = await self.optimize_agent(
                current_def,
                feedback,
                optimization_goals=["提高成功率", "减少错误"]
            )
            
            return optimized_def
        
        return None
```

### 8.4 使用示例

```python
# 性能监控示例
from evolution import MetaAgent, AgentPerformanceMonitor

meta_agent = MetaAgent(llm_client, agent_registry)

# 生成性能报告
report = await meta_agent.monitor_agent_performance(
    agent_id="financial_analyst",
    time_window=timedelta(hours=24)
)

print(f"Agent: {report.agent_id}")
print(f"总执行次数: {report.metrics.total_runs}")
print(f"成功率: {report.metrics.success_rate:.1%}")
print(f"平均耗时: {report.metrics.avg_duration_ms/1000:.2f}s")
print(f"告警数: {len(report.alerts)}")
print(f"优化建议: {report.recommendations}")

# 自动优化
optimized = await meta_agent.auto_optimize_if_needed(
    agent_id="financial_analyst",
    performance_threshold=0.85
)

if optimized:
    print(f"已自动优化 Agent: {optimized.agent_id}")
```
