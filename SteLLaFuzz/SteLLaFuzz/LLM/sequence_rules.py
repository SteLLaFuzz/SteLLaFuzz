import json
import os

from typing import Dict, List, Optional, Sequence, Tuple
from pydantic import BaseModel
from openai import OpenAI
from utility.utility import MODEL, LLM_RETRY, LLM_RESULT_DIR

SEQUENCE_RULE_OUTPUT_DIR = "sequence_rule_results"
SEQUENCE_RULE_REPORT_DIR = "sequence_rule_reports"


class MessageTransitionRule(BaseModel):
    message: str
    allowed_as_start: bool = False
    allow_only_as_first: bool = False
    disallow_repeat: bool = False
    requires_any_prior: Optional[List[str]] = None
    requires_all_prior: Optional[List[str]] = None
    disallowed_immediate_predecessors: Optional[List[str]] = None
    should_not_appear: bool = False
    rationale: Optional[str] = None


class ProtocolTransitionRules(BaseModel):
    protocol: str
    allowed_starts: List[str]
    rules: List[MessageTransitionRule]
    explanation: str


RULE_PROMPT = """\
You are a network protocol expert with deep understanding of [PROTOCOL].
Your task is to derive protocol-level client-side message transition rules for sequence generation.

You are provided with:
- entry message types proposed by an earlier stage:
[ENTRY_TYPES]
- the full list of client-originated message types:
[ALL_TYPES]

Your job is to produce protocol-level progression rules for client-to-server sequencing.
This stage must preserve useful message diversity while still preventing clearly implausible starts and transitions.

Requirements:
1. Work at the protocol level only. Do not use target-specific implementation quirks.
2. Use only the provided message types. Do not invent new names.
3. `allowed_starts` must be a subset of the provided entry message types.
4. Treat `allowed_starts` as safe initial anchors for a fresh sequence, not as a list of all messages that a client might theoretically send.
5. If a message could be client-originated but usually depends on prior context, do NOT put it in `allowed_starts`. Instead, keep it available later in the sequence by using `requires_any_prior`, `requires_all_prior`, or `disallowed_immediate_predecessors`.
6. Use `allow_only_as_first: true` when a message is suitable as an initial anchor but should not reappear later in the same sequence.
7. Use `disallow_repeat: true` when a message should not appear more than once in the same sequence.
8. Use `should_not_appear: true` only for messages that should be excluded from the generated client progression entirely, even as a later follow-up. Do NOT use `should_not_appear` merely because a message is not a valid start, is context-dependent, or is uncommon.
9. Preserve downstream diversity whenever a message is a plausible later client-originated follow-up. Prefer keeping such messages available with explicit prerequisites rather than excluding them.
10. When a message clearly depends on multiple prior milestones, prefer `requires_all_prior` over `requires_any_prior`.
11. Use `requires_any_prior` only when the protocol genuinely permits multiple alternative prerequisites.
12. Use `disallowed_immediate_predecessors` when a direct adjacency would usually indicate an implausible or disallowed progression, without over-pruning later diversity.
13. If uncertain whether a message is a plausible later follow-up, prefer allowing it with prerequisites over excluding it entirely.
14. These rules are for protocol-level legality and plausible progression, not for target-specific realism.

Additional guidance:
- Messages that are completion-like, confirmation-like, context-heavy, or typically triggered only after a narrow prior exchange should usually not be starts.
- If a message is only valid after session setup, authentication, negotiation, or a prior mode switch, encode that dependency explicitly instead of excluding the message.
- Avoid broad starts. A small `allowed_starts` set is preferred when uncertain.
- Prefer `allow_only_as_first` over `should_not_appear` when the message is a valid opener but usually should not reappear later.
- Prefer `disallow_repeat` when repetition itself is the issue rather than full exclusion.
- The goal is not maximum permissiveness, but it is also not minimum message variety. Keep later-stage client-originated messages available whenever they are plausible with the right prerequisites.
- If an allowed start is useful as a repeated probe or capability query, do not force `allow_only_as_first: true`; let repetition remain available unless the protocol clearly forbids it.

Return only the final JSON object in the provided schema.
"""


RULE_REPAIR_PROMPT = """\
You are a network protocol expert with deep understanding of [PROTOCOL].
You are given an existing protocol-level client-side transition rule set plus a reachability report.

Your task is to minimally repair the rule set so that:
- fewer allowed starts are orphaned
- fewer non-excluded message types are unreachable within the sequence length budget

You are provided with:
- entry message types proposed by an earlier stage:
[ENTRY_TYPES]
- the full list of client-originated message types:
[ALL_TYPES]
- the current rule set:
[CURRENT_RULES]
- the current orphan / reachability report:
[ORPHAN_REPORT]

Requirements:
1. Keep the repair minimal. Preserve rules that do not contribute to the reported orphaning or unreachability.
2. Work at the protocol level only. Do not use target-specific assumptions.
3. Use only the provided message types. Do not invent new names.
4. Do not broaden `allowed_starts` unless the current report strongly indicates that a repaired downstream path requires it.
5. Prefer fixing orphaned starts and unreachable non-excluded messages by adjusting:
   - `allow_only_as_first`
   - `requires_any_prior`
   - `requires_all_prior`
   - `disallowed_immediate_predecessors`
   rather than by excluding additional message types.
6. Keep `should_not_appear: true` only for messages that truly should be excluded entirely.
7. If a message remains unreachable for sound protocol reasons, keep it restricted and explain why.
8. Return the full repaired rule set in the same schema as the original rule output.

Return only the final JSON object in the provided schema.
"""


def using_llm(prompt: str) -> ProtocolTransitionRules:
    client = OpenAI()
    try:
        completion = client.beta.chat.completions.parse(
            model=MODEL,
            temperature=0.1,
            messages=[
                {"role": "system", "content": "You derive protocol-level client-side message transition rules."},
                {"role": "user", "content": prompt},
            ],
            response_format=ProtocolTransitionRules,
            timeout=30,
        )
        response = completion.choices[0].message.parsed

        index = 0
        os.makedirs(os.path.join(LLM_RESULT_DIR, "2_sequence_rules"), exist_ok=True)
        while os.path.exists(os.path.join(LLM_RESULT_DIR, "2_sequence_rules", f"response_{index}.json")):
            index += 1
        protocol_file = os.path.join(LLM_RESULT_DIR, "2_sequence_rules", f"response_{index}.json")
        with open(protocol_file, "w", encoding="utf-8") as f:
            json.dump(completion.model_dump(), f, indent=4, ensure_ascii=False)
        return response
    except Exception as e:
        print(f"Error generating sequence rules: {e}")
        return None


def using_rule_repair_llm(prompt: str) -> ProtocolTransitionRules:
    client = OpenAI()
    try:
        completion = client.beta.chat.completions.parse(
            model=MODEL,
            temperature=0.1,
            messages=[
                {"role": "system", "content": "You minimally repair protocol-level client-side transition rules using a reachability report."},
                {"role": "user", "content": prompt},
            ],
            response_format=ProtocolTransitionRules,
            timeout=30,
        )
        response = completion.choices[0].message.parsed

        index = 0
        os.makedirs(os.path.join(LLM_RESULT_DIR, "2_sequence_rule_repairs"), exist_ok=True)
        while os.path.exists(os.path.join(LLM_RESULT_DIR, "2_sequence_rule_repairs", f"response_{index}.json")):
            index += 1
        protocol_file = os.path.join(LLM_RESULT_DIR, "2_sequence_rule_repairs", f"response_{index}.json")
        with open(protocol_file, "w", encoding="utf-8") as f:
            json.dump(completion.model_dump(), f, indent=4, ensure_ascii=False)
        return response
    except Exception as e:
        print(f"Error repairing sequence rules: {e}")
        return None


def _build_type_lists(message_types: Dict[str, object]) -> Tuple[List[str], List[str]]:
    entry_types = [
        message_type["name"]
        for message_type in message_types.get("client_to_server_messages", [])
        if isinstance(message_type, dict) and message_type.get("name")
    ]
    all_types_source = message_types.get("all_client_to_server_messages")
    if not isinstance(all_types_source, list) or not all_types_source:
        all_types_source = message_types.get("client_to_server_messages", [])
    all_types = [
        message_type["name"]
        for message_type in all_types_source
        if isinstance(message_type, dict) and message_type.get("name")
    ]
    return entry_types, all_types


def _should_exclude_message(rule_set: Dict[str, object], message: str) -> bool:
    for rule in rule_set.get("rules", []) or []:
        if isinstance(rule, dict) and rule.get("message") == message:
            return bool(rule.get("should_not_appear"))
    return False


def analyze_rule_reachability(
    protocol: str,
    rule_set: Dict[str, object],
    fallback_starts: Sequence[str],
    allowed_messages: Sequence[str],
    max_length: int = 5,
) -> Dict[str, object]:
    allowed_starts = list(rule_set.get("allowed_starts") or fallback_starts)
    reachable_messages = set()
    reachable_starts = set()
    starts_with_continuation = set()
    visited_prefixes = set()
    frontier: List[Tuple[str, ...]] = []
    sample_paths_by_start: Dict[str, List[List[str]]] = {}

    for start in allowed_starts:
        is_valid, _ = validate_type_sequence_with_rules([start], rule_set, fallback_starts, allowed_messages)
        if not is_valid:
            continue
        prefix = (start,)
        frontier.append(prefix)
        visited_prefixes.add(prefix)
        reachable_messages.add(start)
        reachable_starts.add(start)

    while frontier:
        prefix = frontier.pop(0)
        if len(prefix) >= max_length:
            continue
        for message in allowed_messages:
            candidate = list(prefix) + [message]
            is_valid, _ = validate_type_sequence_with_rules(candidate, rule_set, fallback_starts, allowed_messages)
            if not is_valid:
                continue
            candidate_tuple = tuple(candidate)
            if candidate_tuple in visited_prefixes:
                continue
            visited_prefixes.add(candidate_tuple)
            frontier.append(candidate_tuple)
            reachable_messages.update(candidate)
            reachable_starts.add(candidate[0])
            starts_with_continuation.add(candidate[0])
            sample_paths_by_start.setdefault(candidate[0], [])
            if len(sample_paths_by_start[candidate[0]]) < 3:
                sample_paths_by_start[candidate[0]].append(candidate)

    non_excluded_messages = [
        message for message in allowed_messages
        if not _should_exclude_message(rule_set, message)
    ]
    unreachable_messages = [
        message for message in non_excluded_messages
        if message not in reachable_messages
    ]
    orphaned_allowed_starts = [
        start for start in allowed_starts
        if start not in starts_with_continuation
    ]

    report = {
        "protocol": protocol,
        "max_length": max_length,
        "allowed_starts": allowed_starts,
        "reachable_starts": sorted(reachable_starts),
        "orphaned_allowed_starts": orphaned_allowed_starts,
        "reachable_messages": sorted(reachable_messages),
        "unreachable_messages": unreachable_messages,
        "sample_paths_by_start": sample_paths_by_start,
    }
    os.makedirs(SEQUENCE_RULE_REPORT_DIR, exist_ok=True)
    report_path = os.path.join(SEQUENCE_RULE_REPORT_DIR, f"{protocol.lower()}_reachability_report.json")
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=4, ensure_ascii=False)
    return report


def _rule_report_score(report: Dict[str, object]) -> Tuple[int, int]:
    orphan_count = len(report.get("orphaned_allowed_starts", []))
    unreachable_count = len(report.get("unreachable_messages", []))
    return orphan_count, unreachable_count


def maybe_repair_transition_rules(
    protocol: str,
    rule_set: Dict[str, object],
    fallback_starts: Sequence[str],
    allowed_messages: Sequence[str],
) -> Dict[str, object]:
    initial_report = analyze_rule_reachability(protocol, rule_set, fallback_starts, allowed_messages)
    if not initial_report.get("orphaned_allowed_starts") and not initial_report.get("unreachable_messages"):
        return rule_set

    prompt = (
        RULE_REPAIR_PROMPT.replace("[PROTOCOL]", protocol)
        .replace("[ENTRY_TYPES]", "\n".join(f"- {message}" for message in fallback_starts))
        .replace("[ALL_TYPES]", "\n".join(f"- {message}" for message in allowed_messages))
        .replace("[CURRENT_RULES]", json.dumps(rule_set, indent=2, ensure_ascii=False))
        .replace("[ORPHAN_REPORT]", json.dumps(initial_report, indent=2, ensure_ascii=False))
    )

    repaired = None
    for _ in range(1):
        repaired = using_rule_repair_llm(prompt)
        if repaired is not None:
            break

    if repaired is None:
        return rule_set

    repaired_rule_set = repaired.model_dump()
    repaired_report = analyze_rule_reachability(protocol, repaired_rule_set, fallback_starts, allowed_messages)
    if _rule_report_score(repaired_report) < _rule_report_score(initial_report):
        print(
            f"Applied repaired transition rules for {protocol}: "
            f"orphans {len(initial_report.get('orphaned_allowed_starts', []))}->{len(repaired_report.get('orphaned_allowed_starts', []))}, "
            f"unreachable {len(initial_report.get('unreachable_messages', []))}->{len(repaired_report.get('unreachable_messages', []))}"
        )
        return repaired_rule_set

    return rule_set


def get_transition_rules(protocol: str, message_types: Dict[str, object]) -> Dict[str, object]:
    file_path = os.path.join(SEQUENCE_RULE_OUTPUT_DIR, f"{protocol.lower()}_transition_rules.json")
    if os.path.exists(file_path):
        with open(file_path, "r", encoding="utf-8") as f:
            cached = json.load(f)
        print(f"Loaded cached transition rules for {protocol} from {file_path}")
        return cached

    entry_types, all_types = _build_type_lists(message_types)
    prompt = (
        RULE_PROMPT.replace("[PROTOCOL]", protocol)
        .replace("[ENTRY_TYPES]", "\n".join(f"- {message}" for message in entry_types))
        .replace("[ALL_TYPES]", "\n".join(f"- {message}" for message in all_types))
    )

    response = None
    for _ in range(1):
        response = using_llm(prompt)
        if response is not None:
            break

    if response is None:
        raise Exception(f"Failed to generate transition rules for {protocol}")

    result = response.model_dump()
    result = maybe_repair_transition_rules(protocol, result, entry_types, all_types)
    os.makedirs(SEQUENCE_RULE_OUTPUT_DIR, exist_ok=True)
    with open(file_path, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=4, ensure_ascii=False)
    print(f"Saved transition rules for {protocol} to {file_path}")
    return result


def format_transition_rules_for_prompt(rule_set: Dict[str, object]) -> str:
    allowed_starts = rule_set.get("allowed_starts", []) or []
    rules = rule_set.get("rules", []) or []

    lines = ["Allowed starts:"]
    if allowed_starts:
        lines.extend(f"- {message}" for message in allowed_starts)
    else:
        lines.append("- none provided")

    lines.append("")
    lines.append("Per-message rules:")
    if not rules:
        lines.append("- no explicit rules provided")
        return "\n".join(lines)

    for rule in rules:
        if not isinstance(rule, dict):
            continue
        message = rule.get("message", "<unknown>")
        parts = [f"- {message}"]
        if rule.get("allowed_as_start"):
            parts.append("may_start")
        if rule.get("allow_only_as_first"):
            parts.append("allow_only_as_first")
        if rule.get("disallow_repeat"):
            parts.append("disallow_repeat")
        if rule.get("should_not_appear"):
            parts.append("should_not_appear")
        if rule.get("requires_any_prior"):
            parts.append("requires_any_prior=" + ", ".join(rule["requires_any_prior"]))
        if rule.get("requires_all_prior"):
            parts.append("requires_all_prior=" + ", ".join(rule["requires_all_prior"]))
        if rule.get("disallowed_immediate_predecessors"):
            parts.append(
                "disallowed_immediate_predecessors=" + ", ".join(rule["disallowed_immediate_predecessors"])
            )
        lines.append(" | ".join(parts))

    return "\n".join(lines)


def filter_sequences_with_rules(
    sequences: List[object],
    rule_set: Dict[str, object],
    fallback_starts: Sequence[str],
    allowed_messages: Sequence[str],
) -> Tuple[List[object], List[str]]:
    rules_by_message = {}
    for rule in rule_set.get("rules", []) or []:
        if isinstance(rule, dict) and rule.get("message"):
            rules_by_message[rule["message"]] = rule

    allowed_starts = set(rule_set.get("allowed_starts") or fallback_starts)
    allowed_message_set = set(allowed_messages)

    valid_sequences: List[object] = []
    invalid_reasons: List[str] = []
    for sequence in sequences:
        type_sequence = getattr(sequence, "type_sequence", None)
        if not isinstance(type_sequence, list) or not type_sequence:
            invalid_reasons.append(f"{getattr(sequence, 'sequenceId', 'unknown')}: missing type_sequence")
            continue

        is_valid, reason = _validate_sequence(type_sequence, rules_by_message, allowed_starts, allowed_message_set)
        if is_valid:
            valid_sequences.append(sequence)
        else:
            invalid_reasons.append(f"{getattr(sequence, 'sequenceId', 'unknown')}: {reason}")

    return valid_sequences, invalid_reasons


def validate_type_sequence_with_rules(
    type_sequence: Sequence[str],
    rule_set: Dict[str, object],
    fallback_starts: Sequence[str],
    allowed_messages: Sequence[str],
) -> Tuple[bool, str]:
    rules_by_message = {}
    for rule in rule_set.get("rules", []) or []:
        if isinstance(rule, dict) and rule.get("message"):
            rules_by_message[rule["message"]] = rule

    allowed_starts = set(rule_set.get("allowed_starts") or fallback_starts)
    allowed_message_set = set(allowed_messages)
    return _validate_sequence(type_sequence, rules_by_message, allowed_starts, allowed_message_set)


def _validate_sequence(
    type_sequence: Sequence[str],
    rules_by_message: Dict[str, Dict[str, object]],
    allowed_starts: set,
    allowed_message_set: set,
) -> Tuple[bool, str]:
    if type_sequence[0] not in allowed_starts:
        return False, f"starts with disallowed message {type_sequence[0]}"

    seen = set()
    previous = None
    for index, message in enumerate(type_sequence):
        if message not in allowed_message_set:
            return False, f"contains unknown message {message}"

        rule = rules_by_message.get(message, {})
        if rule.get("should_not_appear"):
            return False, f"contains forbidden message {message}"
        if index > 0 and rule.get("allow_only_as_first"):
            return False, f"{message} is allowed only as the first message"
        if message in seen and rule.get("disallow_repeat"):
            return False, f"{message} may not repeat in the same sequence"
        if index == 0 and rule.get("allowed_as_start") is False and allowed_starts:
            # allowed_starts already governs the main decision; keep this as secondary consistency.
            if message not in allowed_starts:
                return False, f"{message} is not allowed as a start message"
        requires_any = rule.get("requires_any_prior") or []
        if requires_any and not any(candidate in seen for candidate in requires_any):
            return False, f"{message} is missing any required prior from {requires_any}"
        requires_all = rule.get("requires_all_prior") or []
        if requires_all and not all(candidate in seen for candidate in requires_all):
            return False, f"{message} is missing all required priors from {requires_all}"
        disallowed_predecessors = rule.get("disallowed_immediate_predecessors") or []
        if previous is not None and previous in disallowed_predecessors:
            return False, f"{message} cannot immediately follow {previous}"

        seen.add(message)
        previous = message

    return True, ""
