"""Recover only sandboxes bearing one exact next-framework run identifier."""
from e2b import Sandbox
from e2b.sandbox.sandbox_api import SandboxQuery
from sandbox_profile import benchmark_profile_file, load_profile
import time
import httpx


def cleanup_run(root, run_id, profile_file=None, expected_ids=()):
    if not run_id:
        raise ValueError("An explicit owned run ID is required")
    profile = load_profile(root, benchmark_profile_file(root, profile_file))
    def owned():
        pages = Sandbox.list(query=SandboxQuery(metadata={"benchmark_next_run": run_id}),
                             limit=100, request_timeout=20, **profile.client_kwargs())
        items = []
        while pages.has_next:
            for row in pages.next_items():
                if (row.metadata or {}).get("benchmark_next_run") != run_id:
                    raise RuntimeError("Sandbox service ignored the exact run ownership filter")
                items.append(row)
        return items
    def exists(sandbox_id):
        response = httpx.get(profile.api_url + "/sandboxes/" + sandbox_id,
                             headers={"X-API-KEY": profile.api_key}, timeout=20)
        if response.status_code == 404:
            return False
        response.raise_for_status()
        if (response.json().get("metadata") or {}).get("benchmark_next_run") != run_id:
            raise RuntimeError("Sandbox ID does not match the exact run ownership")
        return True
    # The list API is eventually consistent immediately after creation. IDs
    # returned by create must be checked directly even when listing is empty.
    known = set(expected_ids) | {row.sandbox_id for row in owned()}
    attempted, errors = set(), []
    remaining = {sandbox_id for sandbox_id in known if exists(sandbox_id)}
    for attempt in range(3):
        if not remaining:
            break
        for sandbox_id in remaining:
            attempted.add(sandbox_id)
            try:
                Sandbox.kill(sandbox_id, request_timeout=20, **profile.client_kwargs())
            except Exception as exc:
                errors.append({"sandbox_id": sandbox_id, "type": type(exc).__name__})
        # Some regional DELETE responses report 500 after successful removal.
        known.update(row.sandbox_id for row in owned())
        remaining = {sandbox_id for sandbox_id in known if exists(sandbox_id)}
        if remaining and attempt < 2:
            time.sleep(2)
    ids = sorted(remaining)
    return {"run_id": run_id, "recovered": sorted(attempted - set(ids)),
            "remaining": ids, "verified": not ids, "delete_errors": errors,
            "checked_ids": sorted(known), "check": "management_api_404"}
