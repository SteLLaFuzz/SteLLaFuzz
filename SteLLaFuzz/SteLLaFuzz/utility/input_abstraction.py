import re
from collections import defaultdict
from typing import Any, Dict, Iterable, List


BYTE_TOKEN_RE = re.compile(r"0x[0-9a-fA-F]{2}")
INT_RE = re.compile(r"^-?\d+$")
HEXISH_RE = re.compile(r"^[0-9a-fA-F]{8,}$")
TEXT_LINE_SPLIT_RE = re.compile(r"\r\n\r\n|\n\n")
TOKEN_RE = re.compile(r"0x[0-9a-fA-F]{2}|[A-Za-z0-9._:+%\-]+|[^\s]")
MAX_OBSERVATION_CLUSTERS = 5
MAX_OBSERVATION_TEMPLATES = 5
MAX_OBSERVATION_EXAMPLES = 5


def collect_generalized_input_observations(seed_messages: Iterable[str]) -> Dict[str, Any]:
    seed_list = list(seed_messages or [])
    chunks: List[str] = []
    for seed_message in seed_list:
        chunks.extend(_split_into_chunks(seed_message))

    text_chunks = []
    binary_chunks = []
    for chunk in chunks:
        if _is_binary_like(chunk):
            binary_chunks.append(chunk)
        else:
            text_chunks.append(chunk)

    return {
        "observed_message_count": len(chunks),
        "text_observations": _generalize_text_chunks(text_chunks),
        "binary_observations": _generalize_binary_chunks(binary_chunks),
    }


def _split_into_chunks(seed_message: str) -> List[str]:
    parts = [part.strip() for part in TEXT_LINE_SPLIT_RE.split(seed_message) if part.strip()]
    return parts or [seed_message.strip()]


def _is_binary_like(chunk: str) -> bool:
    byte_tokens = BYTE_TOKEN_RE.findall(chunk)
    token_count = max(len(chunk.split()), 1)
    return len(byte_tokens) >= max(3, token_count // 2)


def _generalize_text_chunks(chunks: List[str]) -> List[Dict[str, Any]]:
    grouped: Dict[str, List[str]] = defaultdict(list)
    for chunk in chunks:
        first_line = chunk.splitlines()[0].strip() if chunk.splitlines() else chunk.strip()
        key = first_line.split(" ", 1)[0] if first_line else "TEXT"
        grouped[key].append(first_line)

    observations = []
    for key, lines in grouped.items():
        templates = []
        for line in lines:
            template = _generalize_text_line(line)
            if template not in templates:
                templates.append(template)

        observations.append(
            {
                "cluster_key": key,
                "count": len(lines),
                "templates": templates[:MAX_OBSERVATION_TEMPLATES],
                "examples": lines[:MAX_OBSERVATION_EXAMPLES],
            }
        )
    observations.sort(key=lambda observation: observation.get("count", 0), reverse=True)
    return observations[:MAX_OBSERVATION_CLUSTERS]


def _generalize_text_line(line: str) -> str:
    tokens = TOKEN_RE.findall(line)
    normalized = []
    for token in tokens:
        if INT_RE.match(token):
            normalized.append("{int}")
        elif HEXISH_RE.match(token):
            normalized.append("{hex}")
        elif token.lower() in {"true", "false"}:
            normalized.append("{bool}")
        elif ":" in token and token.count(":") >= 2:
            normalized.append("{compound}")
        else:
            normalized.append(token)

    template = " ".join(normalized)
    template = template.replace(" / ", "/")
    template = template.replace(" ? ", "?")
    template = template.replace(" & ", "&")
    template = template.replace(" = ", "=")
    return template


def _generalize_binary_chunks(chunks: List[str]) -> List[Dict[str, Any]]:
    grouped: Dict[str, List[List[str]]] = defaultdict(list)
    for chunk in chunks:
        tokens = BYTE_TOKEN_RE.findall(chunk)
        if not tokens:
            continue
        prefix = " ".join(tokens[:2]) if len(tokens) >= 2 else tokens[0]
        grouped[prefix].append(tokens)

    observations = []
    for key, token_lists in grouped.items():
        min_length = min(len(tokens) for tokens in token_lists)
        template = []
        for index in range(min_length):
            values = {tokens[index] for tokens in token_lists}
            template.append(next(iter(values)) if len(values) == 1 else "{byte}")

        has_variable_tail = any(len(tokens) != min_length for tokens in token_lists)
        if has_variable_tail:
            template.append("{var_tail}")

        observations.append(
            {
                "cluster_key": key,
                "count": len(token_lists),
                "template": " ".join(template),
                "examples": [
                    " ".join(tokens[:32]) for tokens in token_lists[:MAX_OBSERVATION_EXAMPLES]
                ],
            }
        )
    observations.sort(key=lambda observation: observation.get("count", 0), reverse=True)
    return observations[:MAX_OBSERVATION_CLUSTERS]
