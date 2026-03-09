"""Low-level system diagnostics MCP server.

Provides tools for CPU affinity analysis, MSR register access, and ethtool queries.
"""
from pydantic import Field
from typing import Annotated, Literal
import subprocess
import sys
import os
from fastmcp import FastMCP
from fastmcp.prompts import Message
import cpu_intersect
import list_allowed_irqs_per_cpu
import list_allowed_processes_per_cpu

import autodoc

# Initialize FastMCP server
mcp = FastMCP(
    name="lowlevel",
    instructions="""
        This server provices access to low-level information from OpenShift
        nodes, such: as CPU affinity for IRQs and processes, ethtool read-only
        queries and MSR CPU register information.
    """,
)

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
def list_irqs_for_cpu(
        cpu: Annotated[int, "CPU number (0-based)"]
    ) -> str:
    """List all IRQs that are allowed to run on specified CPU.

    Args:
        cpu: CPU number (0-based)

    Returns:
        List of IRQs and process names for the specified CPU. If no process
        name is found, it will be listed as <undefined>.
    """
    procs = list_allowed_irqs_per_cpu.get_irq_for_cpu(cpu)

    if not procs:
        return f"No IRQs found for CPU {cpu}"

    output = [f"IRQs allowed on CPU {cpu} ({len(procs)} total):"]
    for irq, name in procs:
        output.append(f"{irq:>6}  {name}")

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
    if os.getuid() != 0:
        args = ['sudo'] + args
    result = subprocess.run(args, text=True, capture_output=True, check=False)
    if result.returncode != 0:
        return f"Error: {result.stderr}\n"
    return result.stdout

@mcp.tool(annotations={
            "readOnlyHint": True,
            "destructiveHint": False
            }
)
def query_ethtool(
        interface: Annotated[str, "Network interface name (e.g., eth0)"],
        query: Annotated[Literal["show-coalesce", "show-ring", "driver", "show-offload",
                                 "statistics", "show-channels"],
                                 "Query type: must be one of show-coalesce, show-ring, driver, "
                                 "show-offload, statistics, show-channels"]
    ) -> str:
    """Query ethtool for network interface information.

    Args:
        interface: Network interface name
        query: One of: show-coalesce, show-ring, driver, show-offload, statistics, show-channels

    Returns:
        Raw ethtool command output
    """
    r = subprocess.run(['/usr/sbin/ethtool', f'--{query}', interface],
                       text=True, capture_output=True, check=False)
    if r.returncode != 0:
        return f"Error: {r.stderr}"
    return r.stdout


@mcp.prompt(
    name="check-sriov-pod-network-health",
    description="Run a complete health check of the network for an SR-IOV pod"
)
def check_sriov_pod_network_health(
    pod_name: str = Field(description="Name of the pod"),
    namespace: str = Field(description="Namespace where the pod is running"),
) -> str:
    user_msg = f"""
## Your Task

Analyze all OpenShift-related parameters that may impact SR-IOV network performance for pod {pod_name} running in namespace {namespace}. You must check the following:

1. Check the CPU usage of all reserved cores, as defined by the Performance Profile resource. You can use a Prometheus query to get it.
2. Make sure the topology policy defined in the Performance Profile resource is either "single-numa-node" or "restricted".
3. Make sure the following annotations, including their required values, are included in the pod definition:
    - cpu-load-balancing.crio.io: disable
    - cpu-quota.crio.io: disable
    - irq-load-balancing.crio.io: disable
4. Find the node CPUs assigned to the pod. To do so, use the containerID from the pod as a key to search for its cgroup in the host filesystem. Search under /host/sys/fs/cgroup, with pattern being `**/*<containerID>*/cpuset.cpus.effective`. Then:
  a) Check which processes are running on the node CPUs assigned to the pod. You can use the list_processes_for_cpu tool to get the information. If there is any kernel process running on those CPUs, ensure it is a per-cpu kernel thread and not any other type of process.
  b) Check the IRQs allowed to run on the node CPUs assigned to the pod. You can use the list_irqs_for_cpu tool to get the information. No IRQ related to a network driver should be allowed to run on those CPUs.
5. Find the physical NICs used by the SR-IOV VFs associated to the pod. You can use the SriovNetworkNodeState OpenShift resource to get the VF to PF mapping. Then, check the MTU for all physical NICs used by the SR-IOV VFs associated to the pod. They must be 1500 or higher.
6. Check the combined channels for the physical NICs used by the SR-IOV VFs associated to the pod. You can use the query_ethtool tool to get that information. The number of combined channels must be at least 16 for each NIC.
7. Make sure the the pod's CPU utilization is above 90%.
8. Make sure the pod containers are not being throttled by the CFS.
9. Make sure the QoS class for the pod is Guaranteed.
10. Check the statistics for all physical NICs used by the SR-IOV VFs associated to the pod. You can use the query_ethtool tool to get that information. There should be a good balance in the values of tx_queue_*_packets and rx_queue_*_packets for each of the tx and rx queues.
11. Check the MTU for all SR-IOV VFs associated to the pod. They must be 1500 or higher.
12. Make sure there are no errors or packet drops shown for any physical NICs used by the SR-IOV VFs associated to the pod. You can use a Prometheus query to get the information.
13. Check for any drops or errors at the TCP and UDP layers on the node running the pod. Use a Prometheus query to get the information.
14. Check the kernel settings under /proc/sys/net are correct. You can use the read_text_file_openshift_host tool from the openshift-filesystem-mcp MCP server for that. Specifically, the highest value from each file should be at least:
    - /host/proc/sys/net/ipv4/tcp_rmem: 4194304
    - /host/proc/sys/net/ipv4/tcp_wmem: 4194304
15. Check for softnet packet-drop errors or high time_squeeze values at /host/proc/net/softnet_stat, which can indicate network contention on the node running the pod. You can use the read_text_file_openshift_host tool from the openshift-filesystem-mcp MCP server for that.
16. Check for a high number of SMI interrupts received by the node's CPU, by reading the MSR register. Use the read_msr_register tool for that.

Do not try to run any local commands. Always use the tools at your disposal from the available MCP servers.

Once the checks have been completed, prepare a comprehensive report of the results, highlighting any error that must be immediately acted upon, as well as any warning that may be checked.
    """
    assistant_msg = "I will check the pod network health for you."

    return [
        Message(user_msg),
        Message(assistant_msg, role="assistant"),
    ]


if __name__ == "__main__":
    if len(sys.argv) > 1:
        if sys.argv[1] == '--help':
            autodoc.show_autodoc(sys.modules[__name__])
        else:
            a1 = sys.argv[1]
            sys.argv = sys.argv[1:]
            if '(' in a1:
                ret = eval(a1)
            else:
                ret = eval(a1 + '(' + ', '.join("'%s'" % (a) for a in sys.argv[1:]) + ')')
            print(ret)
    else:
        mcp.run(transport="http", host="0.0.0.0", port=9028)
