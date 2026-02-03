"""
安全表达式评估器

提供基于 AST 的安全条件表达式评估，避免使用 eval() 的安全风险。

支持的操作:
- 比较运算: ==, !=, <, <=, >, >=
- 逻辑运算: and, or, not
- 属性访问: obj.field
- 字典访问: obj['key']
- 常量: 字符串、数字、布尔值、None
"""

import ast
import operator
from typing import Dict, Any, Optional, Union

from src.utils.logger import get_logger

logger = get_logger()


# 支持的比较运算符
COMPARE_OPS = {
    ast.Eq: operator.eq,
    ast.NotEq: operator.ne,
    ast.Lt: operator.lt,
    ast.LtE: operator.le,
    ast.Gt: operator.gt,
    ast.GtE: operator.ge,
    ast.Is: operator.is_,
    ast.IsNot: operator.is_not,
    ast.In: lambda a, b: a in b,
    ast.NotIn: lambda a, b: a not in b,
}

# 支持的二元运算符
BINARY_OPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.Mod: operator.mod,
}

# 支持的一元运算符
UNARY_OPS = {
    ast.Not: operator.not_,
    ast.UAdd: operator.pos,
    ast.USub: operator.neg,
}


class SafeEvalError(Exception):
    """安全评估错误"""

    pass


def safe_eval_condition(
    expression: str,
    context: Dict[str, Any],
    default: bool = False,
) -> bool:
    """
    安全地评估条件表达式

    Args:
        expression: 条件表达式字符串
        context: 上下文变量字典
        default: 评估失败时的默认值

    Returns:
        条件评估结果

    Examples:
        >>> context = {"score": 0.8, "status": "success"}
        >>> safe_eval_condition("score >= 0.7", context)
        True
        >>> safe_eval_condition("status == 'success'", context)
        True
        >>> safe_eval_condition("score > 0.9 and status == 'success'", context)
        False
    """
    if not expression or not expression.strip():
        return default

    try:
        tree = ast.parse(expression, mode="eval")
        result = _eval_node(tree.body, context)
        return bool(result)
    except SafeEvalError as e:
        logger.warning(f"条件评估安全检查失败: {e}, 表达式: {expression}")
        return default
    except Exception as e:
        logger.warning(f"条件评估失败: {e}, 表达式: {expression}")
        return default


def safe_eval_expression(
    expression: str,
    context: Dict[str, Any],
    default: Any = None,
) -> Any:
    """
    安全地评估表达式并返回结果

    Args:
        expression: 表达式字符串
        context: 上下文变量字典
        default: 评估失败时的默认值

    Returns:
        表达式评估结果
    """
    if not expression or not expression.strip():
        return default

    try:
        tree = ast.parse(expression, mode="eval")
        return _eval_node(tree.body, context)
    except SafeEvalError as e:
        logger.warning(f"表达式评估安全检查失败: {e}, 表达式: {expression}")
        return default
    except Exception as e:
        logger.warning(f"表达式评估失败: {e}, 表达式: {expression}")
        return default


def _eval_node(node: ast.AST, context: Dict[str, Any]) -> Any:
    """
    递归评估 AST 节点

    Args:
        node: AST 节点
        context: 上下文变量字典

    Returns:
        节点评估结果

    Raises:
        SafeEvalError: 不支持的节点类型
    """
    # 常量（Python 3.8+）
    if isinstance(node, ast.Constant):
        return node.value

    # 旧版常量（兼容性）
    if isinstance(node, ast.Num):
        return node.n
    if isinstance(node, ast.Str):
        return node.s
    if isinstance(node, ast.NameConstant):
        return node.value

    # 变量名
    if isinstance(node, ast.Name):
        name = node.id
        if name in context:
            return context[name]
        # 支持内置常量
        if name == "True":
            return True
        if name == "False":
            return False
        if name == "None":
            return None
        raise SafeEvalError(f"未知变量: {name}")

    # 属性访问 (obj.attr)
    if isinstance(node, ast.Attribute):
        value = _eval_node(node.value, context)
        if value is None:
            return None
        attr = node.attr

        # 安全检查：禁止访问私有属性
        if attr.startswith("_"):
            raise SafeEvalError(f"禁止访问私有属性: {attr}")

        # 优先尝试字典访问
        if isinstance(value, dict):
            return value.get(attr)

        # 然后尝试属性访问
        if hasattr(value, attr):
            result = getattr(value, attr)
            # 禁止返回可调用对象（方法）
            if callable(result) and not isinstance(result, type):
                raise SafeEvalError(f"禁止访问方法: {attr}")
            return result

        return None

    # 下标访问 (obj[key])
    if isinstance(node, ast.Subscript):
        value = _eval_node(node.value, context)
        if value is None:
            return None

        # 处理 slice
        if isinstance(node.slice, ast.Index):
            # Python 3.8 及更早版本
            key = _eval_node(node.slice.value, context)
        else:
            # Python 3.9+
            key = _eval_node(node.slice, context)

        if isinstance(value, dict):
            return value.get(key)
        if isinstance(value, (list, tuple)) and isinstance(key, int):
            try:
                return value[key]
            except IndexError:
                return None

        return None

    # 比较运算 (a == b, a < b, etc.)
    if isinstance(node, ast.Compare):
        left = _eval_node(node.left, context)

        for op, comparator in zip(node.ops, node.comparators):
            right = _eval_node(comparator, context)

            if type(op) not in COMPARE_OPS:
                raise SafeEvalError(f"不支持的比较运算符: {type(op).__name__}")

            try:
                if not COMPARE_OPS[type(op)](left, right):
                    return False
            except TypeError:
                # 类型不可比较
                return False

            left = right

        return True

    # 布尔运算 (and, or)
    if isinstance(node, ast.BoolOp):
        if isinstance(node.op, ast.And):
            for value in node.values:
                if not _eval_node(value, context):
                    return False
            return True
        elif isinstance(node.op, ast.Or):
            for value in node.values:
                if _eval_node(value, context):
                    return True
            return False
        else:
            raise SafeEvalError(f"不支持的布尔运算符: {type(node.op).__name__}")

    # 一元运算 (not, -, +)
    if isinstance(node, ast.UnaryOp):
        if type(node.op) not in UNARY_OPS:
            raise SafeEvalError(f"不支持的一元运算符: {type(node.op).__name__}")

        operand = _eval_node(node.operand, context)
        return UNARY_OPS[type(node.op)](operand)

    # 二元运算 (+, -, *, /, %)
    if isinstance(node, ast.BinOp):
        if type(node.op) not in BINARY_OPS:
            raise SafeEvalError(f"不支持的二元运算符: {type(node.op).__name__}")

        left = _eval_node(node.left, context)
        right = _eval_node(node.right, context)
        return BINARY_OPS[type(node.op)](left, right)

    # 条件表达式 (a if condition else b)
    if isinstance(node, ast.IfExp):
        condition = _eval_node(node.test, context)
        if condition:
            return _eval_node(node.body, context)
        else:
            return _eval_node(node.orelse, context)

    # 列表
    if isinstance(node, ast.List):
        return [_eval_node(elt, context) for elt in node.elts]

    # 元组
    if isinstance(node, ast.Tuple):
        return tuple(_eval_node(elt, context) for elt in node.elts)

    # 字典
    if isinstance(node, ast.Dict):
        return {
            _eval_node(k, context): _eval_node(v, context)
            for k, v in zip(node.keys, node.values)
            if k is not None
        }

    # 不支持的节点类型
    raise SafeEvalError(f"不支持的表达式类型: {type(node).__name__}")


def validate_expression(expression: str) -> tuple[bool, Optional[str]]:
    """
    验证表达式是否安全

    Args:
        expression: 表达式字符串

    Returns:
        (是否有效, 错误信息)
    """
    if not expression or not expression.strip():
        return True, None

    try:
        tree = ast.parse(expression, mode="eval")
        _validate_node(tree.body)
        return True, None
    except SyntaxError as e:
        return False, f"语法错误: {e}"
    except SafeEvalError as e:
        return False, str(e)
    except Exception as e:
        return False, f"验证失败: {e}"


def _validate_node(node: ast.AST) -> None:
    """
    验证 AST 节点是否安全

    Args:
        node: AST 节点

    Raises:
        SafeEvalError: 不安全的节点
    """
    # 禁止的节点类型
    forbidden = (
        ast.Call,  # 函数调用
        ast.Lambda,  # Lambda 表达式
        ast.FunctionDef,  # 函数定义
        ast.AsyncFunctionDef,
        ast.ClassDef,  # 类定义
        ast.Import,  # 导入
        ast.ImportFrom,
        ast.Global,  # 全局变量
        ast.Nonlocal,
        ast.Exec,  # exec（Python 2）
    )

    if isinstance(node, forbidden):
        raise SafeEvalError(f"禁止的表达式类型: {type(node).__name__}")

    # 递归验证子节点
    for child in ast.iter_child_nodes(node):
        _validate_node(child)


# 导出
__all__ = [
    "safe_eval_condition",
    "safe_eval_expression",
    "validate_expression",
    "SafeEvalError",
]
