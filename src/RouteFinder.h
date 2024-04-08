//
// Created by hanyuan on 2024/4/7.
//

#ifndef OPENROUTEFINDER_ROUTEFINDER_H
#define OPENROUTEFINDER_ROUTEFINDER_H

#include "NavaidInformation.h"
#include "NavaidCompare.h"
#include "NavDataReader.h"
#include "RouteResult.h"
#include <iostream>
#include <map>
#include <string>
#include <vector>
#include <algorithm>

class RouteFinder {
    const std::map<std::string, NavaidInformation> &Nodes;
    const NavDataReader &DataReader;

public:

    RouteFinder() = delete;

    explicit RouteFinder(const NavDataReader &Reader) : Nodes(Reader.getNavaids()), DataReader(Reader) {};

    RouteResult calculateShortestRoute(const NavaidInformation &Start,
                                       const NavaidInformation &End,
                                       AIRWAY_TYPE AirwayType = AIRWAY_HIGH);
};


#endif //OPENROUTEFINDER_ROUTEFINDER_H
