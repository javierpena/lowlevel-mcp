from typing import Annotated, Any
import subprocess
from fastmcp import FastMCP
import cpu_intersect
import list_allowed_processes_per_cpu

# Initialize FastMCP server
mcp = FastMCP("lowlevel")

@mcp.tool()
def find_cpu_intersections(
    cpus: str = "",
    ignore_cgroups: str = "",
    ignore_procs: str = "",
) -> str:
    """Find processes with intersecting CPU affinity from different cgroups.

    Args:
        cpus: Filter by CPU list (e.g., "0,1,2")
        ignore_cgroups: Ignore cgroups (comma-separated)
        ignore_procs: Ignore process names (comma-separated)

    Returns:
        Report of cgroup pairs with overlapping CPU sets
    """
    cpu_filter = None
    if cpus:
        cpu_filter = {int(c.strip()) for c in cpus.split(',') if c.strip()}

    ignore_cg = {cg.strip() for cg in ignore_cgroups.split(',') if cg.strip()} if ignore_cgroups else set()
    ignore_pr = {p.strip() for p in ignore_procs.split(',') if p.strip()} if ignore_procs else set()

    procs = cpu_intersect.get_proc_info(cpu_filter, ignore_cg, ignore_pr)
    mismatches = cpu_intersect.find_cgroup_mismatches(procs)

    output = []
    if not mismatches:
        output.append("No processes with intersecting CPUs and mismatched cgroups found")
    else:
        for pid1, pid2, shared in mismatches:
            p1 = procs[pid1]
            p2 = procs[pid2]
            output.append(f"{pid1:>6} {p1['name']:20} cgroup {p1['cgroup']}")
            output.append(f"{pid2:>6} {p2['name']:20} cgroup {p2['cgroup']}")
            output.append(f"       Shared CPUs: {cpu_intersect.fmt_cpus(shared)}\n")

    return "\n".join(output)

@mcp.tool(annotations={
            "readOnlyHint": True,
            "destructiveHint": False
            }
)
def list_processes_for_cpu(
        cpu: Annotated[int, "CPU number (0-based)"]
    ) -> str:
    """List all processes allowed to run on specified CPU.

    Args:
        cpu: CPU number (0-based)

    Returns:
        List of PIDs and process names for the specified CPU
    """
    procs = list_allowed_processes_per_cpu.get_processes_for_cpu(cpu)

    if not procs:
        return f"No processes found for CPU {cpu}"

    output = [f"Processes allowed on CPU {cpu} ({len(procs)} total):"]
    for pid, name in procs:
        output.append(f"{pid:>6}  {name}")

    return "\n".join(output)

@mcp.tool(annotations={
            "readOnlyHint": True,
            "destructiveHint": False
            }
)
def read_msr_register(
        register: Annotated[str, "Hexadecimal number for the register to be read"],
        cpu: Annotated[int, "If specified, read the register from this CPU. Defaults to 0"] = 0
    ) -> str:
    """Read an MSR register from the specified CPU.

    Returns:
        The MSR register value, in hexadecimal.
    """
    args = ["/usr/sbin/rdmsr", "-x", "-p", str(cpu), register]
    result = subprocess.run(args, text=True, capture_output=True, check=False)
    if result.returncode != 0:
        return f"Error: {result.stderr}\n"
    return result.stdout


def run():
    mcp.run(transport="http", host="0.0.0.0", port=9028)


if __name__ == "__main__":
    run()
