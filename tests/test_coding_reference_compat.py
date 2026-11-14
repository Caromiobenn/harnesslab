import hashlib
from types import SimpleNamespace

import pytest

from harnesslab.coding.reference_compat import patch_protein_reference

SOURCE = b"""def get_single_fasta(data):
    seq = list(data["entity_poly"]["pdbx_seq_one_letter_code_can"])
    return "".join(seq)


def get_pdb_title():
    return "unchanged title lookup"
"""


def test_missing_feature_uses_public_component_metadata_without_hardcoded_sequence():
    urls = []

    def get(url, timeout):
        urls.append((url, timeout))
        return SimpleNamespace(
            raise_for_status=lambda: None,
            json=lambda: {"chem_comp": {"mon_nstd_parent_comp_id": ["GLY", "TYR", "GLY"]}},
        )

    scope = {"requests": SimpleNamespace(get=get), "THREE_TO_ONE": {"GLY": "G", "TYR": "Y"}}
    patched = patch_protein_reference(SOURCE, hashlib.sha256(SOURCE).hexdigest())
    exec(compile(patched, "reference-copy.py", "exec"), scope)
    assert (
        scope["get_single_fasta"](
            {
                "entity_poly": {
                    "pdbx_seq_one_letter_code_can": "AXT",
                    "pdbx_seq_one_letter_code": "A(CR2)\nT",
                }
            }
        )
        == "AGYGT"
    )
    assert urls == [("https://data.rcsb.org/rest/v1/core/chemcomp/CR2", 20)]
    assert scope["get_pdb_title"]() == "unchanged title lookup"
    urls.clear()
    assert (
        scope["get_single_fasta"]({"entity_poly": {"pdbx_seq_one_letter_code_can": "AGT"}}) == "AGT"
    )
    assert urls == []


def test_reference_compatibility_requires_the_pinned_source_and_one_exact_lookup():
    with pytest.raises(ValueError, match="source changed"):
        patch_protein_reference(SOURCE, "0" * 64)
    changed = SOURCE.replace(b"def get_pdb_title", b"def renamed_lookup")
    with pytest.raises(ValueError, match="exactly once"):
        patch_protein_reference(changed, hashlib.sha256(changed).hexdigest())
