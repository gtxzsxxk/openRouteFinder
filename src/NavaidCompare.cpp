//
// Created by hanyuan on 2024/4/8.
//

#include "NavaidCompare.h"

NavaidCompare::NavaidCompare(const NavaidInformation &NavInfo) : NavaidInformation(NavInfo) {
    DistanceToStart = 0xffffffff;
    ShortestDiscovered = false;
}

bool NavaidCompare::operator<(const NavaidCompare &NavCmp) const {
    return DistanceToStart > NavCmp.DistanceToStart;
}

bool NavaidCompare::operator()(NavaidCompare *&lhs, NavaidCompare *&rhs) {
    return lhs->DistanceToStart > rhs->DistanceToStart;
}

NavaidCompare *
NavaidCompare::getNavaidCompareFromMap(std::map<std::string, NavaidCompare> &Map, const std::string &Key) {
    if (Map.count(Key)) {
        return &Map[Key];
    }
    return nullptr;
}
