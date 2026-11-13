"""Explicit one-core task affinity on the approved Hong Kong 2-core/8-GiB allocation."""
import re
import shlex

ADAPTATION = {'allocated_cpus': 2, 'task_cpu_affinity': 1,
              'reason': 'Hong Kong FC requires memory_gib/cpus <= 4; user approved 2 CPUs with one-core task affinity'}


def allocated_cpus(plan):
    adaptation = plan.get('resource_adaptation')
    if adaptation is None:
        return plan['cpus']
    if adaptation != ADAPTATION or plan['cpus'] != 1 or plan['memory_mb'] != 8192:
        raise ValueError('Unsupported CPU resource adaptation')
    return 2


def affinity_probe_command():
    return ("command -v taskset >/dev/null || exit 71; "
            "core=$(awk '$1 == \"Cpus_allowed_list:\" {split($2,a,/[,-]/); print a[1]}' /proc/self/status); "
            "taskset -c \"$core\" /bin/sh -c " + shlex.quote(
                'printf "%s\\n" "$1"; nproc; grep "^Cpus_allowed_list:" /proc/self/status; '
                '/bin/sh -c "grep ^Cpus_allowed_list: /proc/self/status"') + ' sh "$core"')


def parse_affinity_probe(stdout):
    lines = stdout.strip().splitlines()
    if len(lines) != 4 or not re.fullmatch(r'\d+', lines[0]) or lines[1] != '1':
        raise ValueError('Task CPU affinity probe failed')
    core = int(lines[0])
    for line in lines[2:]:
        if line.split() != ['Cpus_allowed_list:', str(core)]:
            raise ValueError('Parent or child task can use more than the selected CPU')
    return {'core': core, 'effective_cpus': 1, 'parent_allowed': str(core), 'child_allowed': str(core)}


def restrict_command(command, core):
    if not isinstance(core, int) or isinstance(core, bool) or core < 0:
        raise ValueError('CPU affinity core must be a nonnegative integer')
    return 'exec taskset -c ' + str(core) + ' /bin/bash -c ' + shlex.quote(command)
