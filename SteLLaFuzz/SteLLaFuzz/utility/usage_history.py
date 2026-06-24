import json
import os
import re
from typing import Any, Dict, Iterable, List

from utility.utility import LLM_RESULT_DIR

USAGE_HISTORY_DIR = os.path.join(LLM_RESULT_DIR, "parameter_usage")
DEPRIORITIZED_LIMIT = 10
GENERIC_WRAPPER_SEGMENTS = {"api", "rest", "rpc", "service", "services", "v1", "v2"}


def _get_usage_history_path(protocol: str, target_name: str) -> str:
    return os.path.join(
        USAGE_HISTORY_DIR,
        f"{protocol.lower()}_{target_name.lower()}_usage.json",
    )


def load_usage_history(protocol: str, target_name: str) -> Dict[str, Any]:
    os.makedirs(USAGE_HISTORY_DIR, exist_ok=True)
    file_path = _get_usage_history_path(protocol, target_name)
    if not os.path.exists(file_path):
        return {
            "surface_groups": {},
            "interaction_surfaces": {},
            "parameter_values": {},
            "recent_group_surface_choices": {},
            "recent_surface_parameter_fields": {},
            "surface_parameter_values": {},
        }

    with open(file_path, "r", encoding="utf-8") as f:
        loaded = json.load(f)
    loaded.setdefault("surface_groups", {})
    loaded.setdefault("interaction_surfaces", {})
    loaded.setdefault("parameter_values", {})
    loaded.setdefault("recent_group_surface_choices", {})
    loaded.setdefault("recent_surface_parameter_fields", {})
    loaded.setdefault("surface_parameter_values", {})
    return loaded


def get_deprioritized_candidates(usage_history: Dict[str, Any]) -> Dict[str, List[str]]:
    interaction_items = sorted(
        usage_history.get("interaction_surfaces", {}).items(),
        key=lambda item: item[1],
        reverse=True,
    )
    parameter_items = sorted(
        usage_history.get("parameter_values", {}).items(),
        key=lambda item: item[1],
        reverse=True,
    )
    return {
        "surface_groups": [key for key, _ in sorted(
            usage_history.get("surface_groups", {}).items(),
            key=lambda item: item[1],
            reverse=True,
        )[:DEPRIORITIZED_LIMIT]],
        "interaction_surfaces": [key for key, _ in interaction_items[:DEPRIORITIZED_LIMIT]],
        "parameter_values": [key for key, _ in parameter_items[:DEPRIORITIZED_LIMIT]],
    }


def update_usage_history(
    protocol: str,
    target_name: str,
    usage_history: Dict[str, Any],
    implementation_metadata: Dict[str, Any],
    generated_testcases: Dict[str, Any],
) -> Dict[str, Any]:
    surface_group_history = usage_history.setdefault("surface_groups", {})
    interaction_history = usage_history.setdefault("interaction_surfaces", {})
    parameter_history = usage_history.setdefault("parameter_values", {})
    usage_history.setdefault("recent_group_surface_choices", {})
    recent_surface_parameter_fields = usage_history.setdefault(
        "recent_surface_parameter_fields", {}
    )
    surface_parameter_values = usage_history.setdefault("surface_parameter_values", {})
    surface_groups = _collect_surface_groups(implementation_metadata)
    surfaces = _collect_known_surfaces(implementation_metadata)
    surface_parameter_fields = _collect_surface_parameter_fields(implementation_metadata)
    parameter_values = _collect_known_parameter_values(implementation_metadata)
    surface_parameter_candidates = _collect_surface_parameter_candidates(implementation_metadata)

    for message in _iter_generated_messages(generated_testcases):
        message_surface = _extract_message_surface(message)
        normalized_message_surface = _normalize_surface_for_matching(message_surface)
        matched_group_keys = set()
        matched_surfaces = set()
        for surface_group in surface_groups:
            group_key = surface_group.get("group_key", "")
            for surface in surface_group.get("surfaces", []):
                if _surfaces_match(surface, normalized_message_surface):
                    matched_group_keys.add(group_key)
                    break
        for group_key in matched_group_keys:
            surface_group_history[group_key] = surface_group_history.get(group_key, 0) + 1
        for surface in surfaces:
            if _surfaces_match(surface, normalized_message_surface):
                interaction_history[surface] = interaction_history.get(surface, 0) + 1
                matched_surfaces.add(surface)
        for parameter_value in parameter_values:
            if parameter_value and parameter_value in message:
                parameter_history[parameter_value] = parameter_history.get(parameter_value, 0) + 1
        for surface in matched_surfaces:
            recent_fields = recent_surface_parameter_fields.setdefault(surface, [])
            for field_name in surface_parameter_fields.get(surface, []):
                if _message_contains_parameter_field(message, field_name):
                    if field_name in recent_fields:
                        recent_fields.remove(field_name)
                    recent_fields.append(field_name)
            if len(recent_fields) > DEPRIORITIZED_LIMIT:
                del recent_fields[:-DEPRIORITIZED_LIMIT]
            surface_values = surface_parameter_values.setdefault(surface, {})
            for field_name, candidate_values in surface_parameter_candidates.get(surface, {}).items():
                for candidate_value in candidate_values:
                    normalized_value = str(candidate_value).strip()
                    if not normalized_value or normalized_value.startswith("{"):
                        continue
                    if normalized_value in message:
                        field_history = surface_values.setdefault(field_name, {})
                        field_history[normalized_value] = field_history.get(normalized_value, 0) + 1

    os.makedirs(USAGE_HISTORY_DIR, exist_ok=True)
    file_path = _get_usage_history_path(protocol, target_name)
    with open(file_path, "w", encoding="utf-8") as f:
        json.dump(usage_history, f, indent=4, ensure_ascii=False)
    return usage_history


def select_surface_group_for_sequence(
    implementation_metadata: Dict[str, Any],
    usage_history: Dict[str, Any],
    type_sequence: List[str],
) -> Dict[str, Any]:
    responses = implementation_metadata.get("responses", [])
    if isinstance(responses, list) and responses:
        matching_groups = []
        for response in responses:
            if not isinstance(response, dict):
                continue
            message_type = str(response.get("message_type", "")).strip()
            if not message_type or message_type not in type_sequence:
                continue
            surfaces = []
            parameter_candidates = {
                "path_params": {},
                "query_params": {},
                "body_fields": {},
                "headers": {},
                "argument_slots": {},
                "field_candidates": {},
            }
            for item in response.get("input_surfaces", []):
                if not isinstance(item, dict):
                    continue
                surface = str(item.get("surface", "")).strip()
                if surface and surface not in surfaces:
                    surfaces.append(surface)
                parameters = item.get("parameters", {})
                if not isinstance(parameters, dict):
                    continue
                for slot_name in parameter_candidates.keys():
                    slot_items = parameters.get(slot_name, [])
                    if not isinstance(slot_items, list):
                        continue
                    for slot_item in slot_items:
                        if not isinstance(slot_item, dict):
                            continue
                        name = str(slot_item.get("name", "")).strip()
                        if not name:
                            continue
                        values = parameter_candidates[slot_name].setdefault(name, [])
                        for value in slot_item.get("values", []):
                            normalized_value = str(value).strip()
                            if normalized_value and normalized_value not in values:
                                values.append(normalized_value)
            if surfaces:
                matching_groups.append(
                    {
                        "group_key": message_type,
                        "surfaces": surfaces,
                        "message_types": [message_type],
                        "parameter_candidates": parameter_candidates,
                    }
                )

        if not matching_groups:
            return {}

        group_counts = usage_history.get("surface_groups", {})
        surface_counts = usage_history.get("interaction_surfaces", {})
        recent_group_surface_choices = usage_history.setdefault("recent_group_surface_choices", {})
        recent_surface_parameter_fields = usage_history.setdefault(
            "recent_surface_parameter_fields", {}
        )

        def _sort_key(surface_group: Dict[str, Any]):
            group_key = surface_group.get("group_key", "")
            surfaces = surface_group.get("surfaces", [])
            surface_usage = min((surface_counts.get(surface, 0) for surface in surfaces), default=0)
            return (
                group_counts.get(group_key, 0),
                surface_usage,
                -len(surfaces),
                group_key,
            )

        selected_group = sorted(matching_groups, key=_sort_key)[0]
        selected_surfaces = selected_group.get("surfaces", [])
        selected_surface = ""
        if selected_surfaces:
            group_key = selected_group.get("group_key", "")
            recent_surfaces = recent_group_surface_choices.setdefault(group_key, [])
            candidate_surfaces = [
                surface for surface in selected_surfaces if surface not in recent_surfaces
            ]
            if not candidate_surfaces:
                recent_surfaces.clear()
                candidate_surfaces = list(selected_surfaces)

            selected_surface = sorted(
                candidate_surfaces,
                key=lambda surface: (surface_counts.get(surface, 0), -len(surface), surface),
            )[0]
            recent_surfaces.append(selected_surface)

        return {
            "group_key": selected_group.get("group_key", ""),
            "selected_surface": selected_surface,
            "group_surfaces": selected_surfaces,
            "message_types": selected_group.get("message_types", []),
            "parameter_candidates": selected_group.get("parameter_candidates", {}),
            "deprioritized_parameter_fields": recent_surface_parameter_fields.get(
                selected_surface, []
            ),
            "required_field_hints": [],
            "format_sensitive_fields": [],
            "sibling_surfaces": [],
            "constraints": [],
            "notes": [],
        }

    surface_groups = implementation_metadata.get("surface_groups", [])
    if not isinstance(surface_groups, list):
        return {}

    matching_groups = []
    for surface_group in surface_groups:
        if not isinstance(surface_group, dict):
            continue
        message_types = surface_group.get("message_types", [])
        if not message_types or any(message_type in type_sequence for message_type in message_types):
            matching_groups.append(surface_group)

    if not matching_groups:
        return {}

    group_counts = usage_history.get("surface_groups", {})
    surface_counts = usage_history.get("interaction_surfaces", {})
    recent_group_surface_choices = usage_history.setdefault("recent_group_surface_choices", {})
    recent_surface_parameter_fields = usage_history.setdefault(
        "recent_surface_parameter_fields", {}
    )

    def _sort_key(surface_group: Dict[str, Any]):
        group_key = surface_group.get("group_key", "")
        surfaces = surface_group.get("surfaces", [])
        surface_usage = min((surface_counts.get(surface, 0) for surface in surfaces), default=0)
        return (
            group_counts.get(group_key, 0),
            surface_usage,
            -len(surfaces),
            group_key,
        )

    selected_group = sorted(matching_groups, key=_sort_key)[0]
    selected_surfaces = selected_group.get("surfaces", [])
    selected_surface = ""
    if selected_surfaces:
        group_key = selected_group.get("group_key", "")
        recent_surfaces = recent_group_surface_choices.setdefault(group_key, [])
        candidate_surfaces = [
            surface for surface in selected_surfaces if surface not in recent_surfaces
        ]
        if not candidate_surfaces:
            recent_surfaces.clear()
            candidate_surfaces = list(selected_surfaces)

        selected_surface = sorted(
            candidate_surfaces,
            key=lambda surface: (surface_counts.get(surface, 0), -len(surface), surface),
        )[0]
        recent_surfaces.append(selected_surface)

    return {
        "group_key": selected_group.get("group_key", ""),
        "selected_surface": selected_surface,
        "group_surfaces": selected_surfaces,
        "message_types": selected_group.get("message_types", []),
        "parameter_candidates": selected_group.get("parameter_candidates", {}),
        "deprioritized_parameter_fields": recent_surface_parameter_fields.get(
            selected_surface, []
        ),
        "required_field_hints": selected_group.get("required_field_hints", []),
        "format_sensitive_fields": selected_group.get("format_sensitive_fields", []),
        "sibling_surfaces": selected_group.get("sibling_surfaces", []),
        "constraints": selected_group.get("constraints", []),
        "notes": selected_group.get("notes", []),
    }


def _iter_generated_messages(generated_testcases: Dict[str, Any]) -> Iterable[str]:
    if not generated_testcases:
        return

    if "sequences" in generated_testcases:
        for sequence in generated_testcases.get("sequences", []):
            for message in sequence.get("messages", []):
                yield message.get("message", "")
        return

    for testcase in generated_testcases.values():
        if not isinstance(testcase, dict):
            continue
        if "sequences" in testcase:
            for sequence in testcase.get("sequences", []):
                for message in sequence.get("messages", []):
                    yield message.get("message", "")


def _collect_known_surfaces(implementation_metadata: Dict[str, Any]) -> List[str]:
    if isinstance(implementation_metadata.get("responses"), list):
        known_surfaces: List[str] = []
        for response in implementation_metadata.get("responses", []):
            if not isinstance(response, dict):
                continue
            for item in response.get("input_surfaces", []):
                if not isinstance(item, dict):
                    continue
                surface = str(item.get("surface", "")).strip()
                if surface and surface not in known_surfaces:
                    known_surfaces.append(surface)
        return known_surfaces

    known_surfaces: List[str] = []
    for surface_list in implementation_metadata.get("interaction_surfaces", {}).values():
        if not isinstance(surface_list, list):
            continue
        for surface in surface_list:
            if surface not in known_surfaces:
                known_surfaces.append(surface)
    return known_surfaces


def _collect_surface_groups(implementation_metadata: Dict[str, Any]) -> List[Dict[str, Any]]:
    if isinstance(implementation_metadata.get("responses"), list):
        collected = []
        for response in implementation_metadata.get("responses", []):
            if not isinstance(response, dict):
                continue
            message_type = str(response.get("message_type", "")).strip()
            surfaces = []
            for item in response.get("input_surfaces", []):
                if not isinstance(item, dict):
                    continue
                surface = str(item.get("surface", "")).strip()
                if surface and surface not in surfaces:
                    surfaces.append(surface)
            if surfaces:
                collected.append({"group_key": message_type, "surfaces": surfaces})
        return collected

    collected = []
    for surface_group in implementation_metadata.get("surface_groups", []):
        if not isinstance(surface_group, dict):
            continue
        group_key = str(surface_group.get("group_key", "")).strip()
        if not group_key:
            continue
        collected.append(
            {
                "group_key": group_key,
                "surfaces": [
                    str(surface)
                    for surface in surface_group.get("surfaces", [])
                    if str(surface).strip()
                ],
            }
        )
    return collected


def _extract_message_surface(message: str) -> str:
    first_line = str(message or "").splitlines()[0] if str(message or "").splitlines() else ""
    parts = first_line.strip().split()
    if len(parts) >= 2 and parts[1].startswith("/"):
        return parts[1].split("?", 1)[0]
    return first_line.strip()


def _normalize_group_segment(segment: str) -> str:
    token = str(segment or "").strip().lower().strip("{}")
    if not token:
        return ""
    if token in {"int", "hex", "id", "uuid", "byte", "num", "number"} or token.isdigit():
        return "{id}"
    return token


def _group_key_from_surface(surface: str) -> str:
    normalized_surface = str(surface or "").strip()
    if not normalized_surface:
        return ""
    if normalized_surface.startswith("/"):
        segments = [
            _normalize_group_segment(segment)
            for segment in normalized_surface.split("/")
            if segment.strip()
        ]
        segments = [segment for segment in segments if segment]
        if len(segments) >= 3 and segments[0] in GENERIC_WRAPPER_SEGMENTS:
            return "/".join(segments[1:3])
        return "/".join(segments[:2])
    tokens = [
        _normalize_group_segment(token)
        for token in normalized_surface.replace(":", "/").split("/")
        if token.strip()
    ]
    tokens = [token for token in tokens if token]
    return "/".join(tokens[:2])


def _normalize_surface_for_matching(surface: str) -> str:
    normalized_surface = str(surface or "").strip()
    if not normalized_surface:
        return ""
    if not normalized_surface.startswith("/"):
        if normalized_surface.startswith("http://") or normalized_surface.startswith("https://"):
            normalized_surface = "/" + normalized_surface.split("://", 1)[1].split("/", 1)[1]
        else:
            normalized_surface = "/" + normalized_surface.lstrip("/")

    path = normalized_surface.split("?", 1)[0]
    segments = []
    for segment in path.split("/"):
        stripped = segment.strip()
        if not stripped:
            continue
        token = stripped.lower()
        if token.isdigit() or token in {"int", "hex", "id", "uuid", "byte", "num", "number"}:
            segments.append("{id}")
        elif re.fullmatch(r"\{[^{}]+\}", stripped):
            segments.append("{id}")
        else:
            segments.append(stripped)
    return "/" + "/".join(segments)


def _surfaces_match(candidate_surface: str, normalized_message_surface: str) -> bool:
    if not candidate_surface or not normalized_message_surface:
        return False
    return _normalize_surface_for_matching(candidate_surface) == normalized_message_surface


def _collect_known_parameter_values(implementation_metadata: Dict[str, Any]) -> List[str]:
    if isinstance(implementation_metadata.get("responses"), list):
        collected: List[str] = []
        for response in implementation_metadata.get("responses", []):
            if not isinstance(response, dict):
                continue
            for item in response.get("input_surfaces", []):
                if not isinstance(item, dict):
                    continue
                parameters = item.get("parameters", {})
                if not isinstance(parameters, dict):
                    continue
                for slot_items in parameters.values():
                    if not isinstance(slot_items, list):
                        continue
                    for slot_item in slot_items:
                        if not isinstance(slot_item, dict):
                            continue
                        for value in slot_item.get("values", []):
                            normalized_value = str(value).strip()
                            if normalized_value and normalized_value not in collected:
                                collected.append(normalized_value)
        return collected

    collected: List[str] = []
    top_level = implementation_metadata.get("parameter_candidates", {})
    for slot_values in top_level.values():
        if not isinstance(slot_values, dict):
            continue
        for values in slot_values.values():
            if not isinstance(values, list):
                continue
            for value in values:
                if value not in collected:
                    collected.append(value)
    return collected


def _collect_surface_parameter_fields(
    implementation_metadata: Dict[str, Any]
) -> Dict[str, List[str]]:
    if isinstance(implementation_metadata.get("responses"), list):
        collected: Dict[str, List[str]] = {}
        for response in implementation_metadata.get("responses", []):
            if not isinstance(response, dict):
                continue
            for item in response.get("input_surfaces", []):
                if not isinstance(item, dict):
                    continue
                surface = str(item.get("surface", "")).strip()
                if not surface:
                    continue
                field_names: List[str] = []
                parameters = item.get("parameters", {})
                if isinstance(parameters, dict):
                    for slot_items in parameters.values():
                        if not isinstance(slot_items, list):
                            continue
                        for slot_item in slot_items:
                            if not isinstance(slot_item, dict):
                                continue
                            name = str(slot_item.get("name", "")).strip()
                            if name and name not in field_names:
                                field_names.append(name)
                collected[surface] = field_names
        return collected

    collected: Dict[str, List[str]] = {}
    for surface_group in implementation_metadata.get("surface_groups", []):
        if not isinstance(surface_group, dict):
            continue
        field_names: List[str] = []
        parameter_candidates = surface_group.get("parameter_candidates", {})
        if isinstance(parameter_candidates, dict):
            for slot_values in parameter_candidates.values():
                if not isinstance(slot_values, dict):
                    continue
                for field_name in slot_values.keys():
                    normalized_field_name = str(field_name).strip()
                    if normalized_field_name and normalized_field_name not in field_names:
                        field_names.append(normalized_field_name)
        for surface in surface_group.get("surfaces", []):
            normalized_surface = str(surface).strip()
            if normalized_surface:
                collected[normalized_surface] = list(field_names)
    return collected


def _collect_surface_parameter_candidates(
    implementation_metadata: Dict[str, Any]
) -> Dict[str, Dict[str, List[str]]]:
    collected: Dict[str, Dict[str, List[str]]] = {}
    responses = implementation_metadata.get("responses", [])
    if not isinstance(responses, list):
        return collected

    for response in responses:
        if not isinstance(response, dict):
            continue
        for item in response.get("input_surfaces", []):
            if not isinstance(item, dict):
                continue
            surface = str(item.get("surface", "")).strip()
            if not surface:
                continue
            parameters = item.get("parameters", {})
            if not isinstance(parameters, dict):
                continue
            surface_candidates = collected.setdefault(surface, {})
            for slot_items in parameters.values():
                if not isinstance(slot_items, list):
                    continue
                for slot_item in slot_items:
                    if not isinstance(slot_item, dict):
                        continue
                    name = str(slot_item.get("name", "")).strip()
                    if not name:
                        continue
                    values = surface_candidates.setdefault(name, [])
                    for value in slot_item.get("values", []):
                        normalized_value = str(value).strip()
                        if normalized_value and normalized_value not in values:
                            values.append(normalized_value)
    return collected


def get_used_values_for_surface_field(
    usage_history: Dict[str, Any],
    surface: str,
    field_name: str,
) -> List[str]:
    if not isinstance(usage_history, dict):
        return []
    surface_values = usage_history.get("surface_parameter_values", {})
    if not isinstance(surface_values, dict):
        return []
    field_history = surface_values.get(surface, {}).get(field_name, {})
    if not isinstance(field_history, dict):
        return []
    return [
        value
        for value, count in field_history.items()
        if str(value).strip() and isinstance(count, int) and count > 0
    ]


def _message_contains_parameter_field(message: str, field_name: str) -> bool:
    escaped = re.escape(str(field_name))
    patterns = (
        rf'"{escaped}"\s*:',
        rf"{escaped}\s*=",
        rf"{escaped}:",
    )
    return any(re.search(pattern, message) for pattern in patterns)
