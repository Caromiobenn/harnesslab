"""Reference-only compatibility for a public database's component representation."""

import hashlib
import shutil
from pathlib import Path

from harnesslab.coding.config import save_json
from harnesslab.coding.controls import NativeOracleControl

ORIGINAL_RETURN = '    return "".join(seq)\n\n\ndef get_pdb_title'
COMPONENT_FALLBACK = """    if "X" in seq:
        import re

        def component_parents(match):
            response = requests.get(
                "https://data.rcsb.org/rest/v1/core/chemcomp/" + match.group(1),
                timeout=20,
            )
            response.raise_for_status()
            parents = response.json()["chem_comp"]["mon_nstd_parent_comp_id"]
            return "".join(THREE_TO_ONE[parent] for parent in parents)

        raw = data["entity_poly"]["pdbx_seq_one_letter_code"].replace("\\n", "")
        resolved = re.sub(r"\\(([^)]+)\\)", component_parents, raw)
        if "X" in resolved:
            raise ValueError("Public component metadata left an unresolved residue")
        return resolved
    return "".join(seq)


def get_pdb_title"""


def patch_protein_reference(source: bytes, expected_sha256: str) -> bytes:
    if hashlib.sha256(source).hexdigest() != expected_sha256:
        raise ValueError("Official reference source changed")
    text = source.decode()
    if text.count(ORIGINAL_RETURN) != 1:
        raise ValueError("Expected public sequence lookup was not found exactly once")
    return text.replace(ORIGINAL_RETURN, COMPONENT_FALLBACK).encode()


class ProteinPublicReferenceControl(NativeOracleControl):
    """Execute a labelled reference copy, never installed into model task inputs."""

    @staticmethod
    def name():
        return "harnesslab-protein-public-reference-compatibility"

    def __init__(self, logs_dir, task_dir, *args, source_sha256, network_mode, **kwargs):
        if network_mode != "public" or Path(task_dir).name != "protein-assembly":
            raise ValueError("This compatibility control requires the online protein task")
        source = Path(task_dir) / "solution/solve.sh"
        patched = patch_protein_reference(source.read_bytes(), source_sha256)
        copied = Path(logs_dir) / "reference-compatibility/task"
        shutil.copytree(task_dir, copied)
        (copied / "solution/solve.sh").write_bytes(patched)
        save_json(
            Path(logs_dir) / "reference-compatibility/provenance.json",
            {
                "method": "public-chemcomp-parent-lookup",
                "original_source": str(source),
                "original_sha256": source_sha256,
                "patched_sha256": hashlib.sha256(patched).hexdigest(),
                "model_calls": 0,
                "model_inputs_changed": False,
            },
        )
        super().__init__(logs_dir, copied, *args, network_mode=network_mode, **kwargs)
