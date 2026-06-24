import os
import json
from typing import Any, Dict, List

MODEL = "gpt-4o-mini"
LLM_RESULT_DIR = "llm_outputs"
SEQUENCE_REPEAT = 1
LLM_RETRY = 3
RAW_OUTPUT_DIR = None

def convert_message_to_binary(message: str) -> bytes:
    if not message:
        return b''
    
    parts = message.split(' ')
    processed_parts = []
    
    for part in parts:
        if part.startswith('0x'):
            try:
                binary_value = bytes([int(part[2:], 16)])
                processed_parts.append((binary_value, True))
            except ValueError:
                processed_parts.append((part.encode(), False))
        else:
            processed_parts.append((part.encode(), False))
    
    result = bytearray()
    for i in range(len(processed_parts)):
        current_data, current_is_binary = processed_parts[i]
        result.extend(current_data)
        
        if i < len(processed_parts) - 1:
            next_is_binary = processed_parts[i+1][1]
            if not current_is_binary and not next_is_binary:
                result.extend(b' ')

    return bytes(result)


def _write_sequence_messages_to_raw(
    sequence: Dict[str, Any],
    output_dir: str,
    file_prefix: str = "new_",
) -> None:
    concatenated_messages = bytearray()
    for message in sequence.get("messages", []):
        concatenated_messages += convert_message_to_binary(message["message"]) + b"\r\n"

    idx = 1
    while True:
        file_path = os.path.join(output_dir, f"{file_prefix}{idx}.raw")
        if not os.path.exists(file_path):
            break
        idx += 1

    with open(file_path, "wb") as f:
        f.write(concatenated_messages)


def set_raw_output_dir(output_dir: str) -> None:
    global RAW_OUTPUT_DIR
    RAW_OUTPUT_DIR = output_dir


def get_raw_output_dir() -> str:
    return RAW_OUTPUT_DIR or ""

def save_llm_response_testcase(test_case: Dict[str, Any], output_dir: str) -> None:
    os.makedirs(output_dir, exist_ok=True)

    for sequence in test_case.get("sequences", []):
        try:
            _write_sequence_messages_to_raw(sequence, output_dir)
        except Exception as e:
            print(f"Error saving LLM response testcase: {e}")
            
def load_seed_messages(seed_messages_dir: str) -> List[str]:
    seed_messages = []
    file_names = []
    for file in os.listdir(seed_messages_dir):
        file_path = os.path.join(seed_messages_dir, file)
        file_names.append(file)
        with open(file_path, "rb") as f:
            binary_content = f.read()
        
        readable_content = ""
        for byte in binary_content:
            if byte in (9, 10, 13) or (32 <= byte <= 126):
                readable_content += chr(byte)
            else:
               readable_content += f" 0x{byte:02x} "
        
        seed_messages.append(readable_content)
    return file_names, seed_messages
