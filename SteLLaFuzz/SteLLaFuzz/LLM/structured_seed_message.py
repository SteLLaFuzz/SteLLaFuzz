import os
import json

from typing import Optional, List
from pydantic import BaseModel
from openai import OpenAI
from utility.utility import MODEL, LLM_RETRY, LLM_RESULT_DIR, SEQUENCE_REPEAT

STRUCTURED_SEED_MESSAGE_OUTPUT_DIR = "structured_seed_message_results"

class Message(BaseModel):
    message: str

class ParsedMessages(BaseModel):
    message_sequences: List[Message]

MESSAGE_PROMPT = """\
You are a network protocol expert with deep understanding of [PROTOCOL].
Your task is to parse a raw seed message sequence that contains both printable ASCII characters and encoded non-ASCII bytes, and extract individual protocol message chunks according to the [PROTOCOL] specification.

Seed Message:
[SEED_MESSAGE]

Please adhere to the following instructions:

1. **Seed Message Parsing:**
   - The original message has been preprocessed such that:
     - All printable ASCII characters remain as-is.
     - All non-ASCII bytes are represented in `0xHH` hex notation (e.g., 0x00, 0x1A, 0xFF).
   - Split the input into individual protocol-level messages based on [PROTOCOL] rules, such as:
     - Header fields
     - Length indicators
     - Delimiters (e.g., \\r\\n, null terminators, etc.)
     - Other message boundary patterns defined in RFCs or official documentation


3. **Protocol-Adherent Parsing:**
   - Follow the message boundary rules defined in the [PROTOCOL] specification.
   - Use length headers, structural delimiters, or field offsets as applicable.
   - Do not split binary payloads incorrectly.

4. **Output Only JSON:**
   - Return only the JSON result. Do not include any additional commentary or explanation.

2. **Output Format:**
   - Return the result as a JSON object with the following schema:
     {
       "message_sequences": [
         {
           "message": "<exact substring of the original seed message>"
         },
         ...
       ]
     }
   - `message`: Include the original string chunk as-is, preserving any hex-encoded bytes.

5. **Message Indexing:**
   - Implicitly assume messages are indexed starting from 0 based on their position. Do not include an index in the output.

Parse the following seed message according to the [PROTOCOL] specification, strictly following the instructions.
"""


def using_llm(prompt: str) -> ParsedMessages:
    client = OpenAI()
    try:
        completion = client.beta.chat.completions.parse(
            model=MODEL,
            messages=[
                {"role": "system", "content": "You are a network protocol expert with deep understanding of [PROTOCOL]."},
                {"role": "user", "content": prompt}
            ],
            response_format=ParsedMessages,
            timeout=30
        )   
        response = completion.choices[0].message.parsed

        index = 0
        os.makedirs(os.path.join(LLM_RESULT_DIR, "5_structured_seed_message"), exist_ok=True)
        while os.path.exists(os.path.join(LLM_RESULT_DIR, "5_structured_seed_message", f"response_{index}.json")):
            index += 1
        protocol_file = os.path.join(LLM_RESULT_DIR, "5_structured_seed_message", f"response_{index}.json")
        with open(protocol_file, "w", encoding="utf-8") as f:
            json.dump(completion.model_dump(), f, indent=4, ensure_ascii=False)
        return response
    except Exception as e:
        print(f"Error processing protocol: {e}")
        return None

def get_structured_seed_message(protocol: str, seed_message: str) -> None:
    os.makedirs(STRUCTURED_SEED_MESSAGE_OUTPUT_DIR, exist_ok=True)
    cache_key = abs(hash((protocol, seed_message)))
    cache_path = os.path.join(
        STRUCTURED_SEED_MESSAGE_OUTPUT_DIR,
        f"{protocol.lower()}_structured_seed_{cache_key}.json",
    )
    if os.path.exists(cache_path):
        with open(cache_path, "r", encoding="utf-8") as f:
            cached = json.load(f)
        print(f"Loaded cached structured seed message for {protocol} from {cache_path}")
        return cached

    prompt = MESSAGE_PROMPT.replace("[PROTOCOL]", protocol)\
                           .replace("[SEED_MESSAGE]", seed_message)
    
    for _ in range(LLM_RETRY):
        response = using_llm(prompt)
        if response is not None:
            break

    if response is None:
        raise Exception(f"Failed to generate message for {protocol}")

    result = response.model_dump()
    with open(cache_path, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=4, ensure_ascii=False)
    return result
