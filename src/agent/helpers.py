import inspect
from typing import Any, get_args, get_origin, get_type_hints


def func_input_schema(func) -> dict[str, Any]:
    
    try:
        hints = get_type_hints(func)
    except Exception:
        hints = {
            name: param.annotation
            for name, param in inspect.signature(func).parameters.items()
            if param.annotation is not inspect.Parameter.empty
        }
    sig = inspect.signature(func)
    
    props = {}
    required = []

    for name, param in sig.parameters.items():
        if name in ("self", "ctx", "context"):
            continue
        
        prop: dict[str, Any] = {}
        hint = hints.get(name)
        origin = get_origin(hint)
        
        # 型判定
        if hint is str:
            prop["type"] = "string"
        elif hint is int:
            prop["type"] = "integer"
        elif hint is float:
            prop["type"] = "number"
        elif hint is bool:
            prop["type"] = "boolean"
        elif hint is list or origin is list:
            prop["type"] = "array"
            item_schema = _get_array_item_schema(hint)
            if item_schema:
                prop["items"] = item_schema
        elif hint is not None and hasattr(hint, "model_json_schema"):
            prop = hint.model_json_schema()
        else:
            prop["type"] = "string"
        
        prop["description"] = f"Parameter: {name}"
        props[name] = prop

        if param.default is inspect.Parameter.empty:
            required.append(name)
    
    schema = {
        "type" : "object",
        "properties" : props
    }

    if required:
        schema["required"] = required
    
    return schema

def _get_array_item_schema(hint: Any) -> dict[str, Any]:
    args = get_args(hint)
    if args:
        item_type = args[0]

        if item_type is str:
            return {"type": "string"}
        elif item_type is int:
            return {"type": "integer"}
        elif item_type is float:
            return {"type": "number"}
        elif item_type is bool:
            return {"type": "boolean"}
        elif hasattr(item_type, "model_json_schema"):
            return item_type.model_json_schema()

    return {}


def format_tool_def(name: str, desc: str, params: dict) -> dict:
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": desc,
            "parameters": params
        }
    }


def tool_exec(tool_box: dict, tool_call) -> str:
    func_name = tool_call.name
    if func_name not in tool_box:
        return f"Error: Unknown tool '{func_name}'"

    try:
        result = tool_box[func_name](**tool_call.args)
        return str(result)
    except Exception as e:
        return f"Error executing {func_name}: {str(e)}"


def remove_code_fence(text: str) -> str:
    if "\n" in text:
        return text.split("\n", 1)[1]

    return text[3:]
