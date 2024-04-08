#include "NavDataReader.h"
#include "RouteFinder.h"
#include <iostream>
#include <chrono>

int main() {
    auto reader = NavDataReader("../tests/navdata/");
    auto t1 = std::chrono::steady_clock::now();
    reader.readNavaids();
    auto t2 = std::chrono::steady_clock::now();
    auto dr_us = std::chrono::duration<double, std::micro>(t2 - t1).count();

    t1 = std::chrono::steady_clock::now();
    reader.cacheFixes();
    t2 = std::chrono::steady_clock::now();
    dr_us = std::chrono::duration<double, std::micro>(t2 - t1).count();

    t1 = std::chrono::steady_clock::now();
    reader.readAirways();
    t2 = std::chrono::steady_clock::now();
    dr_us = std::chrono::duration<double, std::micro>(t2 - t1).count();

    auto routeFinder = RouteFinder(reader);
    t1 = std::chrono::steady_clock::now();
    auto results = routeFinder.calculateShortestRoute(NavaidInformation("VIBOS","ZG"), NavaidInformation("WL","ZJ"));
    std::cout<< "Results: " << results;
    t2 = std::chrono::steady_clock::now();
    dr_us = std::chrono::duration<double, std::micro>(t2 - t1).count();
    return 0;
}
