import argparse
import os
from typing import Any, Dict, List, Optional, Tuple

from LLM.normal_sequence import get_message_sequences
from LLM.parameter import build_implementation_metadata
from LLM.protocol_types import get_protocol_message_types
from LLM.repeated_sequence import get_repeated_message_sequences
from LLM.specialized_structures import get_specialized_structures
from LLM.testcases import get_test_cases
from utility.usage_history import (
    load_usage_history,
    update_usage_history,
)
from utility.utility import load_seed_messages, set_raw_output_dir


def _build_sequence_batches(
    protocol: str,
    message_types: Dict[str, Any],
) -> List[Tuple[str, Dict[str, Any]]]:
    batches: List[Tuple[str, Dict[str, Any]]] = [
        ("len3", get_message_sequences(protocol, message_types, 3)),
        ("len5", get_message_sequences(protocol, message_types, 5)),
    ]

    repeated_message_sequences = get_repeated_message_sequences(protocol, message_types)
    if repeated_message_sequences and repeated_message_sequences.get("sequences"):
        batches.append(("repeated", repeated_message_sequences))

    return batches


def _load_seed_inputs(seed_messages_dir: Optional[str]) -> Tuple[Optional[List[str]], Optional[List[str]]]:
    if not seed_messages_dir:
        return None, None
    return load_seed_messages(seed_messages_dir)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--protocol", "-p", type=str, required=True)
    parser.add_argument("--output_dir", "-o", type=str, required=False, default="results")
    parser.add_argument(
        "--metadata_only",
        action="store_true",
        help="Build implementation metadata and exit before testcase generation.",
    )
    parser.add_argument(
        "--protocol_types_only",
        action="store_true",
        help="Extract protocol message types and exit before downstream stages.",
    )
    parser.add_argument(
        "--specialized_structures_only",
        action="store_true",
        help="Extract specialized structures and exit before testcase generation.",
    )
    parser.add_argument(
        "--sequence_only",
        action="store_true",
        help="Generate message sequences and exit before metadata, structures, and testcase generation.",
    )
    parser.add_argument(
        "--seed_messages",
        "-s",
        type=str,
        required=False,
        default=None,
        help="Path to initial seed messages",
    )
    args = parser.parse_args()

    protocol = args.protocol
    output_dir = args.output_dir
    set_raw_output_dir(output_dir)
    seed_messages_dir = args.seed_messages
    metadata_only = args.metadata_only
    protocol_types_only = args.protocol_types_only
    specialized_structures_only = args.specialized_structures_only
    sequence_only = args.sequence_only
    target_name = os.getenv("STELLAFUZZ_TARGET_NAME")
    protocol_hint = os.getenv("STELLAFUZZ_PROTOCOL_HINT") or protocol
    if not target_name:
        raise SystemExit("STELLAFUZZ_TARGET_NAME environment variable is required")

    print(f"SteLLaFuzz target: {target_name}")

    try:
        file_names, seed_messages = _load_seed_inputs(seed_messages_dir)

        message_types = get_protocol_message_types(protocol)
        if protocol_types_only:
            print("Protocol-types-only mode enabled. Exiting before downstream stages.")
            return
        if sequence_only:
            _build_sequence_batches(protocol, message_types)
            print("Sequence-only mode enabled. Exiting after sequence generation.")
            return

        extra_context: Dict[str, Any] = {
            "application_protocol_hint": protocol_hint,
        }
        if seed_messages:
            extra_context["raw_seed_messages"] = seed_messages
            extra_context["raw_seed_file_names"] = file_names or []

        implementation_metadata = build_implementation_metadata(
            protocol=protocol,
            target_name=target_name,
            message_types=message_types,
            extra_context=extra_context,
        )
        if metadata_only:
            print("Metadata-only mode enabled. Exiting before testcase generation.")
            return

        specialized_structures = get_specialized_structures(protocol, message_types)
        if specialized_structures_only:
            print("Specialized-structures-only mode enabled. Exiting before sequence and testcase generation.")
            return
        sequence_batches = _build_sequence_batches(protocol, message_types)

        usage_history = load_usage_history(protocol, target_name)

        if seed_messages:
            for seed_message in seed_messages:
                for _batch_name, message_sequence_batch in sequence_batches:
                    generated_testcases = get_test_cases(
                        protocol,
                        message_sequence_batch,
                        specialized_structures,
                        implementation_metadata,
                        usage_history,
                    )
                    usage_history = update_usage_history(
                        protocol,
                        target_name,
                        usage_history,
                        implementation_metadata,
                        generated_testcases,
                    )
        else:
            for _batch_name, message_sequence_batch in sequence_batches:
                generated_testcases = get_test_cases(
                    protocol,
                    message_sequence_batch,
                    specialized_structures,
                    implementation_metadata,
                    usage_history,
                )
                usage_history = update_usage_history(
                    protocol,
                    target_name,
                    usage_history,
                    implementation_metadata,
                    generated_testcases,
                )
    except Exception as e:
        print(f"Error processing protocol {protocol}: {e}")


if __name__ == "__main__":
    main()
