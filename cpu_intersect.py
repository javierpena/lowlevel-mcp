#!/usr/bin/env python3

"""Find processes with intersecting CPU affinity from different cgroups.

Implementation:
- Parse /proc/*/status for Cpus_allowed masks
- Parse /proc/*/cgroup for cgroup identifiers
- Filter by CPU list, cgroup names, or process names
- Group processes by cgroup, compute CPU union per cgroup
- Compare cgroup pairs for CPU set intersections - O(n + c²) vs O(n²)
- Report cgroup pairs with overlapping CPU sets

Output shows shared CPUs for each conflicting cgroup pair.

Use case - detect CPU affinity conflicts between cgroups (Kubernetes pods,
systemd services, containers, etc.) on the same node.
"""

import argparse
from pathlib import Path


def parse_cpus_allowed(mask):
    """Convert hex CPU mask to set of CPU numbers."""
    cpus = set()
    val = int(mask.replace(',', ''), 16)
    bit = 0
    while val:
        if val & 1:
            cpus.add(bit)
        val >>= 1
        bit += 1
    return cpus


def get_cgroup(cgroup_text):
    """Extract cgroup identifier from cgroup file."""
    for line in cgroup_text.splitlines():
        parts = [p for p in line.split('/') if p and not p.startswith('0::')]
        if not parts:
            continue

        # Prefer pod cgroups for k8s
        for part in parts:
            if part.startswith('pod'):
                return part

        # Use deepest meaningful cgroup (skip generic slices)
        for part in reversed(parts):
            if part not in ('user.slice', 'system.slice', 'machine.slice'):
                return part

    return None


def get_proc_info(cpu_filter=None, ignore_cgroups=None, ignore_procs=None):
    """Get CPU affinity and cgroup for all processes.

    Args:
        cpu_filter: Set of CPU numbers to filter by. Only include processes
                   whose CPU affinity intersects with this set.
        ignore_cgroups: Set of cgroup names to ignore.
        ignore_procs: Set of process names to ignore.
    """
    if ignore_cgroups is None:
        ignore_cgroups = set()
    if ignore_procs is None:
        ignore_procs = set()

    procs = {}
    for p in Path('/proc').glob('[0-9]*'):
        try:
            status = (p / 'status').read_text()
            name = cpus_allowed = None

            for line in status.splitlines():
                if line.startswith('Name:'):
                    name = line.split(':', 1)[1].strip()
                elif line.startswith('Cpus_allowed:'):
                    cpus_allowed = line.split(':', 1)[1].strip()

            if name in ignore_procs:
                continue

            cgroup = None
            try:
                if cgroup_text := (p / 'cgroup').read_text():
                    cgroup = get_cgroup(cgroup_text)
            except (PermissionError, FileNotFoundError):
                pass

            if cgroup in ignore_cgroups:
                continue

            if cpus_allowed and (cpus := parse_cpus_allowed(cpus_allowed)):
                if cpu_filter is None or cpus & cpu_filter:
                    procs[p.name] = {'name': name, 'cpus': cpus, 'cgroup': cgroup}
        except (PermissionError, FileNotFoundError, ProcessLookupError):
            pass
    return procs


def find_cgroup_mismatches(procs, verbose=False):
    """Find cgroups with intersecting CPUs. O(n + c²) vs O(n²)."""
    # Group processes by cgroup
    by_cgroup = {}
    for pid, info in procs.items():
        if cg := info['cgroup']:
            by_cgroup.setdefault(cg, []).append(pid)

    # Compute CPU union per cgroup
    cgroup_cpus = {}
    for cg, pids in by_cgroup.items():
        cgroup_cpus[cg] = set().union(*(procs[pid]['cpus'] for pid in pids))

    if verbose:
        print(f"Cgroups: {len(cgroup_cpus)}, Processes: {len(procs)}")
        for cg, cpus in sorted(cgroup_cpus.items()):
            print(f"  {cg}: {len(by_cgroup[cg])} procs, {len(cpus)} CPUs")
        print()

    # Compare cgroup pairs
    mismatches = []
    cgroups = list(cgroup_cpus.keys())
    for i, cg1 in enumerate(cgroups):
        for cg2 in cgroups[i+1:]:
            if shared := cgroup_cpus[cg1] & cgroup_cpus[cg2]:
                # Show all process pairs
                for pid1 in by_cgroup[cg1]:
                    for pid2 in by_cgroup[cg2]:
                        mismatches.append((pid1, pid2, shared))

    return mismatches


def fmt_cpus(cpus):
    """Format CPU set as compact ranges (e.g., 0-3,5,7-9)."""
    if not cpus:
        return ""
    sorted_cpus = sorted(cpus)
    ranges = []
    start = end = sorted_cpus[0]

    for cpu in sorted_cpus[1:]:
        if cpu == end + 1:
            end = cpu
        else:
            ranges.append(f"{start}-{end}" if start != end else str(start))
            start = end = cpu
    ranges.append(f"{start}-{end}" if start != end else str(start))
    return ",".join(ranges)


def print_stats(procs):
    """Print statistics for cgroups and processes."""
    # Group by cgroup
    by_cgroup = {}
    no_cgroup = []
    for pid, info in procs.items():
        if cg := info['cgroup']:
            by_cgroup.setdefault(cg, []).append(pid)
        else:
            no_cgroup.append(pid)

    # Compute CPU union per cgroup
    cgroup_cpus = {}
    for cg, pids in by_cgroup.items():
        cgroup_cpus[cg] = set().union(*(procs[pid]['cpus'] for pid in pids))

    # Sort by process count descending, show top 20
    sorted_cgroups = sorted(by_cgroup.items(), key=lambda x: len(x[1]), reverse=True)[:20]

    print(f"Processes: {len(procs)}, Cgroups: {len(by_cgroup)}, No cgroup: {len(no_cgroup)}")
    for cg, pids in sorted_cgroups:
        cpus = cgroup_cpus[cg]
        print(f"{cg}: {len(pids)} procs, CPUs: {fmt_cpus(cpus)} ({len(cpus)} total)")


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Find CPU affinity conflicts between cgroups')
    parser.add_argument('-v', '--verbose', action='store_true', help='show all process pairs')
    parser.add_argument('-s', '--stats', action='store_true', help='show cgroup and process statistics')
    parser.add_argument('-c', '--cpus', help='filter by CPU list (e.g., 0,1,2)')
    parser.add_argument('-i', '--ignore-cgroups', help='ignore cgroups (comma-separated)')
    parser.add_argument('-I', '--ignore-procs', help='ignore process names (comma-separated)')
    args = parser.parse_args()

    cpu_filter = None
    if args.cpus:
        cpu_filter = {int(c.strip()) for c in args.cpus.split(',') if c.strip()}

    ignore_cgroups = set()
    if args.ignore_cgroups:
        ignore_cgroups = {cg.strip() for cg in args.ignore_cgroups.split(',') if cg.strip()}

    ignore_procs = set()
    if args.ignore_procs:
        ignore_procs = {p.strip() for p in args.ignore_procs.split(',') if p.strip()}

    procs = get_proc_info(cpu_filter, ignore_cgroups, ignore_procs)

    if args.stats:
        print_stats(procs)
        exit(0)

    mismatches = find_cgroup_mismatches(procs, args.verbose)

    if not mismatches:
        print("No processes with intersecting CPUs and mismatched cgroups found")
    else:
        for pid1, pid2, shared in mismatches:
            p1 = procs[pid1]
            p2 = procs[pid2]
            print(f"{pid1:>6} {p1['name']:20} cgroup {p1['cgroup']}")
            print(f"{pid2:>6} {p2['name']:20} cgroup {p2['cgroup']}")
            print(f"       Shared CPUs: {fmt_cpus(shared)}\n")
