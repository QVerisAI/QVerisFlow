"""
Agent Framework Examples CLI

命令行接口，用于快速运行各种示例。
"""

import argparse
import asyncio
import sys
from pathlib import Path
from typing import Dict, Callable, Any

# 确保 src 目录在 Python 路径中
# 这是因为 src 模块内部使用 `from utils.` 等相对导入
_root = Path(__file__).parent.parent
_src_path = str(_root / "src")
if _src_path not in sys.path:
    sys.path.insert(0, _src_path)
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))


# 示例注册表
EXAMPLES: Dict[str, Dict[str, Any]] = {
    "simple": {
        "name": "简单 Agent 示例",
        "description": "基本的 Agent 创建和执行，展示核心概念",
        "module": "examples.simple_agent",
        "function": "run_example",
    },
    "tools": {
        "name": "工具集成示例",
        "description": "自定义工具注册和执行，展示工具系统",
        "module": "examples.agent_with_tools",
        "function": "run_example",
    },
    "verification": {
        "name": "验证器示例",
        "description": "规则验证和 LLM 评判验证，展示验证系统",
        "module": "examples.agent_with_verification",
        "function": "run_example",
    },
    "workflow": {
        "name": "工作流示例",
        "description": "多 Agent 协作工作流，展示编排系统",
        "module": "examples.workflow_example",
        "function": "run_example",
    },
    "meta": {
        "name": "Meta Agent 示例",
        "description": "使用 Meta Agent 动态创建 Agent 和工作流",
        "module": "examples.meta_agent_example",
        "function": "run_example",
    },
    "ab": {
        "name": "A/B 测试示例",
        "description": "A/B 测试和 Prompt 优化，展示演化系统",
        "module": "examples.ab_testing_example",
        "function": "run_example",
    },
    "monitor": {
        "name": "性能监控示例",
        "description": "Agent 性能监控和告警，展示可观测性",
        "module": "examples.performance_monitoring",
        "function": "run_example",
    },
}


def list_examples():
    """列出所有可用示例"""
    print("\n" + "=" * 60)
    print("  Agent Framework Examples")
    print("=" * 60)
    print("\n可用示例:\n")

    for key, info in EXAMPLES.items():
        print(f"  {key:15} - {info['name']}")
        print(f"                  {info['description']}")
        print()

    print("用法:")
    print("  python -m examples <example_name>")
    print("\n示例:")
    print("  python -m examples simple")
    print("  python -m examples workflow")
    print("=" * 60 + "\n")


def run_example(example_name: str, verbose: bool = False):
    """运行指定的示例"""
    if example_name not in EXAMPLES:
        print(f"错误: 未知的示例 '{example_name}'")
        print(f"可用示例: {', '.join(EXAMPLES.keys())}")
        sys.exit(1)

    info = EXAMPLES[example_name]

    print("\n" + "=" * 60)
    print(f"  运行示例: {info['name']}")
    print(f"  描述: {info['description']}")
    print("=" * 60 + "\n")

    try:
        # 动态导入模块
        import importlib

        module = importlib.import_module(info["module"])
        func = getattr(module, info["function"])

        # 运行示例
        if asyncio.iscoroutinefunction(func):
            result = asyncio.run(func(verbose=verbose))
        else:
            result = func(verbose=verbose)

        print("\n" + "=" * 60)
        print("  示例运行完成")
        print("=" * 60 + "\n")

        return result

    except ImportError as e:
        print(f"错误: 无法导入模块 '{info['module']}'")
        print(f"详情: {e}")
        print("\n请确保已安装所有依赖: uv sync --all-extras")
        sys.exit(1)
    except AttributeError as e:
        print(f"错误: 模块中找不到函数 '{info['function']}'")
        print(f"详情: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"错误: 运行示例时发生异常")
        print(f"详情: {e}")
        if verbose:
            import traceback

            traceback.print_exc()
        sys.exit(1)


def create_parser() -> argparse.ArgumentParser:
    """创建命令行解析器"""
    parser = argparse.ArgumentParser(
        prog="examples",
        description="Agent Framework 示例运行器",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python -m examples --list           列出所有可用示例
  python -m examples simple           运行简单 Agent 示例
  python -m examples workflow         运行工作流示例
  python -m examples meta -v          运行 Meta Agent 示例（详细输出）
        """,
    )

    parser.add_argument(
        "example",
        nargs="?",
        default=None,
        choices=list(EXAMPLES.keys()),
        help="要运行的示例名称",
    )

    parser.add_argument(
        "-l",
        "--list",
        action="store_true",
        help="列出所有可用示例",
    )

    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="详细输出模式",
    )

    parser.add_argument(
        "--version",
        action="version",
        version="%(prog)s 1.0.0",
    )

    return parser


def main():
    """CLI 主入口"""
    parser = create_parser()
    args = parser.parse_args()

    if args.list or args.example is None:
        list_examples()
        return

    run_example(args.example, verbose=args.verbose)


if __name__ == "__main__":
    main()
