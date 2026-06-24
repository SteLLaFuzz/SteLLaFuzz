from __future__ import annotations

from typing import Dict, Iterable, List, Optional, Sequence, Tuple


TLS_ENTRY_TYPES = {"ClientHello"}
TLS_DEPENDENT_MESSAGES = {
    "Certificate",
    "CertificateVerify",
    "ChangeCipherSpec",
    "ClientKeyExchange",
    "Finished",
    "KeyExchange",
}
TLS_DISALLOWED_CLIENT_MESSAGES = {
    "HelloRequest",
}

SSH_ENTRY_TYPES = {"KEXINIT"}
SSH_CHANNEL_MESSAGES = {"CHANNEL_CLOSE", "CHANNEL_DATA", "CHANNEL_REQUEST"}

RTSP_ENTRY_TYPES = {"DESCRIBE", "OPTIONS"}
RTSP_SETUP_DEPENDENT_MESSAGES = {"PAUSE", "PLAY", "RECORD", "TEARDOWN"}


def get_entry_message_names(message_types: Dict[str, object]) -> List[str]:
    return [
        item["name"]
        for item in message_types.get("client_to_server_messages", [])
        if isinstance(item, dict) and item.get("name")
    ]


def get_candidate_message_names(message_types: Dict[str, object]) -> List[str]:
    source = message_types.get("all_client_to_server_messages")
    if not isinstance(source, list) or not source:
        source = message_types.get("client_to_server_messages", [])
    return [
        item["name"]
        for item in source
        if isinstance(item, dict) and item.get("name")
    ]


def validate_sequence(
    protocol: str,
    sequence: Sequence[str],
    entry_message_names: Iterable[str],
    allowed_message_names: Iterable[str],
) -> Tuple[bool, Optional[str]]:
    if not sequence:
        return False, "empty sequence"

    entry_set = set(entry_message_names)
    allowed_set = set(allowed_message_names)

    unknown_messages = [message for message in sequence if message not in allowed_set]
    if unknown_messages:
        return False, f"contains unknown message types: {', '.join(unknown_messages)}"

    first_message = sequence[0]
    if entry_set and first_message not in entry_set:
        return False, f"starts with non-entry message {first_message}"

    normalized_protocol = protocol.upper()
    if normalized_protocol == "TLS":
        return _validate_tls_sequence(sequence)
    if normalized_protocol == "SSH":
        return _validate_ssh_sequence(sequence)
    if normalized_protocol == "RTSP":
        return _validate_rtsp_sequence(sequence)

    return True, None


def filter_valid_sequences(
    protocol: str,
    sequences: Iterable[object],
    entry_message_names: Iterable[str],
    allowed_message_names: Iterable[str],
) -> Tuple[List[object], List[str]]:
    valid_sequences: List[object] = []
    invalid_reasons: List[str] = []

    for sequence in sequences:
        type_sequence = getattr(sequence, "type_sequence", None)
        if not isinstance(type_sequence, list):
            invalid_reasons.append("sequence missing type_sequence list")
            continue

        is_valid, reason = validate_sequence(
            protocol,
            type_sequence,
            entry_message_names,
            allowed_message_names,
        )
        if is_valid:
            valid_sequences.append(sequence)
        else:
            invalid_reasons.append(
                f"{getattr(sequence, 'sequenceId', 'unknown')}: {reason}"
            )

    return valid_sequences, invalid_reasons


def _validate_tls_sequence(sequence: Sequence[str]) -> Tuple[bool, Optional[str]]:
    seen = set()

    for index, message in enumerate(sequence):
        if index == 0 and message not in TLS_ENTRY_TYPES:
            return False, f"TLS sequence must start with ClientHello, got {message}"

        if index > 0 and message == "ClientHello":
            return False, "ClientHello may only appear as the first message"

        if message in TLS_DISALLOWED_CLIENT_MESSAGES:
            return False, f"{message} is not a valid client-originated TLS sequence message"

        if message in TLS_DEPENDENT_MESSAGES and "ClientHello" not in seen:
            return False, f"{message} requires prior ClientHello"

        if message == "CertificateVerify" and "Certificate" not in seen:
            return False, "CertificateVerify requires prior Certificate"

        if message == "Finished" and "ChangeCipherSpec" not in seen:
            return False, "Finished requires prior ChangeCipherSpec"

        seen.add(message)

    return True, None


def _validate_ssh_sequence(sequence: Sequence[str]) -> Tuple[bool, Optional[str]]:
    seen = set()

    for index, message in enumerate(sequence):
        if index == 0 and message not in SSH_ENTRY_TYPES:
            return False, f"SSH sequence must start with KEXINIT, got {message}"

        if index > 0 and message == "KEXINIT":
            return False, "KEXINIT may only appear as the first message"

        if message == "SERVICE_REQUEST" and "KEXINIT" not in seen:
            return False, "SERVICE_REQUEST requires prior KEXINIT"

        if message == "USERAUTH_REQUEST" and "SERVICE_REQUEST" not in seen:
            return False, "USERAUTH_REQUEST requires prior SERVICE_REQUEST"

        if message in {"CHANNEL_OPEN", "GLOBAL_REQUEST"} and "USERAUTH_REQUEST" not in seen:
            return False, f"{message} requires prior USERAUTH_REQUEST"

        if message in SSH_CHANNEL_MESSAGES and "CHANNEL_OPEN" not in seen:
            return False, f"{message} requires prior CHANNEL_OPEN"

        seen.add(message)

    return True, None


def _validate_rtsp_sequence(sequence: Sequence[str]) -> Tuple[bool, Optional[str]]:
    seen = set()

    for index, message in enumerate(sequence):
        if index == 0 and message not in RTSP_ENTRY_TYPES:
            return False, f"RTSP sequence must start with OPTIONS or DESCRIBE, got {message}"

        if message == "SETUP" and not ({"DESCRIBE", "OPTIONS"} & seen):
            return False, "SETUP requires prior OPTIONS or DESCRIBE"

        if message in RTSP_SETUP_DEPENDENT_MESSAGES and "SETUP" not in seen:
            return False, f"{message} requires prior SETUP"

        if message == "PAUSE" and "PLAY" not in seen:
            return False, "PAUSE requires prior PLAY"

        seen.add(message)

    return True, None
