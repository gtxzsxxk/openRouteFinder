//
// Created by hanyuan on 2024/4/8.
//

#include "RouteResult.h"

RouteResult::RouteResult(NavaidCompare *RouteEnd) {
    while (RouteEnd) {
        RouteNodes.push_back(*RouteEnd);
        RouteEnd = RouteEnd->ComeFrom;
    }
    std::reverse(RouteNodes.begin(), RouteNodes.end());
    setPrefix("DCT", "");
}

void RouteResult::setPrefix(const std::string &StartPrefix, const std::string &EndPrefix) {
    if (!StartPrefix.empty()) {
        (*RouteNodes.begin()).ViaEdge = StartPrefix;
    }

    if (!EndPrefix.empty()) {
        (*(RouteNodes.end() - 1)).ViaEdge = EndPrefix;
    }
}

std::string RouteResult::toString() const {
    std::string Route;
    for (const auto &WayPoint: RouteNodes) {
        Route += WayPoint.ViaEdge + " " + WayPoint.getIdentifier() + " ";
    }

    return Route;
}

std::ostream &operator<<(std::ostream &Out, const RouteResult &Result) {
    Out << Result.toString() << std::endl;
    return Out;
}
