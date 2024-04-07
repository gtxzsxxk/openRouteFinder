#include "NavDataReader.h"
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

    auto r1 = reader.getNodeFromNavaids("DAPRO", "ZH");

    return 0;
}
