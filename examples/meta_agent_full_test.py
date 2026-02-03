"""
Meta Agent 完整测试示例

展示完整流程：
1. 使用 MetaAgent 创建 Agent 定义
2. 持久化存储 Agent 定义
3. 生成工作流定义
4. 执行工作流进行完整任务测试
5. 查看执行结果和存储的文件

配置文件: config/app_config.yaml
"""

import asyncio
import sys
import json
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.evolution import MetaAgent, VersionControl
from src.registry import AgentRegistry
from src.tools import ToolRegistry
from src.orchestration import WorkflowEngine
from src.workspace import AgentWorkspace, WorkspaceConfig
from src.config import create_llm_client, create_qveris_adapter, get_qveris_config
from src.definitions import AgentExecutionType, AgentDomainType


class MetaAgentFullTest:
    """Meta Agent 完整测试类"""

    def __init__(
        self,
        model_name: str = "qwen-plus",
        workspace_base: str = "./workspaces/meta_agent_test",
        version_storage: str = "./storage/agent_versions",
    ):
        self.model_name = model_name
        self.workspace_base = workspace_base
        self.version_storage = version_storage

        # 确保目录存在
        Path(workspace_base).mkdir(parents=True, exist_ok=True)
        Path(version_storage).mkdir(parents=True, exist_ok=True)

        # 初始化组件
        self.agent_registry = AgentRegistry()
        self.tool_registry = ToolRegistry.get_default()
        self.version_control = VersionControl(version_storage)
        self.llm_client = None
        self.meta_agent = None
        self.qveris_adapter = None

    async def initialize(self):
        """初始化 LLM 客户端和 MetaAgent"""
        print("\n📦 初始化组件...")
        print("-" * 50)

        # 创建 LLM 客户端
        try:
            unified_client = create_llm_client(
                model_name=self.model_name, client_type="langchain"
            )
            self.llm_client = unified_client.get_langchain_client()
            print(f"   ✅ LLM 客户端: {unified_client.model_name}")
        except Exception as e:
            print(f"   ❌ LLM 客户端创建失败: {e}")
            print("   请检查 config/app_config.yaml 中的 API 配置")
            raise

        # 初始化 QVeris 工具适配器（注册 qveris_search_tools 和 qveris_execute_tool）
        qveris_config = get_qveris_config()
        if qveris_config.get("enabled", False):
            try:
                self.qveris_adapter = create_qveris_adapter(self.tool_registry)
                if self.qveris_adapter:
                    self.qveris_adapter.register_meta_tools()
                    print("   ✅ QVeris 远程工具已注册 (qveris_search_tools, qveris_execute_tool)")
                else:
                    print("   ⚠️ QVeris 适配器创建失败")
            except Exception as e:
                print(f"   ⚠️ QVeris 工具注册失败: {e}")
        else:
            print("   ℹ️ QVeris 未启用（在 config/app_config.yaml 中配置）")

        # 加载已有 Agent 定义（作为参考）
        agents_dir = Path(__file__).parent / "agents"
        if agents_dir.exists():
            try:
                self.agent_registry.register_from_yaml(str(agents_dir))
                agent_ids = [a["agent_id"] for a in self.agent_registry.list_all()]
                print(f"   ✅ 加载参考 Agent: {agent_ids}")
            except Exception as e:
                print(f"   ⚠️ 加载参考 Agent 失败: {e}")

        # 创建 MetaAgent
        self.meta_agent = MetaAgent(
            llm_client=self.llm_client,
            agent_registry=self.agent_registry,
            tool_registry=self.tool_registry,
            temperature=0.3,
            max_tokens=4000,
        )
        print("   ✅ MetaAgent 创建成功")

    async def create_and_persist_agents(self) -> list:
        """创建 Agent 并持久化存储"""
        print("\n🤖 创建智能体定义...")
        print("-" * 50)

        created_agents = []

        # 创建数据收集 Agent
        print("\n   [1/3] 创建数据收集 Agent...")
        try:
            data_agent = await self.meta_agent.create_agent(
                task_description="""
                创建一个数据收集 Agent，专门负责：
                1. 搜索和获取公司的基本信息
                2. 收集财务数据摘要
                3. 整理新闻和公告信息
                
                输出应该是结构化的数据汇总。
                """,
                tools=["qveris_search_tools", "qveris_execute_tool"],
                constraints={
                    "max_iterations": 5,
                    "domain": AgentDomainType.DATA_INTEGRATION.value,
                },
            )
            created_agents.append(data_agent)
            print(f"      ✅ 创建成功: {data_agent.name} ({data_agent.agent_id})")

            # 持久化到版本控制
            self._save_agent_version(data_agent)

            # 注册到 Registry
            self.agent_registry.register_definition(data_agent)

        except Exception as e:
            print(f"      ❌ 创建失败: {e}")

        # 创建分析 Agent
        print("\n   [2/3] 创建分析 Agent...")
        try:
            analysis_agent = await self.meta_agent.create_agent(
                task_description="""
                创建一个分析 Agent，专门负责：
                1. 分析收集到的数据
                2. 提取关键指标和趋势
                3. 形成分析结论
                
                输出应该是结构化的分析报告。
                """,
                tools=["file_read", "file_write"],
                constraints={
                    "max_iterations": 5,
                    "domain": AgentDomainType.FINANCIAL_ANALYSIS.value,
                },
            )
            created_agents.append(analysis_agent)
            print(
                f"      ✅ 创建成功: {analysis_agent.name} ({analysis_agent.agent_id})"
            )

            self._save_agent_version(analysis_agent)
            self.agent_registry.register_definition(analysis_agent)

        except Exception as e:
            print(f"      ❌ 创建失败: {e}")

        # 创建报告生成 Agent
        print("\n   [3/3] 创建报告生成 Agent...")
        try:
            report_agent = await self.meta_agent.create_agent(
                task_description="""
                创建一个报告生成 Agent，专门负责：
                1. 汇总所有分析结果
                2. 生成结构化报告
                3. 提供投资建议
                
                输出应该是完整的投资分析报告。
                """,
                tools=["file_read", "file_write"],
                constraints={
                    "max_iterations": 3,
                    "domain": AgentDomainType.REPORT_GENERATION.value,
                },
            )
            created_agents.append(report_agent)
            print(f"      ✅ 创建成功: {report_agent.name} ({report_agent.agent_id})")

            self._save_agent_version(report_agent)
            self.agent_registry.register_definition(report_agent)

        except Exception as e:
            print(f"      ❌ 创建失败: {e}")

        print(f"\n   📊 共创建 {len(created_agents)} 个 Agent")
        return created_agents

    def _save_agent_version(self, agent_def):
        """保存 Agent 版本"""
        try:
            # 转换为字典
            agent_dict = (
                agent_def.model_dump()
                if hasattr(agent_def, "model_dump")
                else vars(agent_def)
            )

            # 提交到版本控制
            version = self.version_control.commit(
                agent_id=agent_def.agent_id,
                definition=agent_dict,
                version=agent_def.version or "1.0.0",
                author="meta_agent",
                message=f"由 MetaAgent 自动生成",
                auto_activate=True,
            )
            print(f"      💾 已保存版本: {version.version_id}")

            # 同时保存为 YAML 文件（便于查看）
            yaml_path = (
                Path(self.version_storage) / "yaml" / f"{agent_def.agent_id}.yaml"
            )
            yaml_path.parent.mkdir(parents=True, exist_ok=True)

            import yaml

            with open(yaml_path, "w", encoding="utf-8") as f:
                yaml.dump(agent_dict, f, allow_unicode=True, default_flow_style=False)
            print(f"      📄 已导出 YAML: {yaml_path}")

        except Exception as e:
            print(f"      ⚠️ 保存版本失败: {e}")

    async def generate_workflow(self, agent_ids: list):
        """生成工作流定义"""
        print("\n🔄 生成工作流定义...")
        print("-" * 50)

        try:
            workflow = await self.meta_agent.generate_workflow(
                task_description="""
                设计一个端到端的投资分析工作流：
                1. 首先收集目标公司的数据
                2. 然后进行深度分析
                3. 最后生成投资分析报告
                
                每个阶段应该有清晰的输入输出。
                """,
                available_agents=agent_ids,
                constraints={
                    "max_parallel": 2,
                    "timeout": 300,
                },
                include_error_handling=True,
            )

            print(f"   ✅ 工作流生成成功")
            print(f"      ID: {workflow.workflow_id}")
            print(f"      名称: {workflow.name}")
            print(f"      节点数: {len(workflow.nodes)}")
            print(f"      边数: {len(workflow.edges)}")

            # 打印节点信息
            print("\n   📋 节点列表:")
            for node in workflow.nodes:
                deps = f" (依赖: {node.dependencies})" if node.dependencies else ""
                agent_info = f" [Agent: {node.agent_id}]" if node.agent_id else ""
                print(f"      - [{node.node_type.value}] {node.name}{agent_info}{deps}")

            # 保存工作流定义
            workflow_path = Path(self.workspace_base) / "workflow_definition.json"
            workflow_dict = (
                workflow.model_dump()
                if hasattr(workflow, "model_dump")
                else vars(workflow)
            )
            with open(workflow_path, "w", encoding="utf-8") as f:
                json.dump(workflow_dict, f, ensure_ascii=False, indent=2, default=str)
            print(f"\n   💾 工作流已保存: {workflow_path}")

            return workflow

        except Exception as e:
            print(f"   ❌ 生成失败: {e}")
            import traceback

            traceback.print_exc()
            return None

    async def execute_workflow(self, workflow, task_input: dict):
        """执行工作流进行完整任务测试"""
        print("\n🚀 执行工作流...")
        print("-" * 50)

        if not workflow:
            print("   ❌ 没有可执行的工作流")
            return None

        try:
            # 创建工作流引擎
            engine = WorkflowEngine(
                agent_registry=self.agent_registry,
                tool_registry=self.tool_registry,
                llm_client=self.llm_client,
                workspace_base_path=self.workspace_base,
                auto_checkpoint=True,
            )

            print(f"   📝 任务输入: {json.dumps(task_input, ensure_ascii=False)}")
            print("   ⏳ 开始执行...\n")

            # 执行工作流
            result = await engine.execute(
                workflow_definition=workflow,
                initial_context={
                    "task": task_input.get("task", "分析任务"),
                    **task_input,
                },
            )

            # 打印结果
            print("\n   📊 执行结果:")
            print(f"      状态: {result.status.value}")
            print(f"      耗时: {result.total_duration_ms:.2f}ms")

            if result.error:
                print(f"      错误: {result.error}")

            if result.node_results:
                print("\n   📋 节点执行结果:")
                for node_id, node_result in result.node_results.items():
                    status = (
                        node_result.status
                        if hasattr(node_result, "status")
                        else "unknown"
                    )
                    print(f"      - {node_id}: {status}")

            if result.final_output:
                print("\n   📄 最终输出:")
                output_str = json.dumps(
                    result.final_output, ensure_ascii=False, indent=2
                )
                # 截断过长的输出
                if len(output_str) > 500:
                    print(f"      {output_str[:500]}...")
                else:
                    print(f"      {output_str}")

            return result

        except Exception as e:
            print(f"   ❌ 执行失败: {e}")
            import traceback

            traceback.print_exc()
            return None

    def show_storage_summary(self):
        """显示存储摘要"""
        print("\n📁 存储摘要...")
        print("-" * 50)

        # Agent 版本存储
        print("\n   Agent 版本存储:")
        version_path = Path(self.version_storage)
        if version_path.exists():
            for f in version_path.glob("*.json"):
                print(f"      - {f.name}")

        # YAML 导出
        yaml_path = version_path / "yaml"
        if yaml_path.exists():
            print("\n   YAML 导出:")
            for f in yaml_path.glob("*.yaml"):
                print(f"      - {f.name}")

        # 工作空间文件
        workspace_path = Path(self.workspace_base)
        if workspace_path.exists():
            print("\n   工作空间文件:")
            for f in workspace_path.rglob("*"):
                if f.is_file():
                    rel_path = f.relative_to(workspace_path)
                    print(f"      - {rel_path}")


async def run_full_test(
    model_name: str = "qwen-plus",
    task_company: str = "比亚迪",
    verbose: bool = False,
):
    """运行完整测试"""
    print("=" * 60)
    print("Meta Agent 完整测试")
    print("=" * 60)

    test = MetaAgentFullTest(model_name=model_name)

    try:
        # 1. 初始化
        await test.initialize()

        # 2. 创建 Agent 并持久化
        created_agents = await test.create_and_persist_agents()

        if not created_agents:
            print("\n❌ 没有成功创建 Agent，测试终止")
            return {"status": "failed", "error": "No agents created"}

        # 3. 生成工作流
        agent_ids = [a.agent_id for a in created_agents]
        workflow = await test.generate_workflow(agent_ids)

        if not workflow:
            print("\n❌ 工作流生成失败，测试终止")
            return {"status": "failed", "error": "Workflow generation failed"}

        # 4. 执行工作流
        task_input = {
            "task": f"对{task_company}进行投资分析",
            "company": task_company,
            "analysis_type": "comprehensive",
        }
        result = await test.execute_workflow(workflow, task_input)

        # 5. 显示存储摘要
        test.show_storage_summary()

        print("\n" + "=" * 60)
        print("测试完成")
        print("=" * 60)

        return {
            "status": (
                "success"
                if result and result.status.value == "completed"
                else "partial"
            ),
            "agents_created": len(created_agents),
            "workflow_id": workflow.workflow_id if workflow else None,
            "execution_status": result.status.value if result else None,
        }

    except Exception as e:
        print(f"\n❌ 测试失败: {e}")
        if verbose:
            import traceback

            traceback.print_exc()
        return {"status": "failed", "error": str(e)}


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Meta Agent 完整测试")
    parser.add_argument("-v", "--verbose", action="store_true", help="显示详细输出")
    parser.add_argument(
        "-m",
        "--model",
        type=str,
        default="qwen-plus",
        help="模型名称（如 qwen-plus, gpt-4o, deepseek-v3）",
    )
    parser.add_argument(
        "-c",
        "--company",
        type=str,
        default="比亚迪",
        help="分析目标公司",
    )

    args = parser.parse_args()
    result = asyncio.run(
        run_full_test(
            model_name=args.model,
            task_company=args.company,
            verbose=args.verbose,
        )
    )
    print(f"\n最终结果: {json.dumps(result, ensure_ascii=False, indent=2)}")
