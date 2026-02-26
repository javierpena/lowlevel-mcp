#!/usr/bin/env python3

"""List processes allowed to run on specific CPU.

Returns list of PIDs and process names for processes whose CPU affinity
includes the specified CPU number.
"""

import argparse
from pathlib import Path
from cpu_intersect import parse_cpus_allowed


def get_processes_for_cpu(cpu_num):
    """Get all processes allowed to run on specified CPU.

    Args:
        cpu_num: CPU number (0-based)

    Returns:
        List of tuples: [(pid, process_name), ...]
    """
    procs = []
    for p in Path('/proc').glob('[0-9]*'):
        try:
            status = (p / 'status').read_text()
            name = cpus_allowed = None

            for line in status.splitlines():
                if line.startswith('Name:'):
                    name = line.split(':', 1)[1].strip()
                elif line.startswith('Cpus_allowed:'):
                    cpus_allowed = line.split(':', 1)[1].strip()

            if cpus_allowed and name:
                cpus = parse_cpus_allowed(cpus_allowed)
                if cpu_num in cpus:
                    procs.append((int(p.name), name))
        except (PermissionError, FileNotFoundError, ProcessLookupError):
            pass

    return sorted(procs)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(
        description='List processes allowed to run on specific CPU'
    )
    parser.add_argument('cpu', type=int, help='CPU number (0-based)')
    args = parser.parse_args()

    procs = get_processes_for_cpu(args.cpu)

    if not procs:
        print(f"No processes found for CPU {args.cpu}")
    else:
        print(f"Processes allowed on CPU {args.cpu} ({len(procs)} total):")
        for pid, name in procs:
            print(f"{pid:>6}  {name}")
