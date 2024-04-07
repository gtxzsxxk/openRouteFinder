//
// Created by hanyuan on 2024/4/6.
//

#include "NavDataReader.h"
#include <iostream>
#include <chrono>

std::string NavDataReader::getFileFullPath(const std::string &RelaPath) {
    return DataPath + RelaPath;
}

NavDataReader::NavDataReader(std::string DataPath) : DataPath(std::move(DataPath)) {
    /* Read Cycle Information */
    std::ifstream input(getFileFullPath(DATA_PATH_CYCLE_INFO), std::ios_base::in);
    if (!input.is_open()) {
        std::cerr << "Failed to open cycle file." << std::endl;
        return;
    }

    std::string buffer;
    std::getline(input, buffer);
    DataProvider = getStringFromRegex(buffer, "^([A-Za-z]*) cycle\\s*:\\s*[0-9]*$");
    DataCycle = getStringFromRegex(buffer, "^AIRAC cycle\\s*:\\s*([0-9]*)$");
    std::getline(input, buffer);
    DataRevision = getStringFromRegex(buffer, "^.*:\\s*(.*)$");
    std::getline(input, buffer);
    DataValidRange = getStringFromRegex(buffer, "^Valid\\s*\\(from/to\\)\\s*:\\s*(.*)$");
    printCycleInformation();
}

void NavDataReader::printCycleInformation() {
    std::cout << "NavData Path: \t" << DataPath << std::endl;
    std::cout << "NavData Type: \t" << DataProvider << std::endl;
    std::cout << "NavData Cycle: \t" << DataCycle << std::endl;
    std::cout << "NavData Revision: \t" << DataRevision << std::endl;
    std::cout << "NavData Valid Range: \t" << DataValidRange << std::endl;
}

std::string NavDataReader::getStringFromRegex(const std::string &Source, const std::string &RegexStr) {
    auto reg = std::regex(RegexStr);
    std::smatch match;
    if (std::regex_search(Source, match, reg) && match.size() >= 2) {
        return match[1];
    }
    return {};
}

void NavDataReader::readAllNavaids() {
    std::ifstream input(getFileFullPath(DATA_PATH_NAVAIDS), std::ios_base::in);
    if (!input.is_open()) {
        std::cerr << "Failed to open navaid file." << std::endl;
        return;
    }
    Navaids.clear();
    while (!input.eof()) {
        std::string buffer;
        std::getline(input, buffer);
        double dr_us;
        auto t1 = std::chrono::steady_clock::now();
        auto t2 = std::chrono::steady_clock::now();
        int failed = 0;
        auto node = NavaidInformation(buffer, failed);
        if (!failed) {
            Navaids.insert(std::move(node));
        }

        dr_us = std::chrono::duration<double, std::micro>(t2 - t1).count();
    }
}
void NavDataReader::cacheFixes() {
    std::ifstream input(getFileFullPath(DATA_PATH_FIXES), std::ios_base::in);
    if (!input.is_open()) {
        std::cerr << "Failed to open fixes file." << std::endl;
        return;
    }
    std::cout << "Caching Fixes ..." <<std::endl;
    while (!input.eof()) {
        std::string buffer;
        std::getline(input, buffer);
        double dr_us;
        auto t1 = std::chrono::steady_clock::now();
        auto t2 = std::chrono::steady_clock::now();
        int failed = 0;
        auto node = NavaidInformation(buffer, failed, true);
        if (!failed) {
            FixesCache.insert(std::move(node));
        }

        dr_us = std::chrono::duration<double, std::micro>(t2 - t1).count();
    }
}
