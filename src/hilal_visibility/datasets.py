"""Observation rows loaded as data, without executing batch workflows."""

import ast
import json
from pathlib import Path


def load_observation_rows(path):
    """Read current JSON data or an explicitly supplied legacy Python literal.

    The legacy reader only evaluates the OBSERVATIONS literal; it never
    imports or executes the supplied script.
    """
    path = Path(path)
    text = path.read_text(encoding='utf-8-sig')
    if path.suffix.lower() == '.json':
        payload = json.loads(text)
        if payload.get('schema_version') != 1:
            raise ValueError('Unsupported observation dataset schema')
        rows = payload['observations']
    else:
        tree = ast.parse(text)
        assignment = next(node for node in tree.body if isinstance(node, ast.Assign)
                          and any(isinstance(target, ast.Name) and target.id == 'OBSERVATIONS'
                                  for target in node.targets))
        rows = ast.literal_eval(assignment.value)
    return [tuple(row) for row in rows]
