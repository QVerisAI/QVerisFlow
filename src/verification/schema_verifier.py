"""
Schema 验证器

使用 JSON Schema 对 Agent 输出进行结构验证。
确保输出符合预定义的数据结构和格式要求。
"""

from typing import Dict, Any, Optional, List, Union
import json

from .base import BaseVerifier, VerificationResult
from src.utils.logger import get_logger

logger = get_logger()

# 可选依赖：jsonschema
try:
    from jsonschema import validate, ValidationError, Draft7Validator
    from jsonschema.exceptions import SchemaError

    JSONSCHEMA_AVAILABLE = True
except ImportError:
    JSONSCHEMA_AVAILABLE = False
    logger.debug("jsonschema 未安装，SchemaVerifier 将使用简化验证")


class SchemaVerifier(BaseVerifier):
    """
    基于 JSON Schema 的输出验证器

    使用 JSON Schema 验证 Agent 输出的结构正确性，支持：
    - 完整的 JSON Schema Draft-7 规范
    - 类型验证
    - 必需字段检查
    - 格式验证（email、uri、date-time 等）
    - 自定义验证规则

    用法:
        schema = {
            "type": "object",
            "properties": {
                "name": {"type": "string", "minLength": 1},
                "age": {"type": "integer", "minimum": 0},
                "email": {"type": "string", "format": "email"},
            },
            "required": ["name", "age"],
        }

        verifier = SchemaVerifier(schema)
        result = await verifier.verify({"name": "Alice", "age": 30})
    """

    def __init__(
        self,
        schema: Dict[str, Any],
        allow_additional_properties: bool = True,
        strict_mode: bool = False,
        error_limit: int = 10,
    ):
        """
        初始化 Schema 验证器

        Args:
            schema: JSON Schema 定义
            allow_additional_properties: 是否允许额外属性（默认 True）
            strict_mode: 严格模式，任何验证错误都导致失败
            error_limit: 报告的最大错误数量
        """
        self.schema = schema.copy()
        self.strict_mode = strict_mode
        self.error_limit = error_limit

        # 处理额外属性设置
        if (
            not allow_additional_properties
            and "additionalProperties" not in self.schema
        ):
            self.schema["additionalProperties"] = False

        # 验证 schema 本身
        if JSONSCHEMA_AVAILABLE:
            try:
                Draft7Validator.check_schema(self.schema)
            except SchemaError as e:
                raise ValueError(f"无效的 JSON Schema: {e}")

    async def verify(
        self,
        output: Any,
        context: Optional[Dict[str, Any]] = None,
    ) -> VerificationResult:
        """
        验证输出是否符合 Schema

        Args:
            output: 待验证的输出
            context: 验证上下文（可选）

        Returns:
            验证结果
        """
        context = context or {}

        # 如果输出是字符串，尝试解析为 JSON
        if isinstance(output, str):
            try:
                output = json.loads(output)
            except json.JSONDecodeError as e:
                return VerificationResult(
                    passed=False,
                    score=0.0,
                    feedback=f"输出不是有效的 JSON: {e}",
                    details={
                        "error_type": "json_parse_error",
                        "error_message": str(e),
                        "verifier_name": "schema",
                    },
                )

        if JSONSCHEMA_AVAILABLE:
            return self._validate_with_jsonschema(output, context)
        else:
            return self._validate_simple(output, context)

    def _validate_with_jsonschema(
        self,
        output: Any,
        context: Dict[str, Any],
    ) -> VerificationResult:
        """使用 jsonschema 库进行验证"""
        validator = Draft7Validator(self.schema)
        errors = list(validator.iter_errors(output))

        if not errors:
            return VerificationResult(
                passed=True,
                score=1.0,
                feedback="Schema 验证通过",
                details={
                    "verifier_name": "schema",
                    "errors": [],
                },
            )

        # 收集错误信息
        error_details = []
        for i, error in enumerate(errors[: self.error_limit]):
            error_path = ".".join(str(p) for p in error.absolute_path) or "(root)"
            error_details.append(
                {
                    "path": error_path,
                    "message": error.message,
                    "validator": error.validator,
                    "value": (
                        error.instance
                        if not isinstance(error.instance, (dict, list))
                        or len(str(error.instance)) < 100
                        else "(complex value)"
                    ),
                }
            )

        # 计算分数（基于错误数量）
        total_properties = self._count_schema_properties(self.schema)
        error_count = len(errors)
        score = max(0.0, 1.0 - (error_count / max(total_properties, 1)))

        # 生成反馈
        error_messages = [f"- {e['path']}: {e['message']}" for e in error_details[:5]]
        feedback = f"Schema 验证失败，发现 {error_count} 个错误:\n" + "\n".join(
            error_messages
        )
        if error_count > 5:
            feedback += f"\n... 还有 {error_count - 5} 个错误"

        return VerificationResult(
            passed=False if self.strict_mode else score >= 0.5,
            score=score,
            feedback=feedback,
            details={
                "verifier_name": "schema",
                "error_count": error_count,
                "errors": error_details,
                "total_errors": len(errors),
            },
        )

    def _validate_simple(
        self,
        output: Any,
        context: Dict[str, Any],
    ) -> VerificationResult:
        """简化验证（不依赖 jsonschema）"""
        errors = []

        def validate_value(value: Any, schema: Dict[str, Any], path: str = ""):
            """递归验证值"""
            schema_type = schema.get("type")

            # 类型检查
            if schema_type:
                type_map = {
                    "string": str,
                    "integer": int,
                    "number": (int, float),
                    "boolean": bool,
                    "array": list,
                    "object": dict,
                    "null": type(None),
                }

                expected_type = type_map.get(schema_type)
                if expected_type and not isinstance(value, expected_type):
                    errors.append(
                        {
                            "path": path or "(root)",
                            "message": f"期望类型 {schema_type}，实际类型 {type(value).__name__}",
                            "validator": "type",
                        }
                    )
                    return

            # 对象验证
            if isinstance(value, dict) and schema_type == "object":
                properties = schema.get("properties", {})
                required = schema.get("required", [])

                # 检查必需字段
                for req in required:
                    if req not in value:
                        errors.append(
                            {
                                "path": f"{path}.{req}" if path else req,
                                "message": f"缺少必需字段 '{req}'",
                                "validator": "required",
                            }
                        )

                # 递归验证属性
                for prop, prop_schema in properties.items():
                    if prop in value:
                        validate_value(
                            value[prop], prop_schema, f"{path}.{prop}" if path else prop
                        )

            # 数组验证
            elif isinstance(value, list) and schema_type == "array":
                items_schema = schema.get("items")
                if items_schema:
                    for i, item in enumerate(value):
                        validate_value(item, items_schema, f"{path}[{i}]")

        validate_value(output, self.schema)

        if not errors:
            return VerificationResult(
                passed=True,
                score=1.0,
                feedback="Schema 验证通过（简化模式）",
                details={
                    "verifier_name": "schema",
                    "mode": "simple",
                    "errors": [],
                },
            )

        error_count = len(errors)
        error_messages = [f"- {e['path']}: {e['message']}" for e in errors[:5]]
        feedback = f"Schema 验证失败，发现 {error_count} 个错误:\n" + "\n".join(
            error_messages
        )

        return VerificationResult(
            passed=False,
            score=max(0.0, 1.0 - error_count * 0.2),
            feedback=feedback,
            details={
                "verifier_name": "schema",
                "mode": "simple",
                "error_count": error_count,
                "errors": errors,
            },
        )

    def _count_schema_properties(self, schema: Dict[str, Any]) -> int:
        """统计 Schema 中的属性数量"""
        count = 0

        if "properties" in schema:
            count += len(schema["properties"])
            for prop_schema in schema["properties"].values():
                count += self._count_schema_properties(prop_schema)

        if "items" in schema:
            count += self._count_schema_properties(schema["items"])

        return max(count, 1)


class TypedSchemaVerifier(SchemaVerifier):
    """
    类型化 Schema 验证器

    提供常见数据结构的快捷验证方法。
    """

    @classmethod
    def for_list(
        cls,
        item_schema: Dict[str, Any],
        min_items: int = 0,
        max_items: int = None,
        **kwargs,
    ) -> "TypedSchemaVerifier":
        """
        创建列表验证器

        Args:
            item_schema: 列表项的 Schema
            min_items: 最小项数
            max_items: 最大项数
        """
        schema = {
            "type": "array",
            "items": item_schema,
            "minItems": min_items,
        }
        if max_items is not None:
            schema["maxItems"] = max_items

        return cls(schema, **kwargs)

    @classmethod
    def for_dict(
        cls,
        properties: Dict[str, Dict[str, Any]],
        required: List[str] = None,
        **kwargs,
    ) -> "TypedSchemaVerifier":
        """
        创建字典验证器

        Args:
            properties: 属性定义
            required: 必需属性列表
        """
        schema = {
            "type": "object",
            "properties": properties,
        }
        if required:
            schema["required"] = required

        return cls(schema, **kwargs)

    @classmethod
    def for_string(
        cls,
        min_length: int = None,
        max_length: int = None,
        pattern: str = None,
        format: str = None,
        **kwargs,
    ) -> "TypedSchemaVerifier":
        """
        创建字符串验证器

        Args:
            min_length: 最小长度
            max_length: 最大长度
            pattern: 正则表达式模式
            format: 格式（email、uri、date-time 等）
        """
        schema = {"type": "string"}

        if min_length is not None:
            schema["minLength"] = min_length
        if max_length is not None:
            schema["maxLength"] = max_length
        if pattern:
            schema["pattern"] = pattern
        if format:
            schema["format"] = format

        return cls(schema, **kwargs)


# 预定义的常见 Schema
COMMON_SCHEMAS = {
    "json_response": {
        "type": "object",
        "properties": {
            "success": {"type": "boolean"},
            "data": {},
            "message": {"type": "string"},
        },
        "required": ["success"],
    },
    "analysis_result": {
        "type": "object",
        "properties": {
            "summary": {"type": "string"},
            "findings": {"type": "array", "items": {"type": "string"}},
            "recommendations": {"type": "array", "items": {"type": "string"}},
            "confidence": {"type": "number", "minimum": 0, "maximum": 1},
        },
        "required": ["summary", "findings"],
    },
    "task_result": {
        "type": "object",
        "properties": {
            "status": {"type": "string", "enum": ["success", "failed", "partial"]},
            "result": {},
            "error": {"type": "string"},
            "metrics": {"type": "object"},
        },
        "required": ["status"],
    },
}


def get_common_schema(name: str) -> Dict[str, Any]:
    """获取预定义的常见 Schema"""
    if name not in COMMON_SCHEMAS:
        raise ValueError(
            f"未知的 Schema 名称: {name}，可用: {list(COMMON_SCHEMAS.keys())}"
        )
    return COMMON_SCHEMAS[name].copy()


# 导出
__all__ = [
    "SchemaVerifier",
    "TypedSchemaVerifier",
    "COMMON_SCHEMAS",
    "get_common_schema",
]
