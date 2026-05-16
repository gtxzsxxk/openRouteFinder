"""Backward-compatibility stub for pickle deserialization.

Pickled node lists reference RouteFinderLib.Node and RouteFinderLib.Edge.
This module preserves the original class structure so old pickle files load correctly.
"""


class Edge:
    nfrom = 0
    nend = 0
    dist = 0
    name = ""
    toinstantnode = None
    color = (0, 0, 0)

    def __init__(self, nodefrom, node_end, name, r, g, b):
        self.nfrom = nodefrom.iid
        self.nend = node_end.iid
        self.name = name
        self.color = (r, g, b)


class Node:
    iid = 0
    name = ""
    px = 0.0
    py = 0.0
    nextList = None

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
