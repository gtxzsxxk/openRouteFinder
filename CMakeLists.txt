cmake_minimum_required(VERSION 3.22)
project(openRouteFinder)

set(CMAKE_CXX_STANDARD 20)

add_executable(openRouteFinder src/main.cpp
        src/NavDataReader.cpp
        src/NavDataReader.h
        src/NavaidInformation.cpp
        src/NavaidInformation.h
        src/RouteFinder.cpp
        src/RouteFinder.h)
