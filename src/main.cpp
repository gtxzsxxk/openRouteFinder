#include "NavDataReader.h"
#include <iostream>
#include <chrono>

int main() {
    auto reader = NavDataReader("../tests/navdata/");
    auto t1=std::chrono::steady_clock::now();
    reader.readNavaids();
    auto t2=std::chrono::steady_clock::now();
    auto dr_us=std::chrono::duration<double,std::micro>(t2-t1).count();
    return 0;
}
