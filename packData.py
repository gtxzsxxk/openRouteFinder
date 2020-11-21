import pickle
import RouteFinderLib
import sys
import threading
import time
import os
import config

class ReadListen(threading.Thread):
    cnt=0
    OK=0
    def run(self):
        while True:
            if self.OK==1:
                return
            time.sleep(1)
            print("点："+str(RouteFinderLib.nodeReadCnt)+"/"+str(RouteFinderLib.datlen)+"   "+\
                str(int(RouteFinderLib.nodeReadCnt/RouteFinderLib.datlen*100))+"%"+\
                "       边："+str(RouteFinderLib.edgecnt)+"/"+str(RouteFinderLib.datlen)+"   "+\
                str(int(RouteFinderLib.edgecnt/RouteFinderLib.datlen*100))+"%")
            self.cnt=self.cnt+1
            if int(RouteFinderLib.edgecnt/RouteFinderLib.datlen*100)==100 and self.cnt>10:
                break

mode=input("Read Airports' data?(Y/N):")
if mode=="Y":
    airport_data={}
    for home, dirs, files in os.walk(config.LOCAL_ASDATA_PATH+"\\proc\\"):
        for filename in files:
            print(filename)
            fullpath = os.path.join(home, filename)
            file= open(fullpath, "r")
            airport_data[filename.replace(".txt","")]=file.read()
            file.close()
    
    apfile=open(config.LOCAL_ASDATA_PATH+"\\Airports.txt", "r")
    airport_data["GLOBAL"]=apfile.readlines()
    apfile.close()

    packedData=open(config.SET_APDAT_PATH,"wb")
    pickle.dump(airport_data,packedData)
    print("数据生成完毕")

else:
    rL=ReadListen()
    rL.start()
    RouteFinderLib.ReadASData()
    rL.OK=1
    version=input("请输入数据版本（xxxx）：")
    print("nodeList占用内存大小："+str(int(RouteFinderLib.nodeList.__sizeof__()/1024))+" KB")
    print("数据读取完毕，开始生成序列化航路文件")
    rL.OK=1
    packedFile=open("navRTE_as_"+version+".dat","wb")
    pickle.dump(RouteFinderLib.nodeList,packedFile)
    print("数据生成完毕")