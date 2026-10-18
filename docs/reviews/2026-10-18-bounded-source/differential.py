"""Record actual public admission outcomes in one isolated source checkout."""
import hashlib
import json
import sys
from pathlib import Path

from axiom.model import DiagnosticError
from axiom.source_profiles import SourceLimitsV2, SourceProfileV2, admit_source_v2
from tests.test_source_names_v2 import accepted_cases, rejected_cases


def record(source):
    try:
        admitted = admit_source_v2(source, profile=SourceProfileV2(), limits=SourceLimitsV2())
    except DiagnosticError as error:
        return {"status": "rejected", "code": error.code, "message": error.message,
                "span": [error.span.offset, error.span.length]}
    return {
        "status": "accepted",
        "fields": {field: getattr(admitted, field) for field in (
            "source_digest", "height", "width", "input_interval", "cap",
            "family_digest", "specialization_digest", "constraint_digest",
            "objective_digest", "version")},
        "objective": admitted.objective.value,
        "exact_source": admitted.source_bytes == source,
        "original_ast_sha256": hashlib.sha256(repr(admitted.source_module).encode()).hexdigest(),
    }


outcomes = {kind: {name: record(source) for name, source in cases()}
            for kind, cases in (("accepted", accepted_cases), ("rejected", rejected_cases))}
Path(sys.argv[1]).write_text(json.dumps(outcomes, indent=2, sort_keys=True) + "\n")
print(f"Recorded {len(outcomes['accepted'])} accepted and {len(outcomes['rejected'])} rejected cases")
