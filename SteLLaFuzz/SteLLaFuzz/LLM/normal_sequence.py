import os
import json

from typing import Dict, List
from pydantic import BaseModel
from openai import OpenAI
from LLM.sequence_rules import (
    filter_sequences_with_rules,
    format_transition_rules_for_prompt,
    get_transition_rules,
    validate_type_sequence_with_rules,
)
from utility.utility import MODEL, LLM_RETRY, LLM_RESULT_DIR

MESSAGE_SEQUENCE_OUTPUT_DIR = "message_sequence_results"


class Sequence(BaseModel):
    sequenceId: str
    type_sequence: List[str]


class SkeletonSequence(BaseModel):
    skeletonId: str
    type_sequence: List[str]


class ProtocolSequences(BaseModel):
    protocol: str
    sequences: List[Sequence]
    explanation: str


class ProtocolSkeletons(BaseModel):
    protocol: str
    skeletons: List[SkeletonSequence]
    explanation: str


SKELETON_PROMPT = """\
You are a network protocol expert with deep understanding of [PROTOCOL].
Your task is to generate progression skeletons for client-to-server communications in the [PROTOCOL] protocol.
The objective of this stage is not broad coverage yet. The objective is to propose plausible progression skeletons that start from entry message types and continue with reasonable follow-up client-originated message types.

You are provided with:
- entry message types that may legally start a sequence:
[ENTRY_TYPES]
- the full list of client-originated message types that may appear later in a sequence:
[ALL_TYPES]
- protocol-level transition rules:
[TRANSITION_RULES]

Please adhere to the following instructions:

1. **Generate Progression Skeletons:**
   - Create multiple progression skeletons using message types from the provided lists.
   - Each skeleton length must be between 2 and [SEQ_LENGTH], inclusive.
   - The first message of every skeleton MUST come from the allowed starts implied by the transition rules.
   - After the initial entry message, continue with later-stage or follow-up client-originated message types from the full list.
   - Prioritize plausible follow-up ordering over coverage maximization.
   - Obey the provided transition rules when deciding which messages may appear and what they may follow.
   - Prefer concise skeletons that represent a meaningful progression rather than arbitrary permutations.

2. **Use Only Provided Message Types:**
   - Every message type must exactly match one of the provided message types.
   - Do not invent new message names.

3. **Provide a Skeleton Rationale:**
   - In the "explanation" field, briefly explain why these skeletons represent plausible client-side progressions.

4. **Final Output Requirements:**
   - Do not include any extraneous text; only provide the final JSON output.
   - The output must be valid JSON, strictly adhering to the structure below.

5. **Final Output Structure:**
   ```json
   {
     "protocol": "[PROTOCOL]",
     "skeletons": [
       {
         "skeletonId": "A unique identifier for the skeleton",
         "type_sequence": [
           "Type of message 1",
           "Type of message 2",
           "Type of message 3"
         ]
       }
     ],
     "explanation": "A brief explanation of how these skeletons were constructed as plausible client-side progressions."
   }
   ```

Please generate the final progression skeletons strictly following the above instructions.
"""


EXPANSION_PROMPT = """\
You are a network protocol expert with deep understanding of [PROTOCOL].
Your task is to expand progression skeletons into final client-to-server message sequences for the [PROTOCOL] protocol.
The objective of this stage is to add coverage-oriented variation while preserving the intended progression of each skeleton.

You are provided with:
- entry message types that may legally start a sequence:
[ENTRY_TYPES]
- the full list of client-originated message types that may appear later in a sequence:
[ALL_TYPES]
- progression skeletons:
[SKELETONS]
- protocol-level transition rules:
[TRANSITION_RULES]

Please adhere to the following instructions:

1. **Expand Skeletons Into Final Sequences:**
   - Generate multiple final sequences of exact length [SEQ_LENGTH].
   - Every final sequence MUST start with an allowed start message from the transition rules.
   - Every final sequence MUST preserve the message order of one provided skeleton.
   - You may extend a skeleton with additional client-originated message types from the full list, including repetitions if useful for coverage.
   - Do not turn later-stage messages into fresh starting points.
   - Do not reorder a skeleton so that a later skeleton message appears before an earlier skeleton message.
   - Obey the provided transition rules when deciding which messages may appear and what they may follow.

2. **Coverage Variation:**
   - After preserving the skeleton progression, vary the surrounding or repeated follow-up messages to explore additional states and branches.
   - Prefer variations that still look like a continuation of the skeleton rather than arbitrary permutations.

3. **Use Only Provided Message Types:**
   - Every message type must exactly match one of the provided message types.
   - Do not invent new message names.

4. **Provide a Rationale:**
   - In the "explanation" field, briefly explain how the final sequences preserve the skeleton progressions while adding coverage-oriented variation.

5. **Final Output Requirements:**
   - Do not include any extraneous text; only provide the final JSON output.
   - The output must be valid JSON, strictly adhering to the structure below.

6. **Final Output Structure:**
   ```json
   {
     "protocol": "[PROTOCOL]",
     "sequences": [
       {
         "sequenceId": "A unique identifier for the sequence",
         "type_sequence": [
           "Type of message 1",
           "Type of message 2",
           "Type of message 3"
         ]
       }
     ],
     "explanation": "A brief explanation of how these sequences preserve the skeleton progressions while adding coverage-oriented variation."
   }
   ```

Please generate the final expanded sequences strictly following the above instructions.
"""


COVERAGE_REPAIR_PROMPT = """\
You are a network protocol expert with deep understanding of [PROTOCOL].
Your task is to generate a small number of additional client-to-server message sequences for the [PROTOCOL] protocol.

You are provided with:
- entry message types that may legally start a sequence:
[ENTRY_TYPES]
- the full list of client-originated message types that may appear later in a sequence:
[ALL_TYPES]
- protocol-level transition rules:
[TRANSITION_RULES]
- existing accepted sequences:
[EXISTING_SEQUENCES]
- one missing-but-recoverable target message type that must appear:
[MISSING_TYPE]

Please adhere to the following instructions:

1. Generate 1 or 2 candidate sequences of exact length [SEQ_LENGTH].
2. Every sequence MUST start with an allowed start message from the transition rules.
3. Every sequence MUST include the missing target message type `[MISSING_TYPE]` at least once.
4. If the transition rules indicate that `[MISSING_TYPE]` is valid only as an initial anchor or only as the first message, then `[MISSING_TYPE]` MUST be the first message in the repaired sequence.
5. Obey the provided transition rules when deciding which messages may appear and what they may follow.
6. Prefer plausible progressions that improve message-type coverage rather than arbitrary permutations.
7. Avoid duplicating the existing accepted sequences unless there is no other plausible option.
8. Use only the provided message types. Do not invent new names.
9. Return only the final JSON object in the ProtocolSequences schema.
"""



def using_skeleton_llm(prompt: str) -> ProtocolSkeletons:
    client = OpenAI()
    try:
        completion = client.beta.chat.completions.parse(
            model=MODEL,
            temperature=0.2,
            messages=[
                {"role": "system", "content": "You are a network protocol expert with deep understanding of [PROTOCOL]."},
                {"role": "user", "content": prompt}
            ],
            response_format=ProtocolSkeletons,
            timeout=30
        )
        response = completion.choices[0].message.parsed

        index = 0
        os.makedirs(os.path.join(LLM_RESULT_DIR, "3_message_skeletons"), exist_ok=True)
        while os.path.exists(os.path.join(LLM_RESULT_DIR, "3_message_skeletons", f"response_{index}.json")):
            index += 1
        protocol_file = os.path.join(LLM_RESULT_DIR, "3_message_skeletons", f"response_{index}.json")
        with open(protocol_file, "w", encoding="utf-8") as f:
            json.dump(completion.model_dump(), f, indent=4, ensure_ascii=False)
        return response
    except Exception as e:
        print(f"Error generating message skeletons: {e}")
        return None


def using_expansion_llm(prompt: str) -> ProtocolSequences:
    client = OpenAI()
    try:
        completion = client.beta.chat.completions.parse(
            model=MODEL,
            temperature=0.2,
            messages=[
                {"role": "system", "content": "You are a network protocol expert with deep understanding of [PROTOCOL]."},
                {"role": "user", "content": prompt}
            ],
            response_format=ProtocolSequences,
            timeout=30
        )
        response = completion.choices[0].message.parsed

        index = 0
        os.makedirs(os.path.join(LLM_RESULT_DIR, "3_message_sequences"), exist_ok=True)
        while os.path.exists(os.path.join(LLM_RESULT_DIR, "3_message_sequences", f"response_{index}.json")):
            index += 1
        protocol_file = os.path.join(LLM_RESULT_DIR, "3_message_sequences", f"response_{index}.json")
        with open(protocol_file, "w", encoding="utf-8") as f:
            json.dump(completion.model_dump(), f, indent=4, ensure_ascii=False)
        return response
    except Exception as e:
        print(f"Error expanding message sequences: {e}")
        return None


def _used_messages(sequences: List[Sequence]) -> set:
    used = set()
    for sequence in sequences:
        used.update(sequence.type_sequence)
    return used


def _sequence_key(sequence: Sequence) -> tuple:
    return tuple(sequence.type_sequence)


def _recover_missing_sequences(
    protocol: str,
    seq_length: int,
    sequences: List[Sequence],
    transition_rules: Dict[str, object],
    entry_types: str,
    all_types: str,
    entry_types_list: List[str],
    all_types_list: List[str],
) -> List[Sequence]:
    rules_by_message = {
        rule["message"]: rule
        for rule in transition_rules.get("rules", []) or []
        if isinstance(rule, dict) and rule.get("message")
    }
    used_messages = _used_messages(sequences)
    missing_targets = [
        message
        for message in all_types_list
        if message not in used_messages and not rules_by_message.get(message, {}).get("should_not_appear", False)
    ]
    if not missing_targets:
        return sequences

    formatted_rules = format_transition_rules_for_prompt(transition_rules)
    existing_sequences_json = json.dumps(
        [{"sequenceId": seq.sequenceId, "type_sequence": seq.type_sequence} for seq in sequences],
        indent=2,
        ensure_ascii=False,
    )
    seen_keys = {_sequence_key(sequence) for sequence in sequences}
    repaired_sequences = list(sequences)

    for missing_type in missing_targets:
        missing_rule = rules_by_message.get(missing_type, {})
        requires_start_anchor_repair = missing_rule.get("allow_only_as_first") or (
            missing_rule.get("allowed_as_start") and missing_type in (transition_rules.get("allowed_starts") or [])
        )
        if requires_start_anchor_repair:
            continue
        repair_prompt = (
            COVERAGE_REPAIR_PROMPT.replace("[PROTOCOL]", protocol)
            .replace("[ENTRY_TYPES]", entry_types)
            .replace("[ALL_TYPES]", all_types)
            .replace("[TRANSITION_RULES]", formatted_rules)
            .replace("[EXISTING_SEQUENCES]", existing_sequences_json)
            .replace("[MISSING_TYPE]", missing_type)
            .replace("[SEQ_LENGTH]", str(seq_length))
        )

        repair_response = None
        for _ in range(1):
            repair_response = using_expansion_llm(repair_prompt)
            if repair_response is not None:
                break

        if repair_response is None:
            continue

        repair_candidates = [
            seq
            for seq in repair_response.sequences
            if len(seq.type_sequence) == seq_length and missing_type in seq.type_sequence
        ]
        repair_candidates, _ = filter_sequences_with_rules(
            repair_candidates,
            transition_rules,
            entry_types_list,
            all_types_list,
        )

        added_for_target = False
        for seq in repair_candidates:
            key = _sequence_key(seq)
            if key in seen_keys:
                continue
            repaired_sequences.append(seq)
            seen_keys.add(key)
            added_for_target = True
            break

        if added_for_target:
            existing_sequences_json = json.dumps(
                [{"sequenceId": seq.sequenceId, "type_sequence": seq.type_sequence} for seq in repaired_sequences],
                indent=2,
                ensure_ascii=False,
            )

    return repaired_sequences


def _recover_missing_start_anchor_sequences(
    sequences: List[Sequence],
    transition_rules: Dict[str, object],
    entry_types_list: List[str],
    all_types_list: List[str],
) -> List[Sequence]:
    rules_by_message = {
        rule["message"]: rule
        for rule in transition_rules.get("rules", []) or []
        if isinstance(rule, dict) and rule.get("message")
    }
    allowed_starts = transition_rules.get("allowed_starts") or entry_types_list
    used_starts = {
        sequence.type_sequence[0]
        for sequence in sequences
        if sequence.type_sequence
    }
    missing_starts = [
        message for message in allowed_starts
        if message not in used_starts and not rules_by_message.get(message, {}).get("should_not_appear", False)
    ]
    if not missing_starts:
        return sequences

    repaired_sequences = list(sequences)
    seen_keys = {_sequence_key(sequence) for sequence in sequences}
    next_index = len(repaired_sequences) + 1

    for missing_start in missing_starts:
        added = False
        for sequence in sequences:
            if not sequence.type_sequence or sequence.type_sequence[0] == missing_start:
                continue
            candidate_types = [missing_start] + sequence.type_sequence
            is_valid, _ = validate_type_sequence_with_rules(
                candidate_types,
                transition_rules,
                entry_types_list,
                all_types_list,
            )
            if not is_valid:
                continue
            key = tuple(candidate_types)
            if key in seen_keys:
                continue
            repaired_sequences.append(
                Sequence(sequenceId=f"start_anchor_repair_{next_index}", type_sequence=candidate_types)
            )
            seen_keys.add(key)
            next_index += 1
            added = True
            break

        if added:
            continue

        for sequence in sequences:
            if len(sequence.type_sequence) < 2 or sequence.type_sequence[0] == missing_start:
                continue
            candidate_types = [missing_start] + sequence.type_sequence[1:]
            is_valid, _ = validate_type_sequence_with_rules(
                candidate_types,
                transition_rules,
                entry_types_list,
                all_types_list,
            )
            if not is_valid:
                continue
            key = tuple(candidate_types)
            if key in seen_keys:
                continue
            repaired_sequences.append(
                Sequence(sequenceId=f"start_anchor_repair_{next_index}", type_sequence=candidate_types)
            )
            seen_keys.add(key)
            next_index += 1
            break

    return repaired_sequences


def get_message_sequences(protocol: str, message_types: dict, seq_length: int) -> dict:
    file_path = os.path.join(MESSAGE_SEQUENCE_OUTPUT_DIR, f"{protocol.lower()}_message_sequences_{seq_length}.json")
    if os.path.exists(file_path):
        with open(file_path, "r", encoding="utf-8") as f:
            cached = json.load(f)
        print(f"Loaded cached results for {protocol} from {file_path}")
        return cached

    entry_types_list = [
        message_type["name"]
        for message_type in message_types.get("client_to_server_messages", [])
        if isinstance(message_type, dict) and message_type.get("name")
    ]
    all_types_source = message_types.get("all_client_to_server_messages")
    if not isinstance(all_types_source, list) or not all_types_source:
        all_types_source = message_types.get("client_to_server_messages", [])
    all_types_list = [
        message_type["name"]
        for message_type in all_types_source
        if isinstance(message_type, dict) and message_type.get("name")
    ]
    entry_types = "\n".join(f"- {message_type}" for message_type in entry_types_list).strip()
    all_types = "\n".join(f"- {message_type}" for message_type in all_types_list).strip()
    transition_rules = get_transition_rules(protocol, message_types)
    formatted_rules = format_transition_rules_for_prompt(transition_rules)

    skeleton_prompt = SKELETON_PROMPT.replace("[PROTOCOL]", protocol)\
                                     .replace("[ENTRY_TYPES]", entry_types)\
                                     .replace("[ALL_TYPES]", all_types)\
                                     .replace("[TRANSITION_RULES]", formatted_rules)\
                                     .replace("[SEQ_LENGTH]", str(seq_length))

    skeleton_response = None
    for _ in range(1):
        skeleton_response = using_skeleton_llm(skeleton_prompt)
        if skeleton_response is not None:
            break

    if skeleton_response is None:
        raise Exception(f"Failed to generate message skeletons for {protocol}")

    skeleton_json = json.dumps(skeleton_response.model_dump().get("skeletons", []), indent=2, ensure_ascii=False)
    expansion_prompt = EXPANSION_PROMPT.replace("[PROTOCOL]", protocol)\
                                       .replace("[ENTRY_TYPES]", entry_types)\
                                       .replace("[ALL_TYPES]", all_types)\
                                       .replace("[SKELETONS]", skeleton_json)\
                                       .replace("[TRANSITION_RULES]", formatted_rules)\
                                       .replace("[SEQ_LENGTH]", str(seq_length))

    response = None
    for _ in range(1):
        response = using_expansion_llm(expansion_prompt)
        if response is not None:
            break

    if response is None:
        raise Exception(f"Failed to expand message sequence for {protocol}")

    response.sequences = [seq for seq in response.sequences if len(seq.type_sequence) == seq_length]
    response.sequences, invalid_reasons = filter_sequences_with_rules(
        response.sequences,
        transition_rules,
        entry_types_list,
        all_types_list,
    )
    if invalid_reasons:
        print(f"Rejected {len(invalid_reasons)} rule-violating {protocol} sequences")

    response.sequences = _recover_missing_sequences(
        protocol,
        seq_length,
        response.sequences,
        transition_rules,
        entry_types,
        all_types,
        entry_types_list,
        all_types_list,
    )
    response.sequences = _recover_missing_start_anchor_sequences(
        response.sequences,
        transition_rules,
        entry_types_list,
        all_types_list,
    )

    os.makedirs(MESSAGE_SEQUENCE_OUTPUT_DIR, exist_ok=True)
    with open(file_path, "w", encoding="utf-8") as f:
        json.dump(response.model_dump(), f, indent=4, ensure_ascii=False)
    print(f"Saved results for {protocol} to {file_path}")

    os.makedirs(LLM_RESULT_DIR, exist_ok=True)
    protocol_file = os.path.join(LLM_RESULT_DIR, f"3_{protocol.lower()}_message_sequences_{seq_length}.json")
    with open(protocol_file, "w", encoding="utf-8") as f:
        json.dump(response.model_dump(), f, indent=4, ensure_ascii=False)

    return response.model_dump()
