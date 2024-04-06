//
// Created by hanyuan on 2024/4/6.
//

#include "NavDataReader.h"
#include <iostream>

std::string NavDataReader::getFileFullPath(const std::string &RelaPath) {
    return DataPath + RelaPath;
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
