//
// Created by hanyuan on 2024/4/8.
//

#ifndef OPENROUTEFINDER_NAVAIDCOMPARE_H
#define OPENROUTEFINDER_NAVAIDCOMPARE_H

#include "NavaidInformation.h"
#include <map>

class NavaidCompare : public NavaidInformation {
public:
    int ID;
    double DistanceToStart;
    bool ShortestDiscovered;
    NavaidCompare *ComeFrom = nullptr;
    std::string ViaEdge = "DCT";

    /* Debug Only */
    std::string Path;

    NavaidCompare() = default;

    explicit NavaidCompare(const NavaidInformation &NavInfo);

    bool operator<(const NavaidCompare &NavCmp) const;

    bool operator()(NavaidCompare *&lhs, NavaidCompare *&rhs);

    static NavaidCompare *getNavaidCompareFromMap(std::map<std::string, NavaidCompare> &Map, const std::string &Key);
};


#endif //OPENROUTEFINDER_NAVAIDCOMPARE_H
