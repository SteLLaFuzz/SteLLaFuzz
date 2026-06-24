import os
import json

from typing import Optional, List
from pydantic import BaseModel
from openai import OpenAI
from LLM.sequence_rules import (
    filter_sequences_with_rules,
    format_transition_rules_for_prompt,
    get_transition_rules,
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
    sequences: Optional[List[Sequence]] = None
    explanation: Optional[str] = None


class ProtocolSkeletons(BaseModel):
    protocol: str
    skeletons: List[SkeletonSequence]
    explanation: str


SKELETON_PROMPT = """\
You are a network protocol expert with deep understanding of [PROTOCOL].
Your task is to generate progression skeletons for repeated client-to-server communications in the [PROTOCOL] protocol.
The objective of this stage is to propose plausible progressions first, before adding repeated-message coverage variation.

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
   - Each skeleton length must be between 2 and 6, inclusive.
   - The first message of every skeleton MUST come from the allowed starts implied by the transition rules.
   - After the initial entry message, continue with later-stage or follow-up client-originated message types from the full list.
   - Prioritize plausible follow-up ordering over repeated-message exploration for this stage.
   - Obey the provided transition rules when deciding which messages may appear and what they may follow.

2. **Use Only Provided Message Types:**
   - Every message type must exactly match one of the provided message types.
   - Do not invent new message names.

3. **Provide a Skeleton Rationale:**
   - In the "explanation" field, briefly explain why these skeletons represent plausible client-side progressions.

4. **Final Output Requirements:**
   - You MUST NOT include any extraneous text; only provide the final JSON output.
   - You MUST ensure the output is valid JSON strictly adhering to the structure below. (Invalid JSON or additional text will not be accepted.)

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
Your task is to expand progression skeletons into repeated client-to-server message sequences for the [PROTOCOL] protocol.
The objective of this stage is to add repetition-driven coverage variation while preserving the intended progression of each skeleton.

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

1. **Expand Skeletons Into Repeated Sequences:**
   - Generate multiple final sequences.
   - Every final sequence MUST start with an allowed start message from the transition rules.
   - Every final sequence MUST preserve the message order of one provided skeleton.
   - Add at least one repeated message occurrence in each final sequence.
   - Use repetitions to explore follow-up behavior while keeping the sequence aligned with the underlying skeleton progression.
   - Do not turn later-stage messages into fresh starting points.
   - Do not reorder a skeleton so that a later skeleton message appears before an earlier skeleton message.
   - Obey the provided transition rules when deciding which messages may appear and what they may follow.

2. **Use Only Provided Message Types:**
   - Every message type must exactly match one of the provided message types.
   - Do not invent new message names.

3. **Provide a Rationale:**
   - In the "explanation" field, briefly explain how the final sequences preserve the skeleton progressions while adding repeated-message coverage variation.

4. **Final Output Requirements:**
   - You MUST NOT include any extraneous text; only provide the final JSON output.
   - You MUST ensure the output is valid JSON strictly adhering to the structure below.

5. **Final Output Structure:**
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
     "explanation": "A brief explanation of how these sequences preserve the skeleton progressions while adding repeated-message variation."
   }
   ```

Please generate the final repeated sequences strictly following the above instructions.
"""


def using_skeleton_llm(prompt: str) -> ProtocolSkeletons:
    client = OpenAI()
    try:
        completion = client.beta.chat.completions.parse(
            model=MODEL,
            temperature=0.3,
            messages=[
                {"role": "system", "content": "You are a network protocol expert with deep understanding of [PROTOCOL]."},
                {"role": "user", "content": prompt}
            ],
            response_format=ProtocolSkeletons,
            timeout=30
        )
        response = completion.choices[0].message.parsed

        index = 0
        os.makedirs(os.path.join(LLM_RESULT_DIR, "4_repeated_message_skeletons"), exist_ok=True)
        while os.path.exists(os.path.join(LLM_RESULT_DIR, "4_repeated_message_skeletons", f"response_{index}.json")):
            index += 1
        protocol_file = os.path.join(LLM_RESULT_DIR, "4_repeated_message_skeletons", f"response_{index}.json")
        with open(protocol_file, "w", encoding="utf-8") as f:
            json.dump(completion.model_dump(), f, indent=4, ensure_ascii=False)
        return response
    except Exception as e:
        print(f"Error generating repeated message skeletons: {e}")
        return None


def using_expansion_llm(prompt: str) -> ProtocolSequences:
    client = OpenAI()
    try:
        completion = client.beta.chat.completions.parse(
            model=MODEL,
            temperature=0.5,
            messages=[
                {"role": "system", "content": "You are a network protocol expert with deep understanding of [PROTOCOL]."},
                {"role": "user", "content": prompt}
            ],
            response_format=ProtocolSequences,
            timeout=30
        )
        response = completion.choices[0].message.parsed

        index = 0
        os.makedirs(os.path.join(LLM_RESULT_DIR, "4_repeated_message_sequences"), exist_ok=True)
        while os.path.exists(os.path.join(LLM_RESULT_DIR, "4_repeated_message_sequences", f"response_{index}.json")):
            index += 1
        protocol_file = os.path.join(LLM_RESULT_DIR, "4_repeated_message_sequences", f"response_{index}.json")
        with open(protocol_file, "w", encoding="utf-8") as f:
            json.dump(completion.model_dump(), f, indent=4, ensure_ascii=False)
        return response
    except Exception as e:
        print(f"Error expanding repeated message sequences: {e}")
        return None


def get_repeated_message_sequences(protocol: str, message_types: dict) -> dict:
    file_path = os.path.join(MESSAGE_SEQUENCE_OUTPUT_DIR, f"{protocol.lower()}_repeated_message_sequences.json")
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
                                     .replace("[TRANSITION_RULES]", formatted_rules)

    skeleton_response = None
    for _ in range(1):
        skeleton_response = using_skeleton_llm(skeleton_prompt)
        if skeleton_response is not None:
            break

    if skeleton_response is None:
        raise Exception(f"Failed to generate repeated message skeletons for {protocol}")

    skeleton_json = json.dumps(skeleton_response.model_dump().get("skeletons", []), indent=2, ensure_ascii=False)
    expansion_prompt = EXPANSION_PROMPT.replace("[PROTOCOL]", protocol)\
                                       .replace("[ENTRY_TYPES]", entry_types)\
                                       .replace("[ALL_TYPES]", all_types)\
                                       .replace("[SKELETONS]", skeleton_json)\
                                       .replace("[TRANSITION_RULES]", formatted_rules)

    response = None
    for _ in range(1):
        response = using_expansion_llm(expansion_prompt)
        if response is not None:
            break

    if response is None:
        raise Exception(f"Failed to expand repeated message sequence for {protocol}")

    response.sequences, invalid_reasons = filter_sequences_with_rules(
        response.sequences or [],
        transition_rules,
        entry_types_list,
        all_types_list,
    )
    if invalid_reasons:
        print(f"Rejected {len(invalid_reasons)} rule-violating repeated {protocol} sequences")

    filtered_sequences = []
    for sequence in response.sequences or []:
        message_counts = {}
        has_repetition = False

        for msg_type in sequence.type_sequence:
            message_counts[msg_type] = message_counts.get(msg_type, 0) + 1
            if message_counts[msg_type] > 1:
                has_repetition = True
                break

        if has_repetition:
            filtered_sequences.append(sequence)

    if filtered_sequences:
        response.sequences = filtered_sequences
    else:
        print(f"Warning: No sequences with repeated message types found for {protocol}")

    os.makedirs(MESSAGE_SEQUENCE_OUTPUT_DIR, exist_ok=True)
    with open(file_path, "w", encoding="utf-8") as f:
        json.dump(response.model_dump(), f, indent=4, ensure_ascii=False)
    print(f"Saved results for {protocol} to {file_path}")

    os.makedirs(LLM_RESULT_DIR, exist_ok=True)
    protocol_file = os.path.join(LLM_RESULT_DIR, f"4_{protocol.lower()}_repeated_message_sequences.json")
    with open(protocol_file, "w", encoding="utf-8") as f:
        json.dump(response.model_dump(), f, indent=4, ensure_ascii=False)

    return response.model_dump()
