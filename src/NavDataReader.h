//
// Created by hanyuan on 2024/4/6.
//

#ifndef OPENROUTEFINDER_NAVDATAREADER_H
#define OPENROUTEFINDER_NAVDATAREADER_H

#include "AirportProcedure.h"
#include "NavaidInformation.h"

#include <iostream>
#include <string>
#include <cstdio>
#include <fstream>
#include <regex>
#include <map>

class AirportProcedure;

class NavDataReader {
    const std::string DataPath;
    static constexpr char DATA_PATH_CYCLE_INFO[] = "cycle_info.txt";
    static constexpr char DATA_PATH_AIRWAY[] = "earth_awy.dat";
    static constexpr char DATA_PATH_NAVAIDS[] = "earth_nav.dat";
    static constexpr char DATA_PATH_FIXES[] = "earth_fix.dat";
    std::string DataProvider;
    std::string DataCycle;
    std::string DataRevision;
    std::string DataValidRange;

    std::string getFileFullPath(const std::string &RelaPath) const;

    void printCycleInformation();

    static std::string getStringFromRegex(const std::string &Source, const std::string &RegexStr);

    mutable std::map<std::string, NavaidInformation> Navaids;
    mutable std::map<std::string, NavaidInformation> FixesCache;

public:
    NavDataReader(std::string DataPath);

    void readNavaids();

    void cacheFixes();

    void readAirways();

    std::vector<AirportProcedure> readAirportProcedure(const std::string &ICAO) const;

    const NavaidInformation *getNodeFromNavaids(const std::string &Identifier, const std::string &RegionCode) const;

    const NavaidInformation *getNodeFromNavaids(const NavaidInformation &Node) const;

    [[nodiscard]] const std::map<std::string, NavaidInformation> &getNavaids() const;

    const NavaidInformation *
    getNodeFromNavaidsOrFixesCache(const std::string &Identifier, const std::string &RegionCode, int NavType) const;

    friend AirportProcedure;
};


#endif //OPENROUTEFINDER_NAVDATAREADER_H
