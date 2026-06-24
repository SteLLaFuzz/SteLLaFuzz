import json
import os

from typing import Dict, List, Literal, Optional, Set, Tuple

from openai import OpenAI
from pydantic import BaseModel, Field

from utility.utility import LLM_RETRY, LLM_RESULT_DIR, MODEL

PROTOCOL_SPECIALIZED_STRUCTURE_OUTPUT_DIR = "protocol_specialized_structure_results"
MAX_SCHEMA_RETRY = 3

FieldType = Literal[
    "uint8",
    "uint16",
    "uint24",
    "uint32",
    "integer",
    "boolean",
    "bytes",
    "string",
    "ascii_string",
    "utf8_string",
    "name_list",
]

MessageRole = Literal["request", "response", "bidirectional", "unknown"]
SchemaKind = Literal["binary", "text", "mixed", "unknown"]
SyntaxRole = Literal["start_line", "header", "body", "delimiter", "token"]


class SchemaField(BaseModel):
    name: str
    type: FieldType
    required: bool
    description: str
    constraints: List[str] = Field(default_factory=list)

    fixed_byte_length: Optional[int] = None
    length_from: Optional[str] = None
    fixed_value: Optional[str] = None

    syntax_role: Optional[SyntaxRole] = None
    format: Optional[str] = None
    delimiter: Optional[str] = None
    encoding: Optional[str] = None
    line_terminated_by: Optional[str] = None
    repeatable: Optional[bool] = None
    position: Optional[int] = None


class SchemaLayer(BaseModel):
    name: str
    description: str
    fields: List[SchemaField]


class CanonicalStructuredOutput(BaseModel):
    protocol: str
    message_type: str
    code: Optional[str] = None
    type_description: str
    message_role: MessageRole
    schema_kind: SchemaKind
    layers: List[SchemaLayer]
    references: List[str]
    notes: Optional[str] = None


PROTOCOL_SPECIALIZED_STRUCTURE_PROMPT = """\
You are a network protocol expert. Produce a canonical message schema for one protocol message.

You are given:
- protocol: [PROTOCOL]
- target implementation: [TARGET_IMPLEMENTATION]
- message type: [TYPE]
- code: [CODE]
- message description: [DESCRIPTION]

Return a canonical schema using only the structured output fields provided by the tool.

General requirements:
1. Be protocol-agnostic in reasoning style. Do not rely on benchmark names, implementation names, or target-specific examples.
   You may use the target implementation only as a secondary disambiguation hint.
2. Prefer a machine-usable schema over prose. Model wire-visible structure, field order, and message syntax.
3. Use `schema_kind`:
   - `text` for line-oriented or header-oriented messages
   - `binary` for length-prefixed or binary field messages
   - `mixed` only if both textual and binary layers are essential
   - `unknown` only if the official structure cannot be inferred
4. Use one or more `layers` to separate envelope, payload, headers, handshake bodies, or similar structural regions when helpful.
5. Each field must include:
   - `name`
   - `type`
   - `required`
   - `description`
   - `constraints`
6. Use only these field types:
   - uint8, uint16, uint24, uint32, integer, boolean, bytes, string, ascii_string, utf8_string, name_list
7. Use binary-oriented attributes only when appropriate:
   - `fixed_byte_length`
   - `length_from`
   - `fixed_value`
8. Use text-oriented attributes only when appropriate:
   - `syntax_role`
   - `format`
   - `delimiter`
   - `encoding`
   - `line_terminated_by`
   - `repeatable`
   - `position`
9. Do not add free-form reasoning fields. Put brief caveats or unresolved ambiguity in `notes`.
10. Prefer explicit field order and structural decomposition over generic "header blob" or "body blob" fields.
11. Treat the protocol specification as the primary authority.
12. Use the target implementation only to choose among protocol-compatible structural variants that are wire-visible in practice.
13. Do not invent implementation-specific fields unless they are still protocol-compatible and wire-visible.

Additional guidance:
- If a textual request has a start line, model it as a field with `syntax_role: start_line`.
- If a message includes repeated headers or repeated vector elements, express the visible count or repetition hint in `constraints`.
- If a field has a fixed protocol code, set `fixed_value`.
- If a variable-length field is governed by another field, use `length_from`.
- If exact low-level details are unclear, keep the schema conservative and record uncertainty in `notes`.

Produce the final canonical schema now.
"""

VALIDATION_RETRY_PROMPT = """\

Your previous schema was rejected by a structural validator.
You must fix the schema and return a fully corrected schema in the same DSL.

Validation errors:
[VALIDATION_ERRORS]

Correction requirements:
1. Keep the same protocol and message type.
2. Fix the listed invalid expressions directly.
3. If a field references another field, that referenced field must exist.
4. If `schema_kind` is `binary`, do not use text-only attributes such as `syntax_role`, `format`, `delimiter`, `encoding`, `line_terminated_by`, or `position`.
5. If `schema_kind` is `text`, include visible textual structure such as a start line or headers when applicable.
6. `references` must contain at least one authoritative source string.
7. Preserve valid parts of the schema where possible, but prefer correctness over minimal edits.
"""


class ValidationIssue(BaseModel):
    path: str
    message: str
    observed: str
    expected: str


def _collect_field_names(schema: CanonicalStructuredOutput) -> Tuple[Dict[str, str], List[ValidationIssue]]:
    field_paths: Dict[str, str] = {}
    issues: List[ValidationIssue] = []
    for layer_index, layer in enumerate(schema.layers):
        for field_index, field in enumerate(layer.fields):
            path = f"layers[{layer_index}].fields[{field_index}]"
            if field.name in field_paths:
                issues.append(
                    ValidationIssue(
                        path=f"{path}.name",
                        message="Duplicate field name detected.",
                        observed=field.name,
                        expected="Use a field name that is unique across the schema.",
                    )
                )
            else:
                field_paths[field.name] = path
    return field_paths, issues


def _detect_reference_cycles(edges: Dict[str, str]) -> List[Tuple[str, str]]:
    visited: Set[str] = set()
    active: Set[str] = set()
    cycles: List[Tuple[str, str]] = []

    def visit(node: str) -> None:
        if node in active:
            cycles.append((node, edges[node]))
            return
        if node in visited or node not in edges:
            return
        visited.add(node)
        active.add(node)
        visit(edges[node])
        active.remove(node)

    for source in edges:
        visit(source)
    return cycles


def validate_specialized_schema(schema: CanonicalStructuredOutput) -> List[ValidationIssue]:
    issues: List[ValidationIssue] = []
    length_field_types = {"uint8", "uint16", "uint24", "uint32", "integer"}

    if not schema.references:
        issues.append(
            ValidationIssue(
                path="references",
                message="Missing authoritative references.",
                observed="[]",
                expected="Add at least one RFC, specification, or official documentation reference.",
            )
        )

    if not schema.layers:
        issues.append(
            ValidationIssue(
                path="layers",
                message="Schema has no layers.",
                observed="[]",
                expected="Add at least one non-empty layer.",
            )
        )
        return issues

    field_paths, duplicate_issues = _collect_field_names(schema)
    issues.extend(duplicate_issues)

    layer_names: Set[str] = set()
    length_edges: Dict[str, str] = {}
    text_structure_count = 0

    for layer_index, layer in enumerate(schema.layers):
        layer_path = f"layers[{layer_index}]"
        if layer.name in layer_names:
            issues.append(
                ValidationIssue(
                    path=f"{layer_path}.name",
                    message="Duplicate layer name detected.",
                    observed=layer.name,
                    expected="Use a layer name that is unique across the schema.",
                )
            )
        else:
            layer_names.add(layer.name)

        if not layer.fields:
            issues.append(
                ValidationIssue(
                    path=f"{layer_path}.fields",
                    message="Layer has no fields.",
                    observed="[]",
                    expected="Add at least one field to each layer.",
                )
            )
            continue

        for field_index, field in enumerate(layer.fields):
            field_path = f"{layer_path}.fields[{field_index}]"

            if field.fixed_byte_length is not None and field.fixed_byte_length <= 0:
                issues.append(
                    ValidationIssue(
                        path=f"{field_path}.fixed_byte_length",
                        message="Invalid fixed byte length.",
                        observed=str(field.fixed_byte_length),
                        expected="Use a positive integer or null.",
                    )
                )

            if field.fixed_byte_length is not None and field.length_from is not None:
                issues.append(
                    ValidationIssue(
                        path=field_path,
                        message="Field uses both fixed_byte_length and length_from.",
                        observed=json.dumps(
                            {
                                "fixed_byte_length": field.fixed_byte_length,
                                "length_from": field.length_from,
                            },
                            ensure_ascii=False,
                        ),
                        expected="Use only one of fixed_byte_length or length_from for a single field.",
                    )
                )

            if field.length_from is not None:
                if field.length_from not in field_paths:
                    issues.append(
                        ValidationIssue(
                            path=f"{field_path}.length_from",
                            message="length_from references a missing field.",
                            observed=field.length_from,
                            expected="Reference an existing field name in the schema.",
                        )
                    )
                elif field.length_from == field.name:
                    issues.append(
                        ValidationIssue(
                            path=f"{field_path}.length_from",
                            message="Field self-references through length_from.",
                            observed=field.length_from,
                            expected="Reference a different existing length field.",
                        )
                    )
                else:
                    target_layer_path, target_field_path = None, None
                    target_field = None
                    for candidate_layer_index, candidate_layer in enumerate(schema.layers):
                        for candidate_field_index, candidate_field in enumerate(candidate_layer.fields):
                            if candidate_field.name == field.length_from:
                                target_layer_path = f"layers[{candidate_layer_index}]"
                                target_field_path = f"{target_layer_path}.fields[{candidate_field_index}]"
                                target_field = candidate_field
                                break
                        if target_field is not None:
                            break

                    if target_field is None:
                        issues.append(
                            ValidationIssue(
                                path=f"{field_path}.length_from",
                                message="length_from target could not be resolved after name lookup.",
                                observed=field.length_from,
                                expected="Reference an existing numeric length field.",
                            )
                        )
                    elif target_field.type not in length_field_types:
                        issues.append(
                            ValidationIssue(
                                path=f"{field_path}.length_from",
                                message="length_from must reference a numeric length field.",
                                observed=json.dumps(
                                    {
                                        "referenced_field": field.length_from,
                                        "referenced_type": target_field.type,
                                        "referenced_path": target_field_path,
                                    },
                                    ensure_ascii=False,
                                ),
                                expected="Reference a field whose type is one of uint8, uint16, uint24, uint32, or integer.",
                            )
                        )
                    elif target_field.syntax_role in {"start_line", "header", "body", "delimiter", "token"}:
                        issues.append(
                            ValidationIssue(
                                path=f"{field_path}.length_from",
                                message="length_from references a text-structure field instead of a dedicated length field.",
                                observed=json.dumps(
                                    {
                                        "referenced_field": field.length_from,
                                        "referenced_syntax_role": target_field.syntax_role,
                                        "referenced_path": target_field_path,
                                    },
                                    ensure_ascii=False,
                                ),
                                expected="Reference a dedicated numeric length field, not a textual structure field.",
                            )
                        )
                    else:
                        length_edges[field.name] = field.length_from

            text_attrs = {
                "syntax_role": field.syntax_role,
                "format": field.format,
                "delimiter": field.delimiter,
                "encoding": field.encoding,
                "line_terminated_by": field.line_terminated_by,
                "position": field.position,
            }
            has_text_attr = any(value is not None for value in text_attrs.values())
            if field.syntax_role in {"start_line", "header"}:
                text_structure_count += 1

            if schema.schema_kind == "binary" and has_text_attr:
                issues.append(
                    ValidationIssue(
                        path=field_path,
                        message="Binary schema uses text-only attributes.",
                        observed=json.dumps(text_attrs, ensure_ascii=False),
                        expected="Remove text-only attributes from binary schemas.",
                    )
                )

            if schema.schema_kind == "text":
                if field.fixed_byte_length is not None and field.syntax_role is None:
                    issues.append(
                        ValidationIssue(
                            path=field_path,
                            message="Text schema field uses binary-style fixed length without text structure metadata.",
                            observed=json.dumps(
                                {
                                    "fixed_byte_length": field.fixed_byte_length,
                                    "syntax_role": field.syntax_role,
                                },
                                ensure_ascii=False,
                            ),
                            expected="Either add appropriate text structure metadata or remove binary-style fixed sizing.",
                        )
                    )
                if field.syntax_role == "header" and field.delimiter is None:
                    issues.append(
                        ValidationIssue(
                            path=field_path,
                            message="Header field is missing a header delimiter.",
                            observed=json.dumps({"delimiter": field.delimiter}, ensure_ascii=False),
                            expected="Add a visible header delimiter such as ': ' or an equivalent textual separator.",
                        )
                    )

    for source, target in _detect_reference_cycles(length_edges):
        issues.append(
            ValidationIssue(
                path=field_paths.get(source, source),
                message="Detected a cycle in length_from references.",
                observed=f"{source} -> {target}",
                expected="Use an acyclic set of length_from references.",
            )
        )

    if schema.schema_kind == "text" and text_structure_count == 0:
        issues.append(
            ValidationIssue(
                path="layers",
                message="Text schema has no visible textual structure markers.",
                observed="No field with syntax_role start_line or header.",
                expected="Add at least one field with syntax_role start_line or header.",
            )
        )

    return issues


def _format_validation_issues(issues: List[ValidationIssue]) -> str:
    lines: List[str] = []
    for index, issue in enumerate(issues, start=1):
        lines.append(
            "\n".join(
                [
                    f"{index}. path: {issue.path}",
                    f"   error: {issue.message}",
                    f"   wrong expression: {issue.observed}",
                    f"   required fix: {issue.expected}",
                ]
            )
        )
    return "\n".join(lines)


def using_llm(prompt: str) -> CanonicalStructuredOutput:
    client = OpenAI()
    try:
        completion = client.beta.chat.completions.parse(
            model=MODEL,
            temperature=0.1,
            messages=[
                {"role": "system", "content": "You produce canonical network message schemas in a constrained DSL."},
                {"role": "user", "content": prompt},
            ],
            response_format=CanonicalStructuredOutput,
            timeout=30,
        )
        response = completion.choices[0].message.parsed

        index = 0
        os.makedirs(os.path.join(LLM_RESULT_DIR, "2_specialized_structures"), exist_ok=True)
        while os.path.exists(os.path.join(LLM_RESULT_DIR, "2_specialized_structures", f"response_{index}.json")):
            index += 1
        protocol_file = os.path.join(LLM_RESULT_DIR, "2_specialized_structures", f"response_{index}.json")
        with open(protocol_file, "w", encoding="utf-8") as f:
            json.dump(completion.model_dump(), f, indent=4, ensure_ascii=False)
        return response
    except Exception as e:
        print(f"Error processing protocol: {e}")
        return None


def get_specialized_structure(protocol: str, message_type: dict) -> dict:
    target_implementation = os.getenv("STELLAFUZZ_TARGET_NAME", "unknown")
    base_prompt = (
        PROTOCOL_SPECIALIZED_STRUCTURE_PROMPT.replace("[PROTOCOL]", protocol)
        .replace("[TARGET_IMPLEMENTATION]", target_implementation)
        .replace("[TYPE]", message_type["name"])
        .replace("[CODE]", message_type["code"] if message_type["code"] else "NULL")
        .replace("[DESCRIPTION]", message_type["description"])
    )

    retry_suffix = ""
    response = None
    issues: List[ValidationIssue] = []
    for attempt in range(max(LLM_RETRY, MAX_SCHEMA_RETRY)):
        response = using_llm(base_prompt + retry_suffix)
        if response is not None:
            issues = validate_specialized_schema(response)
            if not issues:
                return response.model_dump()
            if attempt == max(LLM_RETRY, MAX_SCHEMA_RETRY) - 1:
                break
            retry_suffix = VALIDATION_RETRY_PROMPT.replace(
                "[VALIDATION_ERRORS]",
                _format_validation_issues(issues),
            )

    if response is None:
        raise Exception(f"Failed to generate specialized structure for {message_type['name']} in {protocol}")
    raise Exception(
        "Failed validation for "
        f"{message_type['name']} in {protocol} after retries:\n{_format_validation_issues(issues)}"
    )


def get_specialized_structures(protocol: str, message_types: dict) -> dict:
    file_path = os.path.join(
        PROTOCOL_SPECIALIZED_STRUCTURE_OUTPUT_DIR,
        f"{protocol.lower()}_specialized_structures.json",
    )
    weak_file_path = os.path.join(
        PROTOCOL_SPECIALIZED_STRUCTURE_OUTPUT_DIR,
        f"{protocol.lower()}_specialized_structures_weak.json",
    )
    if os.path.exists(file_path):
        with open(file_path, "r", encoding="utf-8") as f:
            cached = json.load(f)
        print(f"Loaded cached results for {protocol} from {file_path}")
        return cached

    structures = {}
    weak_structure_targets = []

    structure_targets = message_types.get("all_client_to_server_messages") or message_types["client_to_server_messages"]

    for message_type in structure_targets:
        try:
            structures[message_type["name"]] = get_specialized_structure(protocol, message_type)
        except Exception as e:
            print(f"Error processing message type {message_type['name']} in {protocol}: {e}")
            weak_structure_targets.append(
                {
                    "name": message_type.get("name"),
                    "code": message_type.get("code"),
                    "description": message_type.get("description"),
                    "failure_reason": str(e),
                }
            )
    
    os.makedirs(PROTOCOL_SPECIALIZED_STRUCTURE_OUTPUT_DIR, exist_ok=True)
    with open(file_path, "w", encoding="utf-8") as f:
        json.dump(structures, f, indent=4, ensure_ascii=False)
    print(f"Saved results for {protocol} to {file_path}")

    with open(weak_file_path, "w", encoding="utf-8") as f:
        json.dump(weak_structure_targets, f, indent=4, ensure_ascii=False)
    print(f"Saved weak structure targets for {protocol} to {weak_file_path}")

    os.makedirs(LLM_RESULT_DIR, exist_ok=True)
    protocol_file = os.path.join(LLM_RESULT_DIR, f"2_{protocol.lower()}_specialized_structures.json")
    with open(protocol_file, "w", encoding="utf-8") as f:
        json.dump(structures, f, indent=4, ensure_ascii=False)

    weak_protocol_file = os.path.join(LLM_RESULT_DIR, f"2_{protocol.lower()}_specialized_structures_weak.json")
    with open(weak_protocol_file, "w", encoding="utf-8") as f:
        json.dump(weak_structure_targets, f, indent=4, ensure_ascii=False)

    return structures
