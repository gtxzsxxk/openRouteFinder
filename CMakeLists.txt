cmake_minimum_required(VERSION 3.22)
project(openRouteFinder)

set(CMAKE_CXX_STANDARD 20)

set(CMAKE_CXX_FLAGS "${CMAKE_CXX_FLAGS} -Wall -Werror")

add_executable(openRouteFinder src/main.cpp
        src/NavDataReader.cpp
        src/NavDataReader.h
        src/NavaidInformation.cpp
        src/NavaidInformation.h
        src/RouteFinder.cpp
        src/RouteFinder.h
        src/NavaidCompare.cpp
        src/NavaidCompare.h
        src/RouteResult.cpp
        src/RouteResult.h
        src/AirportProcedure.cpp
        src/AirportProcedure.h)
