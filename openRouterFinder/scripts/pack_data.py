"""Navigation data preprocessing script."""

import os
import pickle
import sys

# Add project root to path
sys.path.insert(0, str(os.path.dirname(os.path.dirname(os.path.dirname(__file__)))))

from openRouterFinder.config import settings
from openRouterFinder.core.graph import Node, Edge


def pack_airport_data(cycle: str):
    """Pack airport data into .air file."""
    airport_data = {}
    proc_path = os.path.join(settings.local_asdata_path, "proc")
    for home, dirs, files in os.walk(proc_path):
        for filename in files:
            print(filename)
            fullpath = os.path.join(home, filename)
            with open(fullpath, "r") as f:
                airport_data[filename.replace(".txt", "")] = f.read()

    apfile_path = os.path.join(settings.local_asdata_path, "Airports.txt")
    with open(apfile_path, "r") as f:
        airport_data["GLOBAL"] = f.readlines()

    output = settings.navdat_full_path.parent / f"airport_{cycle}.air"
    with open(output, "wb") as f:
        pickle.dump(airport_data, f)
    print(f"Airport data packed to {output}")


def pack_nav_data(cycle: str):
    """Pack navigation route data into .map file."""
    node_list = _build_node_list_from_asdata()

    output = settings.navdat_full_path.parent / f"navidata_{cycle}.map"
    with open(output, "wb") as f:
        pickle.dump(node_list, f)
    print(f"Nav data packed to {output}")
    print(f"nodeList memory: {int(node_list.__sizeof__() / 1024)} KB")


def _build_node_list_from_asdata():
    """Build node list from Aerosoft raw ATS data."""
    node_list = []
    node_index = {}  # (name, lat_rounded, lon_rounded) -> Node

    ats_path = os.path.join(settings.local_asdata_path, "ATS.txt")
    with open(ats_path, "r") as f:
        lines = f.readlines()

    print("Reading nodes...")
    for line in lines:
        parts = line.strip().split(",")
        if parts[0] != "S":
            continue
        n1 = Node(iid=len(node_list), name=parts[1], px=float(parts[2]), py=float(parts[3]))
        n2 = Node(iid=len(node_list) + 1, name=parts[4], px=float(parts[5]), py=float(parts[6]))

        k1 = (n1.name, round(n1.px, 6), round(n1.py, 6))
        k2 = (n2.name, round(n2.px, 6), round(n2.py, 6))

        if k1 not in node_index:
            node_index[k1] = n1
            node_list.append(n1)
        if k2 not in node_index:
            node_index[k2] = n2
            node_list.append(n2)

    print(f"Total nodes: {len(node_list)}")

    print("Reading edges...")
    edge_name = ""
    for line in lines:
        parts = line.strip().split(",")
        if parts[0] == "A":
            edge_name = parts[1]
        elif parts[0] == "S":
            k1 = (parts[1], round(float(parts[2]), 6), round(float(parts[3]), 6))
            k2 = (parts[4], round(float(parts[5]), 6), round(float(parts[6]), 6))
            n1 = node_index[k1]
            n2 = node_index[k2]
            n1.next_list.append(Edge(nfrom=n1.iid, nend=n2.iid, name=edge_name))

    return node_list


def main():
    mode = input("Read Airports' data? (y/n strictly): ")
    cycle = input("Input Data Version (such as 2206): ")

    if mode == "y":
        pack_airport_data(cycle)
    else:
        pack_nav_data(cycle)

    print("Done.")


if __name__ == "__main__":
    main()
