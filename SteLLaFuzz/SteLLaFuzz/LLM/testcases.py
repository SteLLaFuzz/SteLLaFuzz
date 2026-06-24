import json
import os
import random
import re

from typing import Any, Dict, List, Optional, Sequence as TypingSequence, Tuple
from pydantic import BaseModel
from openai import OpenAI
from utility.usage_history import get_used_values_for_surface_field
from utility.utility import (
    MODEL,
    LLM_RETRY,
    LLM_RESULT_DIR,
    convert_message_to_binary,
    get_raw_output_dir,
    save_llm_response_testcase,
)

TESTCASE_OUTPUT_DIR = "testcase_results"
MAX_PLANS_PER_SEQUENCE = 3
MAX_PLAN_ATTEMPTS_PER_SEQUENCE = 10
PARAMETER_CANDIDATE_SLOTS = (
    "path_params",
    "query_params",
    "body_fields",
    "headers",
    "argument_slots",
    "field_candidates",
)


class Message(BaseModel):
    message: str


class Sequence(BaseModel):
    sequenceId: str
    messages: List[Message]
    explanation: str


class TestCase(BaseModel):
    protocol: str
    sequences: List[Sequence]


MESSAGE_PROMPT = """\
You are a network protocol expert with deep understanding of [PROTOCOL].
Your task is to realize pre-selected client-to-server generation plans for the [PROTOCOL] protocol.

1. **Fixed Generation Plans:**
   ```
   [GENERATION_PLANS]
   ```
   (Each plan already selects a concrete per-message surface and concrete field values. Treat each plan as authoritative. Do not invent a different surface or substitute unrelated values. If `selected_wire_fields` are present, those wire hex values are higher-priority than semantic labels for realizing binary messages.)

2. **Type Sequence:**  
   [SEQUENCE]

3. **Type Structure:**  
   [STRUCTURE]

4. **Number of Message Sequences to Generate:**  
   [NUMBER]

Please adhere to the following instructions:

1. **Realize The Provided Plans:**
   - Generate exactly [NUMBER] message sequences, one per provided generation plan.
   - Each output sequence MUST preserve the provided type order.
   - For each output sequence, use the corresponding plan's selected surface and selected field values as the concrete baseline.
   - Do not replace a selected surface with a different surface.
   - Do not replace a selected field value with a different unrelated value.
   - If `selected_wire_fields` are provided for a binary message, preserve those exact wire hex values for the corresponding fields.
   - If a plan omits a field, you may fill protocol-required glue conservatively, but keep the selected values unchanged.
   - For binary-based protocols, represent each message as a sequence of bytes in hex format separated by spaces (e.g., "0x1a 0x0b 0x34 0x00").
   - For text-based protocols, generate the message in plain ASCII text using spaces, newlines, or CRLF as needed according to the protocol specification.
   - For each message in a sequence, map the message type to its corresponding structure from the type structure and realize the provided surface + selected field values.

   **Example:**  
   For SMTP, an acceptable output would be:
   ```json
   {
      "protocol": "SMTP",
      "sequences": [
          {
              "sequenceId": "1",
              "messages": [
                  {"message": "HELO localhost"},
                  {"message": "MAIL FROM:<ubuntu@ubuntu>"},
                  {"message": "RCPT TO:<ubuntu@ubuntu>"},
                  {"message": "DATA"},
                  {"message": "From: ubuntu <ubuntu@ubuntu>\\r\\nTo: ubuntu <ubuntu@ubuntu>\\r\\nSubject: Test Email\\r\\n\\r\\nThis is a test email body."},
                  {"message": "QUIT"}
              ],
              "explanation": "Explanation of the sequence generation process"
          }
      ]
   }
   ```
   For SSH, an acceptable output would be:
   ```json
   {
      "protocol": "SSH",
      "sequences": [
          {
              "sequenceId": "1",
              "messages": [
                  {"message": "SSH-2.0-OpenSSH_7.5"},
                  {"message": "0x00 0x00 0x9c 0x05 0x14 0x09 0x00 0x00 0x00 0x00 0x00 0x00 0x00 0x00 0x00 0x30 0x01 0x75 0x63 0x76 0x72 0x32 0x65 0x35 0x35 0x39 0x31 0x73 0x2d 0x61 0x68 0x35 0x32 0x2c 0x36 0x6c 0x7a 0x62 0x69 0x00 0x00 0x1a 0x00 0x6f 0x6e 0x65 0x6e 0x7a 0x2c 0x69 0x6c 0x40 0x62 0x70 0x6f 0x6e 0x65 0x73 0x73 0x2e 0x68 0x6f 0x63 0x2c 0x6d 0x6c 0x7a 0x62 0x69 0x00 0x00 0x00 0x00 0x00 0x00 0x00 0x00 0x00 0x00 0x00 0x00 0x00 0x00 0x00 0x00 0x00 0x00 0x00 0x00 0x00 0x00 0x00 0x00 0x00 0x00 0x00 0x00 0x2c 0x00 0x1e 0x06 0x00 0x00 0x20 0x00 0xe5 0x2f 0xa3 0x7d 0xcd 0x47 0x43 0x62 0x28 0x15 0xac 0xda 0xbb 0x5f 0x07 0x29 0xff 0x30 0x84 0xf6 0xc4 0xaf 0xc2 0xcf 0x90 0xed 0x5f 0x99 0xcb 0x58 0x74 0x3b 0x00 0x00 0x00 0x00 0x00 0x00 0x00 0x00 0x0c 0x00 0x00 0x0a"},
                  {"message": "0x00 0x15 0x00 0x00 0x00 0x00 0x00 0x00 0x00 0x00 0x00 0x00 0x00 0x00 0x00 0x00 0x00 0x00 0x06 0x18 0x00 0x05 0x00 0x00 0x73 0x0c 0x68 0x73 0x75 0x2d 0x65 0x73 0x61 0x72 0x74 0x75 0x00 0x68 0x00 0x00 0x00 0x00 0xb9 0x00 0x1a 0xac 0x9c 0xe0 0xc1 0xfa 0x00 0xd5 0x00 0x00 0x0a 0x30"},
                  {"message": "0x00 0x32 0x00 0x00 0x75 0x06 0x75 0x62 0x74 0x6e 0x00 0x75 0x00 0x00 0x73 0x0e 0x68 0x73 0x63 0x2d 0x6e 0x6f 0x65 0x6e 0x74 0x63 0x6f 0x69 0x00 0x6e 0x00 0x00 0x6e 0x04 0x6e 0x6f 0x00 0x65 0x00 0x00 0x00 0x00 0x00 0x00 0xf3 0x00 0x35 0xee 0xe3 0xb0 0x27 0x3a 0x00 0x5d 0x00 0x00 0x0a 0x48"}
              ],
              "explanation": "Explanation of the sequence generation process"
          }
      ]
   }
   ```

2. **Keep The Plans Intact:**
   - The provided plans were already selected to cover different corridors and values.
   - Your job is to faithfully realize them, not to redesign them.

3. **Authoritative and Accurate:**
   - Base the actual values strictly on the provided type structure.
   - Use the provided generation plans as the primary authority for chosen surfaces and field values.
   - Avoid subjective assumptions; rely solely on the provided inputs.

4. **Step-by-Step Reasoning:**
   - In the "explanation" field, include a clear, step-by-step explanation of how the sequences were generated.
   - Describe how each message type was mapped to the corresponding selected surface and selected field values from its plan.
   - Note any protocol-required glue fields you had to add conservatively.

5. **Final Output Format:**
   - The final output must be a JSON object with the following structure:
     ```json
     {
       "protocol": "[PROTOCOL]",
       "sequences": [
         {
           "sequenceId": "A unique identifier for the sequence",
           "message_sequence": "Total messages in the sequence",
           "explanation": "A step-by-step explanation of how the sequences were generated and the rationale behind the actual values selected.",
           "is_binary": "True if the protocol is binary-based, False otherwise"
         }
         // ... additional sequence objects, up to [NUMBER] sequences
       ]
     }
     ```

Please realize the provided generation plans for [PROTOCOL] based on the above instructions.
"""


REFINEMENT_PROMPT = """\
You are a network protocol expert refining preliminary [PROTOCOL] testcase sequences.

1. **Authoritative Generation Plans**
   ```
   [GENERATION_PLANS]
   ```

2. **Type Sequence**
   [SEQUENCE]

3. **Type Structure**
   [STRUCTURE]

4. **Preliminary Candidate Sequences**
   ```
   [PRELIMINARY_SEQUENCES]
   ```

Refine the preliminary sequences under these rules:

1. Keep the same number of sequences and the same message order.
2. Treat the provided generation plans as authoritative. Do not invent new semantic fields or unrelated values.
3. If a message has wire-oriented content in the plans or preliminary candidate, use only bytes already present in the plan-selected wire values and the preliminary candidate sequences.
4. If a message is binary-oriented, output it strictly as hex bytes separated by spaces, for example: `0x16 0x03 0x03 0x00 0x2f`.
5. If a message is text-oriented, output plain ASCII protocol text only. Remove commentary, field labels, and other explanatory artifacts.
6. Reduce malformed patterns:
   - no arbitrary field reordering,
   - no unnecessary CRLF separators inside a binary message,
   - no excessive zero padding,
   - no obviously inconsistent length relation if a shorter coherent arrangement is available from the provided bytes or text.
7. Preserve likely location, order, and length relations as conservatively as possible from the provided plans, structure, and preliminary sequences.
8. If you cannot prove a longer packet layout from the provided evidence, prefer a shorter coherent sequence over padded filler.
9. The `explanation` field must briefly describe only how you refined the preliminary sequence; do not claim protocol validity you cannot infer.

Return only a JSON object matching the required schema.
"""


def _normalize_surface_for_corridor(protocol: str, surface: str) -> str:
    normalized = str(surface or "").strip()
    if not normalized:
        return ""
    if protocol.upper() == "RTSP":
        normalized = re.sub(r"^rtsp://[^/]+", "", normalized)
        normalized = normalized.split("?", 1)[0].rstrip("/")
        normalized = re.sub(r"/track\d+$", "", normalized)
        return normalized or "/"
    if protocol.upper() == "HTTP":
        normalized = normalized.split("?", 1)[0].rstrip("/")
        return normalized or "/"
    return normalized


def _surfaces_are_corridor_compatible(protocol: str, left: str, right: str) -> bool:
    if not left or not right:
        return False
    if left == right:
        return True
    if protocol.upper() in {"RTSP", "HTTP"}:
        return left.startswith(right + "/") or right.startswith(left + "/")
    return False


def _choose_random_value(
    rng: random.Random,
    usage_history: Dict[str, Any],
    surface: str,
    field_name: str,
    values: TypingSequence[str],
    locally_used_values: Optional[TypingSequence[str]] = None,
) -> Optional[str]:
    normalized_values = [
        str(value).strip()
        for value in values
        if str(value).strip()
    ]
    if not normalized_values:
        return None

    used_values = set(get_used_values_for_surface_field(usage_history, surface, field_name))
    used_values.update(str(value).strip() for value in (locally_used_values or []) if str(value).strip())
    candidates = [value for value in normalized_values if value not in used_values]
    if not candidates:
        candidates = list(normalized_values)
    return rng.choice(candidates)


def _build_surface_candidates(
    implementation_metadata: Optional[Dict[str, Any]],
    type_sequence: List[str],
) -> Dict[str, List[Dict[str, Any]]]:
    if not isinstance(implementation_metadata, dict):
        return {}

    responses = implementation_metadata.get("responses", [])
    if not isinstance(responses, list):
        return {}

    candidates_by_type: Dict[str, List[Dict[str, Any]]] = {}
    for message_type in type_sequence:
        matching_candidates: List[Dict[str, Any]] = []
        for response in responses:
            if not isinstance(response, dict):
                continue
            if str(response.get("message_type", "")).strip() != message_type:
                continue
            for input_surface in response.get("input_surfaces", []):
                if not isinstance(input_surface, dict):
                    continue
                surface = str(input_surface.get("surface", "")).strip()
                if not surface:
                    continue
                matching_candidates.append(
                    {
                        "message_type": message_type,
                        "surface": surface,
                        "parameters": input_surface.get("parameters", {}),
                    }
                )
        if matching_candidates:
            candidates_by_type[message_type] = matching_candidates
    return candidates_by_type


def _sample_surface_candidate(
    protocol: str,
    rng: random.Random,
    message_type: str,
    candidates: List[Dict[str, Any]],
    current_corridor: str,
    used_surfaces: Dict[str, int],
) -> Tuple[Optional[Dict[str, Any]], str]:
    if not candidates:
        return None, current_corridor

    compatible_candidates = []
    for candidate in candidates:
        candidate_key = _normalize_surface_for_corridor(protocol, candidate.get("surface", ""))
        if current_corridor and _surfaces_are_corridor_compatible(protocol, current_corridor, candidate_key):
            compatible_candidates.append(candidate)

    candidate_pool = compatible_candidates or candidates
    shuffled_pool = list(candidate_pool)
    rng.shuffle(shuffled_pool)
    shuffled_pool.sort(key=lambda candidate: used_surfaces.get(candidate.get("surface", ""), 0))
    selected = shuffled_pool[0]
    selected_key = _normalize_surface_for_corridor(protocol, selected.get("surface", ""))
    next_corridor = current_corridor
    if not current_corridor or not _surfaces_are_corridor_compatible(protocol, current_corridor, selected_key):
        next_corridor = selected_key
    return selected, next_corridor


def _extract_selected_fields(
    protocol: str,
    rng: random.Random,
    surface: str,
    parameters: Dict[str, Any],
    usage_history: Dict[str, Any],
    local_used_values: Dict[str, Dict[str, List[str]]],
) -> Tuple[Dict[str, str], Dict[str, str]]:
    selected_fields: Dict[str, str] = {}
    selected_wire_fields: Dict[str, str] = {}
    if not isinstance(parameters, dict):
        return selected_fields, selected_wire_fields

    for slot_name in PARAMETER_CANDIDATE_SLOTS:
        slot_items = parameters.get(slot_name, [])
        if not isinstance(slot_items, list):
            continue
        for slot_item in slot_items:
            if not isinstance(slot_item, dict):
                continue
            field_name = str(slot_item.get("name", "")).strip()
            if not field_name:
                continue
            value = _choose_random_value(
                rng,
                usage_history,
                surface,
                field_name,
                slot_item.get("values", []),
                local_used_values.get(surface, {}).get(field_name, []),
            )
            wire_value = _choose_random_value(
                rng,
                usage_history,
                surface,
                field_name,
                slot_item.get("wire_values", []) or [],
                local_used_values.get(surface, {}).get(field_name + "::wire", []),
            )
            if value is not None:
                selected_fields[field_name] = value
            if wire_value is not None:
                selected_wire_fields[field_name] = wire_value

    if protocol.upper() == "RTSP":
        selected_fields.pop("CSeq", None)
        selected_fields.pop("Session", None)
        selected_wire_fields.pop("CSeq", None)
        selected_wire_fields.pop("Session", None)
    return selected_fields, selected_wire_fields


def _apply_rtsp_bindings(
    rng: random.Random,
    plan_messages: List[Dict[str, Any]],
    usage_history: Dict[str, Any],
) -> None:
    cseq_candidates: List[List[int]] = []
    cseq_indices: List[int] = []
    session_candidates: List[List[str]] = []
    session_indices: List[int] = []

    for index, message_plan in enumerate(plan_messages):
        parameters = message_plan.get("parameters", {})
        if not isinstance(parameters, dict):
            continue
        for slot_items in parameters.values():
            if not isinstance(slot_items, list):
                continue
            for slot_item in slot_items:
                if not isinstance(slot_item, dict):
                    continue
                name = str(slot_item.get("name", "")).strip().lower()
                values = [
                    str(value).strip()
                    for value in slot_item.get("values", [])
                    if str(value).strip()
                ]
                if name == "cseq":
                    numeric_values = []
                    for value in values:
                        if value.isdigit():
                            numeric_values.append(int(value))
                    if numeric_values:
                        cseq_indices.append(index)
                        cseq_candidates.append(sorted(set(numeric_values)))
                elif name == "session" and values:
                    session_indices.append(index)
                    session_candidates.append(values)

    if cseq_candidates:
        chosen_chain: List[int] = []
        previous = None
        for candidate_values in cseq_candidates:
            valid_values = [value for value in candidate_values if previous is None or value > previous]
            if not valid_values:
                valid_values = list(candidate_values)
            chosen = rng.choice(valid_values)
            chosen_chain.append(chosen)
            previous = chosen
        for index, cseq_value in zip(cseq_indices, chosen_chain):
            plan_messages[index]["selected_fields"]["CSeq"] = str(cseq_value)

    if session_candidates:
        common_sessions = set(session_candidates[0])
        for candidate_values in session_candidates[1:]:
            common_sessions &= set(candidate_values)
        if common_sessions:
            selected_session = rng.choice(sorted(common_sessions))
        else:
            flattened_sessions = []
            for candidate_values in session_candidates:
                for value in candidate_values:
                    if value not in flattened_sessions:
                        flattened_sessions.append(value)
            selected_session = flattened_sessions[0] if flattened_sessions else None
        if selected_session:
            for index in session_indices:
                plan_messages[index]["selected_fields"]["Session"] = selected_session


def _build_plan_signature(plan_messages: List[Dict[str, Any]]) -> Tuple[Any, ...]:
    signature_items = []
    for message_plan in plan_messages:
        selected_fields = tuple(sorted(
            (field_name, field_value)
            for field_name, field_value in message_plan.get("selected_fields", {}).items()
        ))
        selected_wire_fields = tuple(sorted(
            (field_name, field_value)
            for field_name, field_value in message_plan.get("selected_wire_fields", {}).items()
        ))
        signature_items.append(
            (
                message_plan.get("message_type"),
                message_plan.get("surface"),
                selected_fields,
                selected_wire_fields,
            )
        )
    return tuple(signature_items)


def _sample_generation_plans(
    protocol: str,
    type_sequence: List[str],
    implementation_metadata: Optional[Dict[str, Any]],
    usage_history: Optional[Dict[str, Any]] = None,
    max_plans: int = MAX_PLANS_PER_SEQUENCE,
    max_attempts: int = MAX_PLAN_ATTEMPTS_PER_SEQUENCE,
) -> List[Dict[str, Any]]:
    usage_history = usage_history or {}
    candidates_by_type = _build_surface_candidates(implementation_metadata, type_sequence)
    if any(message_type not in candidates_by_type for message_type in type_sequence):
        return []

    used_surfaces = dict((usage_history.get("interaction_surfaces") or {}))
    local_used_values: Dict[str, Dict[str, List[str]]] = {}
    used_plan_signatures = set()
    rng = random.Random()
    plans: List[Dict[str, Any]] = []

    for _ in range(max_attempts):
        corridor = ""
        plan_messages: List[Dict[str, Any]] = []
        failed = False

        for message_type in type_sequence:
            selected_surface_candidate, corridor = _sample_surface_candidate(
                protocol,
                rng,
                message_type,
                candidates_by_type.get(message_type, []),
                corridor,
                used_surfaces,
            )
            if selected_surface_candidate is None:
                failed = True
                break

            surface = str(selected_surface_candidate.get("surface", "")).strip()
            parameters = selected_surface_candidate.get("parameters", {})
            selected_fields, selected_wire_fields = _extract_selected_fields(
                protocol,
                rng,
                surface,
                parameters,
                usage_history,
                local_used_values,
            )
            plan_messages.append(
                {
                    "message_type": message_type,
                    "surface": surface,
                    "parameters": parameters,
                    "selected_fields": selected_fields,
                    "selected_wire_fields": selected_wire_fields,
                }
            )

        if failed or not plan_messages:
            continue

        if protocol.upper() == "RTSP":
            _apply_rtsp_bindings(rng, plan_messages, usage_history)

        signature = _build_plan_signature(plan_messages)
        if signature in used_plan_signatures:
            continue

        used_plan_signatures.add(signature)
        for message_plan in plan_messages:
            surface = message_plan.get("surface", "")
            used_surfaces[surface] = used_surfaces.get(surface, 0) + 1
            surface_history = local_used_values.setdefault(surface, {})
            for field_name, field_value in message_plan.get("selected_fields", {}).items():
                field_history = surface_history.setdefault(field_name, [])
                if field_value not in field_history:
                    field_history.append(field_value)
            for field_name, field_value in message_plan.get("selected_wire_fields", {}).items():
                field_history = surface_history.setdefault(field_name + "::wire", [])
                if field_value not in field_history:
                    field_history.append(field_value)

        plans.append(
            {
                "plan_id": len(plans) + 1,
                "messages": [
                    {
                        "message_type": message_plan["message_type"],
                        "surface": message_plan["surface"],
                        "selected_fields": dict(sorted(message_plan["selected_fields"].items())),
                        "selected_wire_fields": dict(sorted(message_plan["selected_wire_fields"].items())),
                    }
                    for message_plan in plan_messages
                ],
            }
        )
        if len(plans) >= max_plans:
            break

    return plans


def _format_generation_plans(plans: List[Dict[str, Any]]) -> str:
    lines: List[str] = []
    for plan in plans:
        lines.append(
            json.dumps(
                {
                    "plan_id": plan.get("plan_id"),
                    "messages": plan.get("messages", []),
                },
                ensure_ascii=False,
            )
        )
    return "\n".join(lines)


def _bytes_to_hex_string(data: bytes) -> str:
    return " ".join(f"0x{byte:02x}" for byte in data)


def _format_preliminary_sequences(test_case: Dict[str, Any]) -> str:
    formatted_sequences: List[str] = []
    for sequence in test_case.get("sequences", []):
        messages: List[Dict[str, str]] = []
        for message in sequence.get("messages", []):
            rendered_raw = convert_message_to_binary(message.get("message", ""))
            messages.append(
                {
                    "original_message": message.get("message", ""),
                    "rendered_raw_hex": _bytes_to_hex_string(rendered_raw),
                }
            )
        formatted_sequences.append(
            json.dumps(
                {
                    "sequenceId": sequence.get("sequenceId"),
                    "messages": messages,
                },
                ensure_ascii=False,
            )
        )
    return "\n".join(formatted_sequences)


def _normalize_for_match(value: str) -> str:
    return str(value or "").strip().lower()


def _count_selected_value_matches(message_text: str, selected_values: Dict[str, str]) -> int:
    normalized_message = _normalize_for_match(message_text)
    match_count = 0
    for field_value in selected_values.values():
        normalized_value = _normalize_for_match(field_value)
        if normalized_value and normalized_value in normalized_message:
            match_count += 1
    return match_count


def _message_needs_refinement(plan_message: Dict[str, Any], output_message: str) -> bool:
    selected_fields = plan_message.get("selected_fields", {}) or {}
    selected_wire_fields = plan_message.get("selected_wire_fields", {}) or {}
    output_message = output_message or ""

    selected_count = len(selected_fields)
    selected_wire_count = len(selected_wire_fields)
    matched_selected_count = _count_selected_value_matches(output_message, selected_fields)
    matched_wire_count = _count_selected_value_matches(output_message, selected_wire_fields)

    if selected_wire_count > 0 and matched_wire_count == 0:
        return True

    if selected_count <= 0:
        return False

    if selected_count <= 2:
        return matched_selected_count == 0 and matched_wire_count == 0

    required_selected_matches = (selected_count + 1) // 2
    return matched_selected_count < required_selected_matches and matched_wire_count == 0


def _should_refine_test_case(
    generation_plans: List[Dict[str, Any]],
    preliminary_test_case: Dict[str, Any],
) -> bool:
    sequences = preliminary_test_case.get("sequences", [])
    if not isinstance(sequences, list):
        return True

    for plan, sequence in zip(generation_plans, sequences):
        plan_messages = plan.get("messages", [])
        output_messages = sequence.get("messages", []) if isinstance(sequence, dict) else []
        if len(plan_messages) != len(output_messages):
            return True
        for plan_message, output_message in zip(plan_messages, output_messages):
            output_text = output_message.get("message", "") if isinstance(output_message, dict) else ""
            if _message_needs_refinement(plan_message, output_text):
                return True
    return False


def using_llm(prompt: str, persist_raw_output: bool = True) -> Optional[TestCase]:
    client = OpenAI()
    try:
        completion = client.beta.chat.completions.parse(
            model=MODEL,
            temperature=0.2,
            messages=[
                {
                    "role": "system",
                    "content": "You generate protocol-valid client-to-server testcase sequences.",
                },
                {"role": "user", "content": prompt},
            ],
            response_format=TestCase,
            timeout=30,
        )
        response = completion.choices[0].message.parsed

        index = 0
        os.makedirs(os.path.join(LLM_RESULT_DIR, "6_testcases"), exist_ok=True)
        while os.path.exists(os.path.join(LLM_RESULT_DIR, "6_testcases", f"response_{index}.json")):
            index += 1
        protocol_file = os.path.join(LLM_RESULT_DIR, "6_testcases", f"response_{index}.json")
        with open(protocol_file, "w", encoding="utf-8") as f:
            json.dump(completion.model_dump(), f, indent=4, ensure_ascii=False)
        raw_output_dir = get_raw_output_dir()
        if persist_raw_output and raw_output_dir:
            save_llm_response_testcase(response.model_dump(), raw_output_dir)
        return response
    except Exception as e:
        print(f"Error processing protocol: {e}")
        return None


def _refine_test_case(
    protocol: str,
    type_sequence: List[str],
    specialized_structure: Dict[str, Any],
    generation_plans: List[Dict[str, Any]],
    preliminary_test_case: Dict[str, Any],
) -> Optional[TestCase]:
    sequence = "\n".join(f"{index}. {message_type}" for index, message_type in enumerate(type_sequence, start=1))
    structure = _format_structure(type_sequence, specialized_structure)
    formatted_generation_plans = _format_generation_plans(generation_plans)
    formatted_preliminary_sequences = _format_preliminary_sequences(preliminary_test_case)

    prompt = (
        REFINEMENT_PROMPT.replace("[PROTOCOL]", protocol)
        .replace("[GENERATION_PLANS]", formatted_generation_plans)
        .replace("[SEQUENCE]", sequence)
        .replace("[STRUCTURE]", structure)
        .replace("[PRELIMINARY_SEQUENCES]", formatted_preliminary_sequences)
    )
    return using_llm(prompt, persist_raw_output=False)


def _format_structure(type_sequence: List[str], specialized_structure: Dict[str, Any]) -> str:
    filtered_structure: Dict[str, Any] = {}
    for message_type in type_sequence:
        filtered_structure[message_type] = specialized_structure.get(message_type, {})
    return json.dumps(filtered_structure, ensure_ascii=False, indent=2)


def get_test_case(
    protocol: str,
    type_sequence: List[str],
    specialized_structure: Dict[str, Any],
    implementation_metadata: Optional[Dict[str, Any]] = None,
    usage_history: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    generation_plans = _sample_generation_plans(
        protocol,
        type_sequence,
        implementation_metadata,
        usage_history,
    )
    if not generation_plans:
        raise Exception(f"No generation plans available for {protocol}: {type_sequence}")

    sequence = "\n".join(f"{index}. {message_type}" for index, message_type in enumerate(type_sequence, start=1))
    structure = _format_structure(type_sequence, specialized_structure)
    formatted_generation_plans = _format_generation_plans(generation_plans)

    prompt = (
        MESSAGE_PROMPT.replace("[PROTOCOL]", protocol)
        .replace("[GENERATION_PLANS]", formatted_generation_plans)
        .replace("[SEQUENCE]", sequence)
        .replace("[STRUCTURE]", structure)
        .replace("[NUMBER]", str(len(generation_plans)))
    )

    response = None
    for _ in range(LLM_RETRY):
        response = using_llm(prompt, persist_raw_output=False)
        if response is not None:
            break

    if response is None:
        raise Exception(f"Failed to generate testcase sequence for {protocol}: {type_sequence}")

    response_dict = response.model_dump()
    if _should_refine_test_case(generation_plans, response_dict):
        refined_response = None
        for _ in range(LLM_RETRY):
            refined_response = _refine_test_case(
                protocol,
                type_sequence,
                specialized_structure,
                generation_plans,
                response_dict,
            )
            if refined_response is not None:
                break
        if refined_response is not None:
            response_dict = refined_response.model_dump()

    raw_output_dir = get_raw_output_dir()
    if raw_output_dir:
        save_llm_response_testcase(response_dict, raw_output_dir)
    return response_dict


def get_test_cases(
    protocol: str,
    message_sequences: Dict[str, Any],
    specialized_structures: Dict[str, Any],
    implementation_metadata: Optional[Dict[str, Any]] = None,
    usage_history: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    test_cases: Dict[str, Any] = {}
    for sequence in message_sequences.get("sequences", []):
        try:
            print(f"Processing message sequence: {sequence['sequenceId']}")
            test_cases[sequence["sequenceId"]] = get_test_case(
                protocol,
                sequence["type_sequence"],
                specialized_structures,
                implementation_metadata,
                usage_history,
            )
        except Exception as e:
            print(f"Error processing message sequence {sequence['sequenceId']} in {protocol}: {e}")

    os.makedirs(TESTCASE_OUTPUT_DIR, exist_ok=True)
    idx = 1
    file_path = os.path.join(TESTCASE_OUTPUT_DIR, f"{protocol.lower()}_testcases_{idx}.json")
    while os.path.exists(file_path):
        idx += 1
        file_path = os.path.join(TESTCASE_OUTPUT_DIR, f"{protocol.lower()}_testcases_{idx}.json")
    with open(file_path, "w", encoding="utf-8") as f:
        json.dump(test_cases, f, indent=4, ensure_ascii=False)
    print(f"Saved results for {protocol} to {file_path}")

    os.makedirs(LLM_RESULT_DIR, exist_ok=True)
    idx = 1
    file_path = os.path.join(LLM_RESULT_DIR, f"4_{protocol.lower()}_testcases_{idx}.json")
    while os.path.exists(file_path):
        idx += 1
        file_path = os.path.join(LLM_RESULT_DIR, f"4_{protocol.lower()}_testcases_{idx}.json")
    with open(file_path, "w", encoding="utf-8") as f:
        json.dump(test_cases, f, indent=4, ensure_ascii=False)
    print(f"Saved results for {protocol} to {file_path}")

    return test_cases
