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
    while (true) {
        std::string departure, arrival;

        std::cout << "Departure ICAO: ";
        std::cin >> departure;

        std::cout << "Arrival ICAO: ";
        std::cin >> arrival;

        t1 = std::chrono::steady_clock::now();
        auto results = routeFinder.calculateBetweenAirports(departure, arrival);
        t2 = std::chrono::steady_clock::now();
        std::cout << "Results: " << results;
        dr_us = std::chrono::duration<double, std::milli>(t2 - t1).count();
        std::cout << std::endl << "Time: " << dr_us << " (ms)" << std::endl;
    }
    return 0;
}
