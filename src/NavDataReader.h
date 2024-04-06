//
// Created by hanyuan on 2024/4/6.
//

#ifndef OPENROUTEFINDER_NAVDATAREADER_H
#define OPENROUTEFINDER_NAVDATAREADER_H

#include <iostream>
#include <string>
#include <cstdio>
#include <fstream>
#include <regex>

class NavDataReader {
    const std::string DataPath;
    static constexpr std::string DATA_PATH_CYCLE_INFO = "cycle_info.txt";
    static constexpr std::string DATA_PATH_AIRWAY = "earth_awy.dat";
    std::string DataProvider;
    std::string DataCycle;
    std::string DataRevision;
    std::string DataValidRange;

    std::string getFileFullPath(const std::string &RelaPath);
    void printCycleInformation();
    static std::string getStringFromRegex(const std::string& Source, const std::string& RegexStr);

public:
    NavDataReader(std::string DataPath) : DataPath(std::move(DataPath)) {
        /* Read Cycle Information */
        std::ifstream input(getFileFullPath(DATA_PATH_CYCLE_INFO),std::ios_base::in);
        if(!input.is_open()) {
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
};


#endif //OPENROUTEFINDER_NAVDATAREADER_H
