import os
import json

from typing import Optional, List
from pydantic import BaseModel
from openai import OpenAI
from utility.utility import MODEL, LLM_RETRY, LLM_RESULT_DIR

PROTOCOL_TYPE_OUTPUT_DIR = "protocol_type_results"

class MessageType(BaseModel):
    name: str                               # Message type name (e.g., DISCONNECT, KEXINIT)
    code: Optional[str] = None              # Code of the message type
    description: str                        # Brief description of the message 

class ProtocolMessageTypes(BaseModel):
    protocol: str                                               # Protocol name (e.g., SSH, HTTP)
    client_to_server_messages: List[MessageType]                # List of all message types in the protocol
    potential_candidates: Optional[List[MessageType]] = None    # List of potential candidates for message types
    references: Optional[List[str]] = None                      # List of official documents or RFCs
    notes: Optional[str] = None                                 # Considerations for future extensibility or additional notes


class ServerToClientMessageTypes(BaseModel):
    protocol: str
    server_to_client_messages: List[MessageType]
    references: Optional[List[str]] = None
    notes: Optional[str] = None


class EntryMessageTypes(BaseModel):
    protocol: str
    entry_message_types: List[MessageType]
    references: Optional[List[str]] = None
    notes: Optional[str] = None


class MissingClientMessageTypes(BaseModel):
    protocol: str
    missing_client_to_server_messages: List[MessageType]
    references: Optional[List[str]] = None
    notes: Optional[str] = None

PROTOCOL_TYPE_PROMPT = """\
You are a network protocol expert with deep understanding of [PROTOCOL].
Your task is to extract all defined client-to-server message types in the [PROTOCOL] protocol, including any extended or optional commands as defined in official documentation or recognized RFC extensions.

Please adhere to the following instructions:

1. **Identify All Client-to-Server Message Types (Including Extensions):**
   - List every client-to-server message type defined in the [PROTOCOL] protocol exactly as specified in the official documentation, RFCs, or other recognized authoritative sources.
   - Ensure that extended or optional commands (such as BDAT in the case of Exim's SMTP extensions) are also included if they are part of the protocol's official extensions.
   - If the protocol documentation provides message codes or numeric values alongside the message types, include them. This is not server response code.
   - Present your answer in a structured format (e.g., a JSON array or a table) to ensure clarity and completeness.
   - If applicable, sort the list in alphabetical order or according to the order specified in the official documentation.
   - Message types sent from the server to the client are not extracted.
   - **Example:**  
     For SSH, an acceptable output would be:  
     ```json
     {
       "protocol": "SSH",
       "client_to_server_messages": [
         {"name": "KEXINIT", "code": "20", "description": "Description of KEXINIT including its purpose and usage"},
         {"name": "SERVICE_REQUEST", "code": "5", "description": "Description of SERVICE_REQUEST including its purpose and usage"},
         {"name": "USERAUTH_REQUEST", "code": "50", "description": "Description of USERAUTH_REQUEST including its purpose and usage"}
         // ... include other message types as defined in the official documentation.
       ]
     }
     ```

2. **Authoritative and Accurate:**
   - Base your response strictly on official documentation, RFCs, or other recognized authoritative sources.
   - Provide references (e.g., document names, URLs) for the sources you consulted.
   - Avoid any subjective interpretation or hallucinated information.
   - **Example:**  
     In your response, include a section like:  
     ```plaintext
     Sources:
     - RFC 4253 (SSH Transport Layer Protocol): https://tools.ietf.org/html/rfc4253
     - Official [PROTOCOL] documentation: [Insert URL here]
     ```

3. **Step-by-Step Reasoning:**
   - Detail the process you used to derive the list of client-to-server message types.
   - Explain which official documents or RFCs you consulted and how you verified that the list is complete.
   - If there are ambiguous or unclear parts in the documentation, describe how you addressed them and note any potential uncertainties.
   - **Example:**  
     Include a reasoning section such as:  
     ```plaintext
     Reasoning Process:
     - Step 1: Reviewed the official [PROTOCOL] documentation to identify the message types.
     - Step 2: Cross-referenced with RFC [Number] to ensure all client-to-server message types were included.
     - Step 3: Noted that certain message types had ambiguous definitions; these are marked in the "Potential Candidates" section.
     ```

4. **Error Handling and Completeness:**
   - If certain message types (including any extensions like BDAT) are not clearly defined in the official sources, include a note on these uncertainties and list any potential candidates in a separate section (e.g., "Potential Candidates").
   - Cross-check multiple official sources to confirm the completeness of the list.
   - **Example:**  
     Add a section for ambiguous or uncertain message types, for example:  
     ```plaintext
     Potential Candidates:
     - [TYPE_X]: Defined in some unofficial documentation but not clearly specified in the official sources.
     - [TYPE_Y]: Might be part of an extended version of the protocol.
     ```

Please extract all client-to-server message types for [PROTOCOL] following the above instructions.
"""

SERVER_TO_CLIENT_FILTER_PROMPT = """\
You are a network protocol expert with deep understanding of [PROTOCOL].
You are given a candidate list that was previously extracted as possible client-to-server message types.

Your task is only to identify which items in this candidate list are actually server-to-client messages or server-originated responses according to authoritative protocol documentation.

Rules:
1. Only judge the messages in the provided candidate list.
2. Do not invent new message names.
3. Use official documentation, RFCs, or other recognized authoritative sources.
4. If a candidate is actually sent from server to client, include it in `server_to_client_messages`.
5. If a candidate can be sent by the client, do not include it here, even if it is state-dependent or a poor seed entry.
6. If uncertain, omit it rather than guessing.

Candidate list:
[CANDIDATE_LIST]
"""

ENTRY_MESSAGE_FILTER_PROMPT = """\
You are a network protocol expert with deep understanding of [PROTOCOL].
You are given a list of protocol message types that are already considered client-to-server.

Your task is only to identify which of these messages are appropriate entry message types for seed generation.

Definition of an entry message type:
- A client-originated message type that can reasonably serve as an initial or anchor message type when constructing a seed sequence.
- Prefer messages that are canonical, common, and suitable as a starting point for driving protocol state forward.
- Exclude messages that usually depend on prior narrow context, prior negotiated state, or prior completion of a very specific sub-step.

Rules:
1. Only judge the messages in the provided candidate list.
2. Do not invent new message names.
3. Use official documentation, RFCs, or other recognized authoritative sources.
4. Include only messages that are appropriate entry message types.
5. If uncertain, omit the item rather than guessing.

Candidate list:
[CANDIDATE_LIST]
"""

MISSING_MESSAGE_REPAIR_PROMPT = """\
You are a network protocol expert with deep understanding of [PROTOCOL].
You are given a candidate list that was previously extracted as client-to-server message types.

Your task is only to identify important missing client-to-server message types that are defined in authoritative protocol documentation but absent from the candidate list.

Rules:
1. Only add messages that are truly missing from the provided candidate list.
2. Do not repeat items that are already present.
3. Do not invent new names.
4. Use official documentation, RFCs, or other recognized authoritative sources.
5. Focus on canonical or standardized client-to-server message types, especially core progression methods whose absence would make later-stage methods incomplete or implausible.
6. If the current list already contains later-stage control or session-dependent messages, check carefully whether prerequisite setup or session-establishing client messages are missing.
7. If no important messages are missing, return an empty list.

Candidate list:
[CANDIDATE_LIST]
"""

def using_llm(prompt: str) -> ProtocolMessageTypes:
    client = OpenAI()
    try:
        completion = client.beta.chat.completions.parse(
            model=MODEL,
            temperature=0.1,
            messages=[
                {"role": "system", "content": "You are a network protocol expert with deep understanding of [PROTOCOL]."},
                {"role": "user", "content": prompt}
            ],
            response_format=ProtocolMessageTypes,
            timeout=30
        )
        response = completion.choices[0].message.parsed

        index = 0
        os.makedirs(os.path.join(LLM_RESULT_DIR, "1_types"), exist_ok=True)
        while os.path.exists(os.path.join(LLM_RESULT_DIR, "1_types", f"response_{index}.json")):
            index += 1
        protocol_file = os.path.join(LLM_RESULT_DIR, "1_types", f"response_{index}.json")
        with open(protocol_file, "w", encoding="utf-8") as f:
            json.dump(completion.model_dump(), f, indent=4, ensure_ascii=False)
        return response
    except Exception as e:
        print(f"Error processing protocol: {e}")
        return None


def using_server_to_client_filter(prompt: str) -> ServerToClientMessageTypes:
    client = OpenAI()
    try:
        completion = client.beta.chat.completions.parse(
            model=MODEL,
            temperature=0.1,
            messages=[
                {"role": "system", "content": "You identify only server-to-client protocol messages from a provided candidate list."},
                {"role": "user", "content": prompt}
            ],
            response_format=ServerToClientMessageTypes,
            timeout=30
        )
        response = completion.choices[0].message.parsed

        index = 0
        os.makedirs(os.path.join(LLM_RESULT_DIR, "1_types_filter"), exist_ok=True)
        while os.path.exists(os.path.join(LLM_RESULT_DIR, "1_types_filter", f"response_{index}.json")):
            index += 1
        protocol_file = os.path.join(LLM_RESULT_DIR, "1_types_filter", f"response_{index}.json")
        with open(protocol_file, "w", encoding="utf-8") as f:
            json.dump(completion.model_dump(), f, indent=4, ensure_ascii=False)
        return response
    except Exception as e:
        print(f"Error filtering server-to-client messages: {e}")
        return None


def using_entry_filter(prompt: str) -> EntryMessageTypes:
    client = OpenAI()
    try:
        completion = client.beta.chat.completions.parse(
            model=MODEL,
            temperature=0.1,
            messages=[
                {"role": "system", "content": "You identify only seed-entry-appropriate protocol message types from a provided client-to-server list."},
                {"role": "user", "content": prompt}
            ],
            response_format=EntryMessageTypes,
            timeout=30
        )
        response = completion.choices[0].message.parsed

        index = 0
        os.makedirs(os.path.join(LLM_RESULT_DIR, "1_types_entry_filter"), exist_ok=True)
        while os.path.exists(os.path.join(LLM_RESULT_DIR, "1_types_entry_filter", f"response_{index}.json")):
            index += 1
        protocol_file = os.path.join(LLM_RESULT_DIR, "1_types_entry_filter", f"response_{index}.json")
        with open(protocol_file, "w", encoding="utf-8") as f:
            json.dump(completion.model_dump(), f, indent=4, ensure_ascii=False)
        return response
    except Exception as e:
        print(f"Error filtering entry message types: {e}")
        return None


def using_missing_message_repair(prompt: str) -> MissingClientMessageTypes:
    client = OpenAI()
    try:
        completion = client.beta.chat.completions.parse(
            model=MODEL,
            temperature=0.1,
            messages=[
                {"role": "system", "content": "You identify only important missing client-to-server protocol messages from a provided candidate list."},
                {"role": "user", "content": prompt}
            ],
            response_format=MissingClientMessageTypes,
            timeout=30
        )
        response = completion.choices[0].message.parsed

        index = 0
        os.makedirs(os.path.join(LLM_RESULT_DIR, "1_types_repair"), exist_ok=True)
        while os.path.exists(os.path.join(LLM_RESULT_DIR, "1_types_repair", f"response_{index}.json")):
            index += 1
        protocol_file = os.path.join(LLM_RESULT_DIR, "1_types_repair", f"response_{index}.json")
        with open(protocol_file, "w", encoding="utf-8") as f:
            json.dump(completion.model_dump(), f, indent=4, ensure_ascii=False)
        return response
    except Exception as e:
        print(f"Error repairing missing client-to-server messages: {e}")
        return None


def _filter_server_to_client_messages(protocol: str, extracted: dict) -> dict:
    candidate_list = extracted.get("client_to_server_messages", [])
    prompt = (
        SERVER_TO_CLIENT_FILTER_PROMPT.replace("[PROTOCOL]", protocol)
        .replace("[CANDIDATE_LIST]", json.dumps(candidate_list, indent=2, ensure_ascii=False))
    )

    filtered = None
    for _ in range(LLM_RETRY):
        filtered = using_server_to_client_filter(prompt)
        if filtered is not None:
            break

    if filtered is None:
        return extracted

    excluded_names = {
        item["name"]
        for item in filtered.model_dump().get("server_to_client_messages", [])
        if isinstance(item, dict) and item.get("name")
    }
    extracted["client_to_server_messages"] = [
        item for item in extracted.get("client_to_server_messages", [])
        if item.get("name") not in excluded_names
    ]
    if excluded_names:
        notes = extracted.get("notes")
        exclusion_note = "Filtered server-to-client messages: " + ", ".join(sorted(excluded_names))
        extracted["notes"] = f"{notes}; {exclusion_note}" if notes else exclusion_note

    filter_refs = filtered.model_dump().get("references") or []
    if filter_refs:
        existing_refs = extracted.get("references") or []
        merged_refs = []
        seen = set()
        for ref in existing_refs + filter_refs:
            if ref not in seen:
                merged_refs.append(ref)
                seen.add(ref)
        extracted["references"] = merged_refs
    return extracted


def _repair_missing_client_messages(protocol: str, extracted: dict) -> dict:
    candidate_list = extracted.get("client_to_server_messages", [])
    prompt = (
        MISSING_MESSAGE_REPAIR_PROMPT.replace("[PROTOCOL]", protocol)
        .replace("[CANDIDATE_LIST]", json.dumps(candidate_list, indent=2, ensure_ascii=False))
    )

    repaired = None
    for _ in range(LLM_RETRY):
        repaired = using_missing_message_repair(prompt)
        if repaired is not None:
            break

    if repaired is None:
        return extracted

    existing_names = {
        item["name"]
        for item in candidate_list
        if isinstance(item, dict) and item.get("name")
    }
    missing_messages = [
        item
        for item in repaired.model_dump().get("missing_client_to_server_messages", [])
        if isinstance(item, dict) and item.get("name") and item["name"] not in existing_names
    ]
    if missing_messages:
        extracted["client_to_server_messages"] = candidate_list + missing_messages
        notes = extracted.get("notes")
        repair_note = "Added missing client-to-server messages: " + ", ".join(item["name"] for item in missing_messages)
        extracted["notes"] = f"{notes}; {repair_note}" if notes else repair_note

    repair_refs = repaired.model_dump().get("references") or []
    if repair_refs:
        existing_refs = extracted.get("references") or []
        merged_refs = []
        seen = set()
        for ref in existing_refs + repair_refs:
            if ref not in seen:
                merged_refs.append(ref)
                seen.add(ref)
        extracted["references"] = merged_refs
    return extracted


def _filter_entry_message_types(protocol: str, extracted: dict) -> dict:
    all_client_messages = extracted.get("client_to_server_messages", [])
    extracted["all_client_to_server_messages"] = list(all_client_messages)

    prompt = (
        ENTRY_MESSAGE_FILTER_PROMPT.replace("[PROTOCOL]", protocol)
        .replace("[CANDIDATE_LIST]", json.dumps(all_client_messages, indent=2, ensure_ascii=False))
    )

    filtered = None
    for _ in range(LLM_RETRY):
        filtered = using_entry_filter(prompt)
        if filtered is not None:
            break

    if filtered is None:
        return extracted

    entry_names = {
        item["name"]
        for item in filtered.model_dump().get("entry_message_types", [])
        if isinstance(item, dict) and item.get("name")
    }
    extracted["client_to_server_messages"] = [
        item for item in all_client_messages
        if item.get("name") in entry_names
    ]

    notes = extracted.get("notes")
    entry_note = "Retained entry message types: " + ", ".join(item["name"] for item in extracted["client_to_server_messages"])
    extracted["notes"] = f"{notes}; {entry_note}" if notes else entry_note

    filter_refs = filtered.model_dump().get("references") or []
    if filter_refs:
        existing_refs = extracted.get("references") or []
        merged_refs = []
        seen = set()
        for ref in existing_refs + filter_refs:
            if ref not in seen:
                merged_refs.append(ref)
                seen.add(ref)
        extracted["references"] = merged_refs
    return extracted

def get_protocol_message_types(protocol: str) -> dict:
    protocol_file = os.path.join(PROTOCOL_TYPE_OUTPUT_DIR, f"{protocol.lower()}_types.json")
    if os.path.exists(protocol_file):
        with open(protocol_file, "r", encoding="utf-8") as f:
            cached = json.load(f)
        print(f"Loaded cached results for {protocol} from {protocol_file}")
        return cached

    prompt = PROTOCOL_TYPE_PROMPT.replace("[PROTOCOL]", protocol)

    for _ in range(LLM_RETRY):
        response = using_llm(prompt)
        if response is not None:
            break

    if response is None:
        raise Exception(f"Failed to generate message types for {protocol}")

    result = response.model_dump()
    result = _repair_missing_client_messages(protocol, result)
    result = _filter_server_to_client_messages(protocol, result)
    result = _filter_entry_message_types(protocol, result)

    os.makedirs(PROTOCOL_TYPE_OUTPUT_DIR, exist_ok=True)
    with open(protocol_file, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=4, ensure_ascii=False)
    print(f"Saved results for {protocol} to {protocol_file}")

    os.makedirs(LLM_RESULT_DIR, exist_ok=True)    
    protocol_file = os.path.join(LLM_RESULT_DIR, f"1_{protocol.lower()}_types.json")
    with open(protocol_file, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=4, ensure_ascii=False)

    return result
