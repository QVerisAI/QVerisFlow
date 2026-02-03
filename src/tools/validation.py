"""
工具参数验证模块

使用 JSON Schema 验证工具输入参数的正确性。
确保在执行工具前参数符合预定义的格式要求。
"""

from typing import Dict, Any, Optional, List, Tuple
import json

from src.utils.logger import get_logger

logger = get_logger()

# 可选依赖：jsonschema
try:
    from jsonschema import Draft7Validator, ValidationError
    from jsonschema.exceptions import SchemaError

    JSONSCHEMA_AVAILABLE = True
except ImportError:
    JSONSCHEMA_AVAILABLE = False
    logger.debug("jsonschema 未安装，将使用简化验证")


class ToolValidationError(Exception):
    """工具参数验证错误"""

    def __init__(
        self,
        message: str,
        tool_id: str,
        errors: List[Dict[str, Any]],
        params: Dict[str, Any] = None,
    ):
        super().__init__(message)
        self.message = message
        self.tool_id = tool_id
        self.errors = errors
        self.params = params

    def __str__(self):
        error_lines = [self.message]
        for err in self.errors[:5]:
            error_lines.append(
                f"  - {err.get('path', 'root')}: {err.get('message', 'unknown error')}"
            )
        if len(self.errors) > 5:
            error_lines.append(f"  ... 还有 {len(self.errors) - 5} 个错误")
        return "\n".join(error_lines)


class ToolParameterValidator:
    """
    工具参数验证器

    使用 JSON Schema 验证工具的输入参数。

    使用示例:
    ```python
    validator = ToolParameterValidator()

    # 定义工具的 input_schema
    schema = {
        "type": "object",
        "properties": {
            "city": {"type": "string", "minLength": 1},
            "units": {"type": "string", "enum": ["metric", "imperial"]},
        },
        "required": ["city"]
    }

    # 验证参数
    params = {"city": "London", "units": "metric"}
    is_valid, errors = validator.validate(params, schema, "weather_tool")
    ```
    """

    def __init__(
        self,
        strict_mode: bool = True,
        coerce_types: bool = True,
        remove_extra: bool = False,
    ):
        """
        初始化参数验证器

        Args:
            strict_mode: 是否严格模式（任何验证错误都抛出异常）
            coerce_types: 是否尝试类型转换（如字符串数字转为数字）
            remove_extra: 是否移除额外的未定义属性
        """
        self.strict_mode = strict_mode
        self.coerce_types = coerce_types
        self.remove_extra = remove_extra

        # 缓存已编译的验证器
        self._validators: Dict[str, Any] = {}

    def validate(
        self,
        params: Dict[str, Any],
        schema: Dict[str, Any],
        tool_id: str = "unknown",
    ) -> Tuple[bool, List[Dict[str, Any]]]:
        """
        验证工具参数

        Args:
            params: 待验证的参数
            schema: JSON Schema 定义
            tool_id: 工具 ID（用于错误信息）

        Returns:
            (是否验证通过, 错误列表)
        """
        if not schema:
            return True, []

        # 类型转换预处理
        if self.coerce_types:
            params = self._coerce_types(params, schema)

        # 移除额外属性
        if self.remove_extra:
            params = self._remove_extra_properties(params, schema)

        if JSONSCHEMA_AVAILABLE:
            return self._validate_with_jsonschema(params, schema, tool_id)
        else:
            return self._validate_simple(params, schema, tool_id)

    def validate_and_raise(
        self,
        params: Dict[str, Any],
        schema: Dict[str, Any],
        tool_id: str = "unknown",
    ) -> Dict[str, Any]:
        """
        验证参数并在失败时抛出异常

        Args:
            params: 待验证的参数
            schema: JSON Schema 定义
            tool_id: 工具 ID

        Returns:
            验证（和可能转换）后的参数

        Raises:
            ToolValidationError: 验证失败时
        """
        # 类型转换预处理
        processed_params = params.copy()
        if self.coerce_types:
            processed_params = self._coerce_types(processed_params, schema)

        # 移除额外属性
        if self.remove_extra:
            processed_params = self._remove_extra_properties(processed_params, schema)

        is_valid, errors = self.validate(processed_params, schema, tool_id)

        if not is_valid:
            raise ToolValidationError(
                message=f"工具 {tool_id} 参数验证失败",
                tool_id=tool_id,
                errors=errors,
                params=params,
            )

        return processed_params

    def _validate_with_jsonschema(
        self,
        params: Dict[str, Any],
        schema: Dict[str, Any],
        tool_id: str,
    ) -> Tuple[bool, List[Dict[str, Any]]]:
        """使用 jsonschema 库验证"""
        # 获取或创建验证器
        schema_key = f"{tool_id}:{id(schema)}"
        if schema_key not in self._validators:
            try:
                self._validators[schema_key] = Draft7Validator(schema)
            except SchemaError as e:
                logger.warning(f"工具 {tool_id} 的 schema 无效: {e}")
                return True, []  # schema 无效时跳过验证

        validator = self._validators[schema_key]
        errors = list(validator.iter_errors(params))

        if not errors:
            return True, []

        error_details = []
        for error in errors:
            path = ".".join(str(p) for p in error.absolute_path) or "(root)"
            error_details.append(
                {
                    "path": path,
                    "message": error.message,
                    "validator": error.validator,
                    "schema_path": ".".join(str(p) for p in error.schema_path),
                }
            )

        return False, error_details

    def _validate_simple(
        self,
        params: Dict[str, Any],
        schema: Dict[str, Any],
        tool_id: str,
    ) -> Tuple[bool, List[Dict[str, Any]]]:
        """简化验证（不依赖 jsonschema）"""
        errors = []

        def validate_value(value: Any, prop_schema: Dict[str, Any], path: str):
            """递归验证单个值"""
            schema_type = prop_schema.get("type")

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
                            "path": path,
                            "message": f"期望类型 {schema_type}，实际类型 {type(value).__name__}",
                            "validator": "type",
                        }
                    )
                    return

            # 字符串验证
            if isinstance(value, str):
                min_length = prop_schema.get("minLength")
                max_length = prop_schema.get("maxLength")
                if min_length is not None and len(value) < min_length:
                    errors.append(
                        {
                            "path": path,
                            "message": f"字符串长度 {len(value)} 小于最小长度 {min_length}",
                            "validator": "minLength",
                        }
                    )
                if max_length is not None and len(value) > max_length:
                    errors.append(
                        {
                            "path": path,
                            "message": f"字符串长度 {len(value)} 大于最大长度 {max_length}",
                            "validator": "maxLength",
                        }
                    )

                # 枚举验证
                enum_values = prop_schema.get("enum")
                if enum_values and value not in enum_values:
                    errors.append(
                        {
                            "path": path,
                            "message": f"值 '{value}' 不在允许的选项中: {enum_values}",
                            "validator": "enum",
                        }
                    )

            # 数字验证
            if isinstance(value, (int, float)):
                minimum = prop_schema.get("minimum")
                maximum = prop_schema.get("maximum")
                if minimum is not None and value < minimum:
                    errors.append(
                        {
                            "path": path,
                            "message": f"值 {value} 小于最小值 {minimum}",
                            "validator": "minimum",
                        }
                    )
                if maximum is not None and value > maximum:
                    errors.append(
                        {
                            "path": path,
                            "message": f"值 {value} 大于最大值 {maximum}",
                            "validator": "maximum",
                        }
                    )

            # 对象验证
            if isinstance(value, dict) and schema_type == "object":
                properties = prop_schema.get("properties", {})
                required = prop_schema.get("required", [])

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
                for prop_name, prop_def in properties.items():
                    if prop_name in value:
                        new_path = f"{path}.{prop_name}" if path else prop_name
                        validate_value(value[prop_name], prop_def, new_path)

            # 数组验证
            if isinstance(value, list) and schema_type == "array":
                min_items = prop_schema.get("minItems")
                max_items = prop_schema.get("maxItems")
                if min_items is not None and len(value) < min_items:
                    errors.append(
                        {
                            "path": path,
                            "message": f"数组长度 {len(value)} 小于最小长度 {min_items}",
                            "validator": "minItems",
                        }
                    )
                if max_items is not None and len(value) > max_items:
                    errors.append(
                        {
                            "path": path,
                            "message": f"数组长度 {len(value)} 大于最大长度 {max_items}",
                            "validator": "maxItems",
                        }
                    )

                items_schema = prop_schema.get("items")
                if items_schema:
                    for i, item in enumerate(value):
                        validate_value(item, items_schema, f"{path}[{i}]")

        # 顶层验证
        schema_type = schema.get("type", "object")
        if schema_type == "object":
            properties = schema.get("properties", {})
            required = schema.get("required", [])

            # 检查必需字段
            for req in required:
                if req not in params:
                    errors.append(
                        {
                            "path": req,
                            "message": f"缺少必需参数 '{req}'",
                            "validator": "required",
                        }
                    )

            # 验证各属性
            for prop_name, prop_def in properties.items():
                if prop_name in params:
                    validate_value(params[prop_name], prop_def, prop_name)
        else:
            validate_value(params, schema, "")

        return len(errors) == 0, errors

    def _coerce_types(
        self,
        params: Dict[str, Any],
        schema: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        尝试将参数转换为正确的类型

        例如：字符串 "123" -> 整数 123
        """
        if not isinstance(params, dict):
            return params

        result = params.copy()
        properties = schema.get("properties", {})

        for prop_name, prop_schema in properties.items():
            if prop_name not in result:
                continue

            value = result[prop_name]
            expected_type = prop_schema.get("type")

            if expected_type and isinstance(value, str):
                try:
                    if expected_type == "integer":
                        result[prop_name] = int(value)
                    elif expected_type == "number":
                        result[prop_name] = float(value)
                    elif expected_type == "boolean":
                        if value.lower() in ("true", "1", "yes"):
                            result[prop_name] = True
                        elif value.lower() in ("false", "0", "no"):
                            result[prop_name] = False
                    elif expected_type == "array" and value.startswith("["):
                        result[prop_name] = json.loads(value)
                    elif expected_type == "object" and value.startswith("{"):
                        result[prop_name] = json.loads(value)
                except (ValueError, json.JSONDecodeError):
                    pass  # 保留原值

            # 递归处理嵌套对象
            if expected_type == "object" and isinstance(result[prop_name], dict):
                result[prop_name] = self._coerce_types(result[prop_name], prop_schema)

        return result

    def _remove_extra_properties(
        self,
        params: Dict[str, Any],
        schema: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        移除 schema 中未定义的额外属性
        """
        if not isinstance(params, dict):
            return params

        properties = schema.get("properties", {})
        allow_additional = schema.get("additionalProperties", True)

        if allow_additional is True:
            return params

        result = {}
        for key, value in params.items():
            if key in properties:
                prop_schema = properties[key]
                if prop_schema.get("type") == "object" and isinstance(value, dict):
                    result[key] = self._remove_extra_properties(value, prop_schema)
                else:
                    result[key] = value
            elif allow_additional:
                result[key] = value

        return result


# 全局验证器实例
_default_validator: Optional[ToolParameterValidator] = None


def get_default_validator() -> ToolParameterValidator:
    """获取默认的参数验证器"""
    global _default_validator
    if _default_validator is None:
        _default_validator = ToolParameterValidator()
    return _default_validator


def validate_tool_params(
    params: Dict[str, Any],
    schema: Dict[str, Any],
    tool_id: str = "unknown",
) -> Tuple[bool, List[Dict[str, Any]]]:
    """
    便捷函数：验证工具参数

    Args:
        params: 待验证的参数
        schema: JSON Schema 定义
        tool_id: 工具 ID

    Returns:
        (是否验证通过, 错误列表)
    """
    return get_default_validator().validate(params, schema, tool_id)


# 导出
__all__ = [
    "ToolParameterValidator",
    "ToolValidationError",
    "get_default_validator",
    "validate_tool_params",
]
