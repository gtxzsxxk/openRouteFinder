import pickle
import RouteFinderLib
import os
import config

mode = input("Read Airports' data?(Y/N):")
cycle = input("Input Data Version:")

if mode == "Y":
    airport_data = {}
    for home, dirs, files in os.walk(config.LOCAL_ASDATA_PATH+"\\proc\\"):
        for filename in files:
            print(filename)
            fullpath = os.path.join(home, filename)
            file = open(fullpath, "r")
            airport_data[filename.replace(".txt", "")] = file.read()
            file.close()

    apfile = open(config.LOCAL_ASDATA_PATH+"\\Airports.txt", "r")
    airport_data["GLOBAL"] = apfile.readlines()
    apfile.close()

    packedFile = open("airport_"+cycle+".air", "wb")
    pickle.dump(airport_data, packedFile)
    print("数据生成完毕")
    packedFile.close()

else:
    obj = RouteFinderLib.RTFCALC()
    obj.ReadASData()
    print("nodeList占用内存大小："+str(int(obj.nodeList.__sizeof__()/1024))+" KB")
    print("数据读取完毕，开始生成序列化航路文件")
    packedFile = open("navidata_"+cycle+".map", "wb")
    pickle.dump(obj.nodeList, packedFile)
    print("数据生成完毕")
    packedFile.close()
