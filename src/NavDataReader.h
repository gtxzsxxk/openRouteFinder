//
// Created by hanyuan on 2024/4/6.
//

#ifndef OPENROUTEFINDER_NAVDATAREADER_H
#define OPENROUTEFINDER_NAVDATAREADER_H

#include "NavaidInformation.h"

#include <iostream>
#include <string>
#include <cstdio>
#include <fstream>
#include <regex>
#include <set>

class NavDataReader {
    const std::string DataPath;
    static constexpr std::string DATA_PATH_CYCLE_INFO = "cycle_info.txt";
    static constexpr std::string DATA_PATH_AIRWAY = "earth_awy.dat";
    static constexpr std::string DATA_PATH_NAVAIDS = "earth_nav.dat";
    static constexpr std::string DATA_PATH_FIXES = "earth_fix.dat";
    std::string DataProvider;
    std::string DataCycle;
    std::string DataRevision;
    std::string DataValidRange;

    std::string getFileFullPath(const std::string &RelaPath);
    void printCycleInformation();
    static std::string getStringFromRegex(const std::string& Source, const std::string& RegexStr);

    std::set<NavaidInformation> Navaids;
    std::set<NavaidInformation> FixesCache;

public:
    NavDataReader(std::string DataPath);

    void readNavaids();
    void cacheFixes();
    void readAirways();
};


#endif //OPENROUTEFINDER_NAVDATAREADER_H
