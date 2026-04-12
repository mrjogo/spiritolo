#!/usr/bin/env python3
# [repo-mixin:devcontainer-claude] Settings management utility.
# Sorts and merges Claude permissions in settings.json. Useful when multiple
# mixins or manual edits add permissions that need to be kept organized.
#
# Usage:
#   python .claude/manage_settings.py                              # sort in place
#   python .claude/manage_settings.py --dry-run                    # preview
#   python .claude/manage_settings.py --merge other/settings.json  # merge + sort
"""
Script to manage Claude settings.json file permissions sorting.
Reads a Claude settings JSON file, sorts the permissions.allow array
according to a custom sort function, and writes it back in place
while preserving all other formatting and content.
"""

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict


# Prefixes to move to the back for sorting
MOVE_TO_BACK_PREFIXES = [
    "timeout",  # This will match any timeout command
]


def custom_sort_key(permission: str) -> tuple:
    """
    Custom sort function for permissions with smart numbering and prefix handling.

    Features:
    - Parse "Command(argument)" format
    - Sort first by command alphabetically
    - Sort second by argument with smart numbering and prefix handling
    - Prefix handling only applies to the argument part

    Args:
        permission: A permission string like "Bash(ls:*)" or "WebFetch(domain:github.com)"

    Returns:
        A tuple that can be used for sorting
    """
    import re

    # Parse the "Command(argument)" format
    match = re.match(r"^([^(]+)\(([^)]*)\)$", permission)
    if match:
        command = match.group(1).strip().lower()
        argument = match.group(2).strip().lower()
    else:
        # Fallback for strings that don't match the expected format
        command = permission.lower()
        argument = ""

    # Handle prefix moving in the argument only (e.g., "timeout 5s ros2:*" -> "ros2:* timeout 5s")
    processed_argument = argument
    for prefix in MOVE_TO_BACK_PREFIXES:
        # Match timeout followed by a duration and then the actual command
        prefix_pattern = rf"^{re.escape(prefix)}\s+(\d+s)\s+(.*)"
        match_result = re.match(prefix_pattern, processed_argument)
        if match_result:
            # Extract the duration and command parts
            duration = match_result.group(1)
            command_part = match_result.group(2)
            processed_argument = f"{command_part} {prefix} {duration}"
            break

    # Smart numbering: split into parts and handle numbers specially
    def smart_split(text):
        """Split text into parts, converting numeric parts to integers for proper sorting."""
        parts = []
        # Split on numbers while keeping them
        tokens = re.split(r"(\d+)", text)
        for token in tokens:
            if token.isdigit():
                parts.append((0, int(token)))  # Numbers sort first, as integers
            else:
                parts.append((1, token))  # Text sorts second, as strings
        return parts

    # Return tuple: (command_parts, argument_parts)
    return (smart_split(command), smart_split(processed_argument))


def load_json_with_formatting(file_path: Path) -> tuple[Dict[str, Any], str]:
    """
    Load JSON file and return both parsed content and original text.

    Args:
        file_path: Path to the JSON file

    Returns:
        Tuple of (parsed_json, original_text)
    """
    with open(file_path, "r", encoding="utf-8") as f:
        original_text = f.read()

    try:
        parsed_json = json.loads(original_text)
        return parsed_json, original_text
    except json.JSONDecodeError as e:
        print(f"Error parsing JSON file: {e}", file=sys.stderr)
        sys.exit(1)


def sort_permissions_allow(data: Dict[str, Any]) -> None:
    """
    Sort the permissions.allow array in place using the custom sort function.

    Args:
        data: The parsed JSON data
    """
    if "permissions" not in data:
        print("Warning: 'permissions' key not found in JSON", file=sys.stderr)
        return

    if "allow" not in data["permissions"]:
        print("Warning: 'permissions.allow' key not found in JSON", file=sys.stderr)
        return

    if not isinstance(data["permissions"]["allow"], list):
        print("Warning: 'permissions.allow' is not a list", file=sys.stderr)
        return

    # Sort the allow array using the custom sort function
    data["permissions"]["allow"].sort(key=custom_sort_key)


def write_json_preserving_format(
    file_path: Path, data: Dict[str, Any], original_text: str
) -> None:
    """
    Write JSON back to file, attempting to preserve original formatting.

    Args:
        file_path: Path to write the file
        data: The modified JSON data
        original_text: Original file content for format reference
    """
    import re

    # Convert to JSON string with compact formatting first
    new_json = json.dumps(data, indent=2, ensure_ascii=False)

    # Analyze original formatting patterns for arrays
    lines = original_text.split("\n")

    # Check if arrays were originally compact (single line)
    compact_array_pattern = r'^\s*"[^"]+": \[.*\],$'
    has_compact_arrays = any(re.match(compact_array_pattern, line) for line in lines)

    if has_compact_arrays:
        # Convert specific arrays back to compact format
        # Look for patterns like "ask": [ and "additionalDirectories": [
        new_lines = new_json.split("\n")
        result_lines = []
        i = 0

        while i < len(new_lines):
            line = new_lines[i]

            # Check if this line starts an array that should be compact
            if (
                '"ask": [' in line or '"additionalDirectories": [' in line
            ) and line.strip().endswith("["):
                # Find the closing bracket
                array_content = []
                i += 1
                indent = len(line) - len(line.lstrip())

                while i < len(new_lines) and not new_lines[i].strip().startswith("]"):
                    content_line = new_lines[i].strip()
                    if content_line.endswith(","):
                        content_line = content_line[:-1]  # Remove comma
                    if content_line.startswith('"') and content_line.endswith('"'):
                        array_content.append(content_line)
                    i += 1

                # Create compact array line
                if array_content:
                    if '"ask": [' in line:
                        compact_line = (
                            " " * indent + f'"ask": [{", ".join(array_content)}],'
                        )
                    else:  # additionalDirectories
                        compact_line = (
                            " " * indent
                            + f'"additionalDirectories": [{", ".join(array_content)}],'
                        )
                    result_lines.append(compact_line)
                else:
                    result_lines.append(line)

                # Skip the closing bracket line since we handled it
                if i < len(new_lines):
                    i += 1
            else:
                result_lines.append(line)
                i += 1

        new_json = "\n".join(result_lines)

    # Write the formatted JSON
    with open(file_path, "w", encoding="utf-8") as f:
        f.write(new_json)
        f.write("\n")  # Add trailing newline


def main():
    """Main function to handle command line arguments and execute the sorting."""
    parser = argparse.ArgumentParser(
        description="Sort permissions.allow in Claude settings.json file. Optionally merge permissions from another file first."
    )
    parser.add_argument(
        "file_path",
        nargs="?",
        default=".claude/settings.json",
        help="Path to the Claude settings.json file (default: .claude/settings.json)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be changed without modifying the file",
    )
    parser.add_argument(
        "--merge",
        help="Path to a second settings.json file to merge permissions.allow from",
    )

    args = parser.parse_args()

    file_path = Path(args.file_path)

    if not file_path.exists():
        print(f"Error: File '{file_path}' does not exist", file=sys.stderr)
        sys.exit(1)

    # Load the JSON file
    data, original_text = load_json_with_formatting(file_path)

    # Handle merging if requested
    if args.merge:
        merge_path = Path(args.merge)
        if not merge_path.exists():
            print(f"Error: Merge file '{merge_path}' does not exist", file=sys.stderr)
            sys.exit(1)

        # Load the merge file
        merge_data, _ = load_json_with_formatting(merge_path)

        # Merge permissions.allow arrays
        if "permissions" in merge_data and "allow" in merge_data["permissions"]:
            if "permissions" not in data:
                data["permissions"] = {}
            if "allow" not in data["permissions"]:
                data["permissions"]["allow"] = []

            # Add permissions from merge file that aren't already present
            existing_permissions = set(data["permissions"]["allow"])
            merge_permissions = merge_data["permissions"]["allow"]

            for permission in merge_permissions:
                if permission not in existing_permissions:
                    data["permissions"]["allow"].append(permission)

            print(f"Merged {len(merge_permissions)} permissions from '{merge_path}'")
        else:
            print(
                f"Warning: No permissions.allow found in merge file '{merge_path}'",
                file=sys.stderr,
            )

    # Keep a copy of original permissions for comparison
    original_allow = None
    if "permissions" in data and "allow" in data["permissions"]:
        original_allow = data["permissions"]["allow"].copy()

    # Sort the permissions
    sort_permissions_allow(data)

    # Check if anything changed
    if original_allow is not None:
        new_allow = data["permissions"]["allow"]
        if original_allow == new_allow:
            print("No changes needed - permissions.allow is already sorted correctly")
            return

        if args.dry_run:
            print("Would sort permissions.allow as follows:")
            for i, permission in enumerate(new_allow):
                print(f"  {i+1:2d}. {permission}")
            return

    # Write the sorted file back
    write_json_preserving_format(file_path, data, original_text)
    print(f"Successfully sorted permissions.allow in '{file_path}'")


if __name__ == "__main__":
    main()
