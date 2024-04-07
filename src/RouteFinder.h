//
// Created by hanyuan on 2024/4/7.
//

#ifndef OPENROUTEFINDER_ROUTEFINDER_H
#define OPENROUTEFINDER_ROUTEFINDER_H
#include "NavaidInformation.h"
#include "NavDataReader.h"
#include <map>
#include <string>
#include <vector>

class RouteFinder {
    const std::map<std::string, NavaidInformation> &Nodes;
    const NavDataReader &DataReader;
    RouteFinder() = default;
public:
    RouteFinder(const NavDataReader &Reader) : Nodes(Reader.getNavaids()), DataReader(Reader) {};

    std::vector<NavaidInformation> calculateShortestRoute(const NavaidInformation & Start, const NavaidInformation & End);
};


#endif //OPENROUTEFINDER_ROUTEFINDER_H
