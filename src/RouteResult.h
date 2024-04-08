//
// Created by hanyuan on 2024/4/8.
//

#ifndef OPENROUTEFINDER_ROUTERESULT_H
#define OPENROUTEFINDER_ROUTERESULT_H

#include "NavaidCompare.h"
#include <iostream>

class RouteResult {
    std::vector<NavaidCompare> FullRouteNodes;
    std::vector<NavaidCompare> EncodeRouteNodes;
public:
    RouteResult() = default;

    RouteResult(NavaidCompare *RouteEnd);

    void setPrefixAndEncode(const std::string &StartPrefix, const std::string &EndPrefix);

    [[nodiscard]] std::string toString() const;

    friend std::ostream &operator<<(std::ostream &Out, const RouteResult &Result);
};


#endif //OPENROUTEFINDER_ROUTERESULT_H
