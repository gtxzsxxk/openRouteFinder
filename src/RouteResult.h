//
// Created by hanyuan on 2024/4/8.
//

#ifndef OPENROUTEFINDER_ROUTERESULT_H
#define OPENROUTEFINDER_ROUTERESULT_H

#include "NavaidCompare.h"
#include <iostream>

class RouteResult {
    std::vector<NavaidCompare> RouteNodes;
public:
    RouteResult(NavaidCompare *RouteEnd);

    void setPrefix(const std::string &StartPrefix, const std::string &EndPrefix);

    [[nodiscard]] std::string toString() const;

    friend std::ostream &operator<<(std::ostream &Out, const RouteResult &Result);
};


#endif //OPENROUTEFINDER_ROUTERESULT_H
