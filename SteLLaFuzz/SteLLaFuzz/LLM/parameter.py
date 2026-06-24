import hashlib
import json
import os
import re
import re

from typing import Any, Dict, List, Optional, Tuple

from openai import OpenAI
from pydantic import BaseModel, Field

from utility.utility import MODEL, LLM_RETRY, LLM_RESULT_DIR

IMPLEMENTATION_METADATA_OUTPUT_DIR = "implementation_metadata_results"
IMPLEMENTATION_METADATA_CACHE_DIR = "implementation_metadata_cache"
IMPLEMENTATION_METADATA_SCHEMA_VERSION = 12
PROTOCOL_SPECIALIZED_STRUCTURE_OUTPUT_DIR = "protocol_specialized_structure_results"

PARAMETER_GROUP_NAMES = [
    "path_params",
    "query_params",
    "body_fields",
    "headers",
    "argument_slots",
    "field_candidates",
]
PLACEHOLDER_VALUE_PATTERNS = [
    r"^\{[^}]+\}$",
    r"^<[^>]+>$",
    r"^example\.com$",
    r"^localhost$",
    r"^placeholder$",
    r"^token$",
    r"^token\d+$",
    r"^cookie_value_\d+$",
    r"^signature\d+$",
    r"^user\d+$",
    r"^session\d+$",
    r"^auth_data_placeholder$",
    r"^user_agent_string$",
]


class StructuredNamedValues(BaseModel):
    name: str
    values: List[str]
    wire_values: Optional[List[str]] = None


class StructuredParameterCandidateGroup(BaseModel):
    path_params: List[StructuredNamedValues]
    query_params: List[StructuredNamedValues]
    body_fields: List[StructuredNamedValues]
    headers: List[StructuredNamedValues]
    argument_slots: List[StructuredNamedValues]
    field_candidates: List[StructuredNamedValues]


class MinimalSurfaceInput(BaseModel):
    surface: str
    parameters: StructuredParameterCandidateGroup


class MinimalMessageTypeExtraction(BaseModel):
    message_type: str
    input_surfaces: List[MinimalSurfaceInput]


class MergedMetadata(BaseModel):
    protocol: str
    target_name: str
    variant: str
    responses: List[Dict[str, Any]] = Field(default_factory=list)


def _normalize_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _is_placeholder_like(value: Any) -> bool:
    text = _normalize_text(value)
    if not text:
        return True
    lowered = text.lower()
    for pattern in PLACEHOLDER_VALUE_PATTERNS:
        if re.match(pattern, text, flags=re.IGNORECASE):
            return True
    if lowered in {"some-request-type", "some-data", "key:value"}:
        return True
    return False


def _dedupe_preserve_order(values: List[Any]) -> List[str]:
    seen = set()
    deduped: List[str] = []
    for value in values:
        normalized = _normalize_text(value)
        if not normalized or normalized in seen or _is_placeholder_like(normalized):
            continue
        deduped.append(normalized)
        seen.add(normalized)
    return deduped


def _merge_named_value_entries(entries: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    grouped: Dict[str, List[str]] = {}
    grouped_wire: Dict[str, List[str]] = {}
    order: List[str] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        name = _normalize_text(entry.get("name"))
        if not name:
            continue
        if name not in grouped:
            grouped[name] = []
            order.append(name)
        raw_values = entry.get("values", [])
        if isinstance(raw_values, list):
            grouped[name].extend(raw_values)
        raw_wire_values = entry.get("wire_values", [])
        if isinstance(raw_wire_values, list):
            grouped_wire.setdefault(name, []).extend(raw_wire_values)
    merged_entries = []
    for name in order:
        merged_entry = {
            "name": name,
            "values": _dedupe_preserve_order(grouped.get(name, [])),
        }
        merged_wire_values = _dedupe_preserve_order(grouped_wire.get(name, []))
        if merged_wire_values:
            merged_entry["wire_values"] = merged_wire_values
        merged_entries.append(merged_entry)
    return merged_entries


def _merge_parameter_groups(existing: Dict[str, Any], incoming: Dict[str, Any]) -> Dict[str, Any]:
    merged: Dict[str, Any] = {}
    for group_name in PARAMETER_GROUP_NAMES:
        existing_entries = existing.get(group_name, [])
        incoming_entries = incoming.get(group_name, [])
        merged_entries: List[Dict[str, Any]] = []
        if isinstance(existing_entries, list):
            merged_entries.extend(existing_entries)
        if isinstance(incoming_entries, list):
            merged_entries.extend(incoming_entries)
        merged[group_name] = _merge_named_value_entries(merged_entries)
    return merged


def _merge_input_surfaces(input_surfaces: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    grouped: Dict[str, Dict[str, Any]] = {}
    order: List[str] = []
    for surface in input_surfaces:
        if not isinstance(surface, dict):
            continue
        surface_name = _normalize_text(surface.get("surface"))
        if not surface_name or _is_placeholder_like(surface_name):
            continue
        parameters = surface.get("parameters", {})
        if not isinstance(parameters, dict):
            parameters = {}
        if surface_name not in grouped:
            grouped[surface_name] = {
                "surface": surface_name,
                "parameters": {group_name: [] for group_name in PARAMETER_GROUP_NAMES},
            }
            order.append(surface_name)
        grouped[surface_name]["parameters"] = _merge_parameter_groups(
            grouped[surface_name]["parameters"],
            parameters,
        )
    return [grouped[key] for key in order]


IMPLEMENTATION_METADATA_PROMPT = """\
You analyze protocol-facing inputs for a target implementation.
Your goal is to recover NORMAL, structurally valid input metadata that testcase generation can reuse.

Inputs:
1. Protocol: [PROTOCOL]
2. Target implementation name: [TARGET_NAME]
3. Target message type:
[MESSAGE_TYPE]
4. Application protocol hint:
[PROTOCOL_HINT]
5. Optional seed-derived generalized observations:
[GENERALIZED_INPUT_OBSERVATIONS]
6. Few-shot examples:
[FEW_SHOT_EXAMPLES]

Return a JSON object with this exact structure:
{
  "message_type": "[MESSAGE_TYPE]",
  "input_surfaces": [
    {
      "surface": "surface_a",
      "parameters": {
        "path_params": [],
        "query_params": [],
        "body_fields": [],
        "headers": [],
        "argument_slots": [],
        "field_candidates": []
      }
    }
  ]
}

Instructions:
1. Extract metadata for normal inputs first. Prefer structurally valid surfaces, parameters, and values over malformed cases.
2. Work only on the single target message type given above.
3. For text-based protocols, interaction_surfaces should be concrete request targets, resource URIs, or protocol-visible textual commands. Do not emit generic English labels.
4. For binary protocols, interaction_surfaces should be concrete protocol-facing labels such as "QUERY", "NOTIFY", or "UPDATE".
5. For binary protocols, when a field has a directly observed or strongly supported field-level wire representation, include it as `wire_values` using hex bytes such as `["0x13 0x01"]`.
6. Use `wire_values` only for field-level reusable values. Do not copy whole-message fragments, whole packets, or long opaque blobs as `wire_values`.
7. For binary protocols, keep semantic values in `values` when useful, and add `wire_values` only when the field-level bytes are justified.
5. Use the protocol hint as a secondary disambiguation aid. Do not invent implementation-specific values without evidence.
6. Prefer application-facing surfaces over transport-generic wrappers when the application hint makes that clear.
7. Keep query/body/header/field candidates concrete. For example use "command", "group-type", "qtype", "qclass", "property", "value", "edit-params" instead of prose descriptions.
8. Provide normal candidate values whenever you can justify them. Examples:
   - command -> move, clear
   - group-type -> albums, artists
   - qtype -> A, AAAA, MX
9. If a surface is specific enough to imply parameters, list those parameters directly under parameters instead of hiding them in prose.
10. Return only the JSON object. Do not add notes, explanations, metadata_version, or extra wrapper fields.



"""


WITH_SEED_IMPLEMENTATION_METADATA_PROMPT = """\
You analyze protocol-facing inputs for a target implementation.
Your goal is to reconstruct SEED-USABLE, implementation-specific, protocol-valid concrete input metadata from seed-derived observations.

Inputs:
1. Protocol: [PROTOCOL]
2. Target implementation name: [TARGET_NAME]
3. Target message type:
[MESSAGE_TYPE]
4. Application protocol hint:
[PROTOCOL_HINT]
5. Raw seed messages:
[RAW_SEED_MESSAGES]
6. Few-shot examples:
[FEW_SHOT_EXAMPLES]

Return a JSON object with this exact structure:
{
  "message_type": "[MESSAGE_TYPE]",
  "input_surfaces": [
    {
      "surface": "surface_a",
      "parameters": {
        "path_params": [],
        "query_params": [],
        "body_fields": [],
        "headers": [],
        "argument_slots": [],
        "field_candidates": []
      }
    }
  ]
}

Instructions:
1. Work only on the single target message type given above.
2. Use the raw seed messages as the primary evidence source. Do not invent additional values for diversity, coverage, or protocol completeness.
3. If a field has no clear seed-backed value, leave its values list empty instead of synthesizing a candidate.
4. If the raw seed messages do not provide clear evidence for any concrete input surface for the target message type, return `"input_surfaces": []` rather than inventing a surface.
4. Extract only reusable field-level candidates. Do not copy whole messages, whole requests, or whole packet templates as parameter values unless the observed value is itself a single reusable field.
5. Keep only concrete, protocol-facing, implementation-usable values that are directly observed or strongly supported by the raw seed messages.
6. For binary protocols, when a field-level wire representation is directly observed or strongly supported, include it as `wire_values` using hex bytes such as `["0x13 0x01"]`.
7. Use `wire_values` only for reusable field-level values. Do not emit whole-packet fragments, long opaque packet slices, or unrelated framing bytes as `wire_values`.
8. Reject placeholders, template markers, synthetic stand-ins, and abstract labels. Do not include values such as:
   - {id}, {int}, {session_id}, {random_bytes}, {password}, {public_key}
   - some-request-type, some-data, key:value
   - <target_host>, <user_agent_string>, <session_id>, <token>, <placeholder>
   - example.com, localhost, or other generic examples unless directly evidenced as the real target-facing value
9. Reject zero-only sentinel values and unexplained opaque blobs when they appear to be filler, padding, or copied whole-message fragments rather than meaningful field values.
10. Every input_surface must match the target message_type. Do not assign a surface name that belongs to a different message type.
11. Do not transfer values across message types unless the protocol semantics clearly make the field reusable for this exact target message type.
12. For text-based protocols, surfaces should be concrete request targets, resource URIs, or protocol-visible textual commands when they are evidenced by the raw seed messages. Do not emit generic English labels.
13. For binary protocols, surfaces should be concrete protocol-facing labels when they are evidenced by the raw seed messages.
14. If a surface is specific enough to imply parameters, list those parameters directly under parameters instead of hiding them in prose.
15. Return only the JSON object. Do not add notes, explanations, metadata_version, or extra wrapper fields.
"""


IMPLEMENTATION_METADATA_FEW_SHOT_EXAMPLES = """\
Example A: forked-daapd / DAAP over HTTP
{
  "message_type": "GET",
  "input_surfaces": [
    {
      "surface": "/databases/1/groups",
      "parameters": {
        "path_params": [],
        "query_params": [
          {"name": "group-type", "values": ["albums", "artists", "genres"]},
          {"name": "session-id", "values": ["1"]},
          {"name": "revision-number", "values": ["2"]}
        ],
        "body_fields": [],
        "headers": [],
        "argument_slots": [],
        "field_candidates": []
      }
    },
    {
      "surface": "/ctrl-int/1/playqueue-edit",
      "parameters": {
        "path_params": [],
        "query_params": [
          {"name": "command", "values": ["move", "clear"]},
          {"name": "mode", "values": ["all", "items"]},
          {"name": "edit-params", "values": ["edit-param.move-pair3:0", "edit-param.remove:1"]}
        ],
        "body_fields": [],
        "headers": [],
        "argument_slots": [],
        "field_candidates": []
      }
    }
  ]
}

Example B: TLS ClientHello
{
  "message_type": "ClientHello",
  "input_surfaces": [
    {
      "surface": "ClientHello",
      "parameters": {
        "path_params": [],
        "query_params": [],
        "body_fields": [],
        "headers": [],
        "argument_slots": [],
        "field_candidates": [
          {"name": "client_version", "values": ["TLSv1.2", "TLSv1.3"], "wire_values": ["0x03 0x03", "0x03 0x04"]},
          {"name": "cipher_suites", "values": ["TLS_AES_128_GCM_SHA256", "TLS_AES_256_GCM_SHA384", "TLS_CHACHA20_POLY1305_SHA256"], "wire_values": ["0x13 0x01", "0x13 0x02", "0x13 0x03"]},
          {"name": "extensions", "values": ["server_name", "supported_versions", "signature_algorithms", "key_share"], "wire_values": ["0x00 0x00", "0x00 0x2b", "0x00 0x0d", "0x00 0x33"]}
        ]
      }
    }
  ]
}

Example C: RTSP SETUP
{
  "message_type": "SETUP",
  "input_surfaces": [
    {
      "surface": "rtsp://127.0.0.1:8554/webmFileTest/track1",
      "parameters": {
        "path_params": [],
        "query_params": [],
        "body_fields": [],
        "headers": [
          {"name": "CSeq", "values": ["3"]},
          {"name": "Transport", "values": ["RTP/AVP/TCP;unicast;interleaved=0-1", "RTP/AVP;unicast;client_port=8000-8001"]}
        ],
        "argument_slots": [],
        "field_candidates": []
      }
    }
  ]
}

Example D: SSH KEXINIT
{
  "message_type": "KEXINIT",
  "input_surfaces": [
    {
      "surface": "KEXINIT",
      "parameters": {
        "path_params": [],
        "query_params": [],
        "body_fields": [],
        "headers": [],
        "argument_slots": [],
        "field_candidates": [
          {"name": "kex_algorithms", "values": ["curve25519-sha256", "curve25519-sha256@libssh.org", "diffie-hellman-group14-sha256"], "wire_values": ["0x63 0x75 0x72 0x76 0x65 0x32 0x35 0x35 0x31 0x39 0x2d 0x73 0x68 0x61 0x32 0x35 0x36"]},
          {"name": "server_host_key_algorithms", "values": ["ssh-ed25519", "rsa-sha2-256", "ssh-rsa"], "wire_values": ["0x73 0x73 0x68 0x2d 0x65 0x64 0x32 0x35 0x35 0x31 0x39"]},
          {"name": "encryption_algorithms_client_to_server", "values": ["chacha20-poly1305@openssh.com", "aes128-ctr", "aes256-ctr"], "wire_values": ["0x61 0x65 0x73 0x31 0x32 0x38 0x2d 0x63 0x74 0x72"]},
          {"name": "mac_algorithms_client_to_server", "values": ["hmac-sha2-256", "hmac-sha2-512"], "wire_values": ["0x68 0x6d 0x61 0x63 0x2d 0x73 0x68 0x61 0x32 0x2d 0x32 0x35 0x36"]},
          {"name": "compression_algorithms_client_to_server", "values": ["none", "zlib@openssh.com"], "wire_values": ["0x6e 0x6f 0x6e 0x65"]}
        ]
      }
    }
  ]
}
"""

OPAQUE_FIELD_NAMES = {
    "request_line",
    "packet_length",
    "padding_length",
    "message_type",
    "session_id_length",
    "cipher_suite_count",
    "compression_method_count",
    "certificate_length",
    "cookie",
    "random",
    "client_random",
    "server_random",
    "key_material",
    "verify_data",
    "certificate_data",
}
SEMANTIC_BYTES_FIELD_NAMES = {
    "cipher_suites",
    "extensions",
    "supported_versions",
    "compression_methods",
}
GENERIC_SURFACE_ONLY_FIELDS = {
    "request_line",
}


def _iter_structure_fields(message_structure: Dict[str, Any]) -> List[Dict[str, Any]]:
    fields: List[Dict[str, Any]] = []
    for layer in message_structure.get("layers", []):
        if not isinstance(layer, dict):
            continue
        for field in layer.get("fields", []):
            if isinstance(field, dict):
                fields.append(field)
    return fields


def summarize_specialized_structure_for_metadata(
    message_type: str,
    message_structure: Dict[str, Any],
) -> Dict[str, Any]:
    fields = _iter_structure_fields(message_structure)
    schema_kind = str(message_structure.get("schema_kind") or "unknown").strip() or "unknown"
    message_role = str(message_structure.get("message_role") or "").strip()

    relevant_fields: List[str] = []
    header_fields: List[str] = []
    semantic_list_fields: List[str] = []
    opaque_fields: List[str] = []
    count_or_length_fields: List[str] = []

    for field in fields:
        name = str(field.get("name") or "").strip()
        field_type = str(field.get("type") or "").strip()
        syntax_role = str(field.get("syntax_role") or "").strip()
        if not name:
            continue

        lowered_name = name.lower()
        if syntax_role == "header":
            header_fields.append(name)

        if lowered_name.endswith("_count") or lowered_name.endswith("_length"):
            count_or_length_fields.append(name)
            continue

        if lowered_name in OPAQUE_FIELD_NAMES:
            opaque_fields.append(name)
            continue

        if field_type == "name_list":
            relevant_fields.append(name)
            semantic_list_fields.append(name)
            continue

        if field_type == "bytes":
            if lowered_name in SEMANTIC_BYTES_FIELD_NAMES:
                relevant_fields.append(name)
                semantic_list_fields.append(name)
            else:
                opaque_fields.append(name)
            continue

        if name not in GENERIC_SURFACE_ONLY_FIELDS:
            relevant_fields.append(name)

    summary: Dict[str, Any] = {
        "message_type": message_type,
        "schema_kind": schema_kind,
        "message_role": message_role,
        "surface_rule": (
            "Use only the request target or resource URI as the surface, not the full start line."
            if schema_kind == "text"
            else "Use only the protocol-facing message label as the surface, not raw packet fragments."
        ),
        "relevant_fields": _dedupe_preserve_order(relevant_fields),
        "header_fields": _dedupe_preserve_order(header_fields),
        "semantic_list_fields": _dedupe_preserve_order(semantic_list_fields),
        "opaque_fields": _dedupe_preserve_order(opaque_fields),
        "count_or_length_fields": _dedupe_preserve_order(count_or_length_fields),
        "do_not_emit": (
            [
                "full request line as surface",
                "whole-message template values",
            ]
            if schema_kind == "text"
            else [
                "single raw bytes as semantic field values",
                "whole-packet template values",
            ]
        ),
    }

    if schema_kind == "binary" and semantic_list_fields:
        summary["semantic_value_rule"] = (
            "For semantic list fields, emit complete identifiers or protocol tokens rather than byte fragments."
        )
    elif schema_kind == "binary":
        summary["semantic_value_rule"] = (
            "Prefer semantic field values over opaque binary blobs when the field has a named protocol meaning."
        )

    return summary


def summarize_weak_specialized_structure_for_metadata(
    message_type: str,
    schema_kind: str,
) -> Dict[str, Any]:
    normalized_schema_kind = schema_kind.strip() or "unknown"
    return {
        "message_type": message_type,
        "schema_kind": normalized_schema_kind,
        "message_role": "request",
        "summary_strength": "weak_fallback",
        "surface_rule": (
            "Use only the request target or resource URI as the surface, not the full start line."
            if normalized_schema_kind == "text"
            else "Use only the protocol-facing message label as the surface, not raw packet fragments."
        ),
        "relevant_fields": [],
        "header_fields": [],
        "semantic_list_fields": [],
        "opaque_fields": ["request_line"] if normalized_schema_kind == "text" else [],
        "count_or_length_fields": [],
        "do_not_emit": (
            [
                "full request line as surface",
                "whole-message template values",
            ]
            if normalized_schema_kind == "text"
            else [
                "single raw bytes as semantic field values",
                "whole-packet template values",
            ]
        ),
    }


def summarize_specialized_structures_for_metadata(
    specialized_structures: Dict[str, Any],
    message_type_names: Optional[List[str]] = None,
    weak_specialized_structures: Optional[List[Dict[str, Any]]] = None,
    default_schema_kind: str = "unknown",
) -> Dict[str, Any]:
    if not isinstance(specialized_structures, dict):
        specialized_structures = {}

    selected_names = message_type_names or list(specialized_structures.keys())
    summaries: Dict[str, Any] = {}
    for message_type in selected_names:
        structure = specialized_structures.get(message_type)
        if isinstance(structure, dict):
            summaries[message_type] = summarize_specialized_structure_for_metadata(
                message_type,
                structure,
            )

    if isinstance(weak_specialized_structures, list):
        for weak_entry in weak_specialized_structures:
            if not isinstance(weak_entry, dict):
                continue
            weak_name = str(
                weak_entry.get("name")
                or weak_entry.get("message_type")
                or weak_entry.get("code")
                or ""
            ).strip()
            if not weak_name or weak_name in summaries:
                continue
            if message_type_names is not None and weak_name not in selected_names:
                continue
            summaries[weak_name] = summarize_weak_specialized_structure_for_metadata(
                weak_name,
                default_schema_kind,
            )
    return summaries


def _generalized_observation_prompt_context(extra_context: Optional[Dict[str, Any]]) -> str:
    if not isinstance(extra_context, dict):
        return "No seed-derived generalized observations provided."
    observations = extra_context.get("generalized_input_observations")
    if not isinstance(observations, dict):
        return "No seed-derived generalized observations provided."
    return json.dumps(observations, indent=2, ensure_ascii=False)


def _raw_seed_prompt_context(extra_context: Optional[Dict[str, Any]]) -> str:
    if not isinstance(extra_context, dict):
        return "No raw seed messages provided."
    raw_seed_messages = extra_context.get("raw_seed_messages")
    raw_seed_file_names = extra_context.get("raw_seed_file_names") or []
    if not isinstance(raw_seed_messages, list) or not raw_seed_messages:
        return "No raw seed messages provided."

    blocks: List[str] = []
    for index, seed_message in enumerate(raw_seed_messages, start=1):
        if not isinstance(seed_message, str):
            continue
        file_name = ""
        if isinstance(raw_seed_file_names, list) and index - 1 < len(raw_seed_file_names):
            candidate = raw_seed_file_names[index - 1]
            if isinstance(candidate, str) and candidate.strip():
                file_name = candidate.strip()
        header = f"Seed {index}"
        if file_name:
            header += f" ({file_name})"
        blocks.append(f"--- {header} ---\n{seed_message}")

    return "\n\n".join(blocks) if blocks else "No raw seed messages provided."


def _build_cache_suffix(extra_context: Optional[Dict[str, Any]]) -> str:
    normalized_context = json.dumps(
        {
            "schema_version": IMPLEMENTATION_METADATA_SCHEMA_VERSION,
            "extra_context": extra_context or {},
        },
        sort_keys=True,
        ensure_ascii=False,
    )
    return hashlib.sha256(normalized_context.encode("utf-8")).hexdigest()[:12]


def _save_raw_completion(completion_dump: Dict[str, Any]) -> None:
    os.makedirs(os.path.join(LLM_RESULT_DIR, "3_implementation_metadata"), exist_ok=True)
    index = 0
    while os.path.exists(
        os.path.join(LLM_RESULT_DIR, "3_implementation_metadata", f"response_{index}.json")
    ):
        index += 1
    output_file = os.path.join(LLM_RESULT_DIR, "3_implementation_metadata", f"response_{index}.json")
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(completion_dump, f, indent=4, ensure_ascii=False)


def _save_user_facing_metadata(
    protocol: str,
    target_name: str,
    file_suffix: str,
    variant_label: str,
    extractions: List[MinimalMessageTypeExtraction],
) -> None:
    payload = {
        "protocol": protocol,
        "target_name": target_name,
        "variant": variant_label,
        "responses": _merge_extractions_by_message_type(extractions),
    }

    os.makedirs(IMPLEMENTATION_METADATA_OUTPUT_DIR, exist_ok=True)
    output_file = os.path.join(
        IMPLEMENTATION_METADATA_OUTPUT_DIR,
        f"{protocol.lower()}_{target_name.lower()}_{variant_label}_{file_suffix}_implementation_metadata.json",
    )
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=4, ensure_ascii=False)

    os.makedirs(LLM_RESULT_DIR, exist_ok=True)
    llm_output_file = os.path.join(
        LLM_RESULT_DIR,
        f"3_{protocol.lower()}_{target_name.lower()}_{variant_label}_{file_suffix}_implementation_metadata.json",
    )
    with open(llm_output_file, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=4, ensure_ascii=False)


def _merge_extractions_by_message_type(
    extractions: List[MinimalMessageTypeExtraction],
) -> List[Dict[str, Any]]:
    grouped: Dict[str, Dict[str, Any]] = {}
    for extraction in extractions:
        grouped_response = grouped.setdefault(
            extraction.message_type,
            {
                "message_type": extraction.message_type,
                "input_surfaces": [],
            },
        )
        grouped_response["input_surfaces"].extend(
            extraction.model_dump().get("input_surfaces", [])
        )
    for grouped_response in grouped.values():
        grouped_response["input_surfaces"] = _merge_input_surfaces(
            grouped_response.get("input_surfaces", [])
        )
    return [grouped[key] for key in sorted(grouped.keys())]


def using_llm(prompt: str) -> Optional[Tuple[MinimalMessageTypeExtraction, Dict[str, Any]]]:
    client = OpenAI()
    try:
        completion = client.beta.chat.completions.parse(
            model=MODEL,
            temperature=0.5,
            messages=[
                {
                    "role": "system",
                    "content": "You extract normal protocol-facing input metadata and return structured JSON.",
                },
                {"role": "user", "content": prompt},
            ],
            response_format=MinimalMessageTypeExtraction,
            timeout=30,
        )
        response = completion.choices[0].message.parsed
        _save_raw_completion(completion.model_dump())
        return response, completion.model_dump()
    except Exception as e:
        print(f"Error processing implementation metadata: {e}")
        return None


def _get_message_type_metadata(
    protocol: str,
    target_name: str,
    message_type: str,
    extra_context: Optional[Dict[str, Any]] = None,
) -> Optional[MinimalMessageTypeExtraction]:
    protocol_hint = str((extra_context or {}).get("application_protocol_hint") or protocol).strip()
    has_seed_observations = bool((extra_context or {}).get("raw_seed_messages"))
    max_attempts = 1
    prompt_template = (
        WITH_SEED_IMPLEMENTATION_METADATA_PROMPT
        if has_seed_observations
        else IMPLEMENTATION_METADATA_PROMPT
    )
    prompt = (
        prompt_template.replace("[PROTOCOL]", protocol)
        .replace("[TARGET_NAME]", target_name)
        .replace("[MESSAGE_TYPE]", message_type)
        .replace("[PROTOCOL_HINT]", protocol_hint)
        .replace(
            "[RAW_SEED_MESSAGES]",
            _raw_seed_prompt_context(extra_context),
        )
        .replace("[FEW_SHOT_EXAMPLES]", IMPLEMENTATION_METADATA_FEW_SHOT_EXAMPLES)
    )

    for _ in range(max_attempts):
        result = using_llm(prompt)
        if result is not None:
            response, _completion_dump = result
            return response
    return None


def _run_metadata_extraction_variant(
    protocol: str,
    target_name: str,
    message_type_names: List[str],
    extra_context: Optional[Dict[str, Any]],
) -> List[MinimalMessageTypeExtraction]:
    extractions: List[MinimalMessageTypeExtraction] = []
    for message_type_name in message_type_names:
        extraction = _get_message_type_metadata(
            protocol,
            target_name,
            message_type_name,
            extra_context,
        )
        if extraction is not None:
            extractions.append(extraction)
    return extractions


def _minimal_extractions_to_metadata(
    protocol: str,
    target_name: str,
    message_type_names: List[str],
    extractions: List[MinimalMessageTypeExtraction],
    extra_context: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    del message_type_names
    del extra_context
    return MergedMetadata(
        protocol=protocol,
        target_name=target_name,
        variant="single",
        responses=_merge_extractions_by_message_type(extractions),
    ).model_dump()


def _merge_metadata_variants(
    protocol: str,
    target_name: str,
    message_type_names: List[str],
    without_seed_metadata: Dict[str, Any],
    with_seed_metadata: Optional[Dict[str, Any]],
    merged_extra_context: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    del message_type_names
    del merged_extra_context
    merged_responses: List[Dict[str, Any]] = []
    for source in [without_seed_metadata, with_seed_metadata]:
        if not source:
            continue
        for response in source.get("responses", []):
            if isinstance(response, dict):
                merged_responses.append(response)
    merged_extractions = [
        MinimalMessageTypeExtraction.model_validate(response)
        for response in merged_responses
        if isinstance(response, dict)
    ]
    return MergedMetadata(
        protocol=protocol,
        target_name=target_name,
        variant="merged",
        responses=_merge_extractions_by_message_type(merged_extractions),
    ).model_dump()


def build_implementation_metadata(
    protocol: str,
    target_name: str,
    message_types: Dict[str, Any],
    seed_messages: Optional[List[str]] = None,
    extra_context: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    del seed_messages

    metadata_targets = message_types.get("all_client_to_server_messages")
    if not isinstance(metadata_targets, list) or not metadata_targets:
        metadata_targets = message_types.get("client_to_server_messages", [])

    message_type_names = [
        message_type["name"]
        for message_type in metadata_targets
        if message_type.get("name")
    ]
    base_extra_context = {
        "application_protocol_hint": str((extra_context or {}).get("application_protocol_hint") or protocol).strip()
    }
    with_seed_extra_context = dict(extra_context or {})

    without_seed_suffix = _build_cache_suffix(base_extra_context)
    with_seed_suffix = _build_cache_suffix(with_seed_extra_context)
    merged_suffix = _build_cache_suffix(
        {
            "without_seed_suffix": without_seed_suffix,
            "with_seed_suffix": with_seed_suffix,
            "merged": True,
        }
    )
    merged_cache_file_path = os.path.join(
        IMPLEMENTATION_METADATA_CACHE_DIR,
        f"{protocol.lower()}_{target_name.lower()}_merged_{merged_suffix}_implementation_metadata.json",
    )
    if os.path.exists(merged_cache_file_path):
        with open(merged_cache_file_path, "r", encoding="utf-8") as f:
            cached = json.load(f)
        print(
            f"Loaded cached implementation metadata for {protocol}/{target_name} from {merged_cache_file_path}"
        )
        return cached

    without_seed_extractions = _run_metadata_extraction_variant(
        protocol,
        target_name,
        message_type_names,
        base_extra_context,
    )
    without_seed_metadata = _minimal_extractions_to_metadata(
        protocol,
        target_name,
        message_type_names,
        without_seed_extractions,
        base_extra_context,
    )
    _save_user_facing_metadata(
        protocol,
        target_name,
        without_seed_suffix,
        "without_seed",
        without_seed_extractions,
    )

    with_seed_metadata = None
    if with_seed_extra_context.get("raw_seed_messages"):
        with_seed_extractions = _run_metadata_extraction_variant(
            protocol,
            target_name,
            message_type_names,
            with_seed_extra_context,
        )
        with_seed_metadata = _minimal_extractions_to_metadata(
            protocol,
            target_name,
            message_type_names,
            with_seed_extractions,
            with_seed_extra_context,
        )
        _save_user_facing_metadata(
            protocol,
            target_name,
            with_seed_suffix,
            "with_seed",
            with_seed_extractions,
        )

    merged_metadata = _merge_metadata_variants(
        protocol,
        target_name,
        message_type_names,
        without_seed_metadata,
        with_seed_metadata,
        with_seed_extra_context,
    )

    os.makedirs(IMPLEMENTATION_METADATA_CACHE_DIR, exist_ok=True)
    with open(merged_cache_file_path, "w", encoding="utf-8") as f:
        json.dump(merged_metadata, f, indent=4, ensure_ascii=False)
    print(f"Saved implementation metadata for {protocol}/{target_name}")

    return merged_metadata
