"""Pickle backward-compatibility module.

Pickled nav data files reference RouteFinderLib.Node and RouteFinderLib.Edge.
This module provides compatible class definitions so old pickle files deserialize
correctly. The module is registered as ``sys.modules['RouteFinderLib']`` by
:data_loader: before loading pickle data.
"""


class Edge:
    """Original Edge class for pickle compatibility."""

    def __init__(self, nodefrom, node_end, name, r, g, b):
        self.nfrom = nodefrom.iid
        self.nend = node_end.iid
        self.name = name
        self.color = (r, g, b)


class Node:
    """Original Node class for pickle compatibility."""

    def __init__(self, name, x, y, objself):
        self.iid = objself.nodeList.__len__()
        self.name = name
        self.px = x
        self.py = y
        self.nextList = []
        self.nextList.clear()

    def gethash(self):
        return int(abs(int(self.px) * int(self.py)))


def CalcNodeHash(x, y):
    return int(abs(int(x) * int(y)))
