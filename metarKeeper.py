import config
import time
import threading
import requests

class metarKeeper(threading.Thread):
    metarData=""
    def run(self):
        while True:
            metarFile=open('metar.txt','w')
            gmt_hr=time.gmtime().tm_hour
            print("===="+time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())+"正在更新METAR====")
            r=requests.get(f'https://tgftp.nws.noaa.gov/data/observations/metar/cycles/{gmt_hr}Z.TXT',
                headers={"User-Agent":"Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4464.0 Safari/537.36 Edg/91.0.852.0"})
            metarFile.write(r.text)
            self.metarData=r.text
            print(f"读取{gmt_hr}Z.TXT了{r.text.__len__()}字节")
            print("============================")
            metarFile.close()
            time.sleep(config.METAR_UPDATE_MINUTE*60)

    def readMetar(self,ICAO):
        if self.metarData.__len__()>1000:
            start_index=self.metarData.find(ICAO)
            result=""
            for i in range(0,100):
                if self.metarData[start_index+i]=='\n':
                    break
                result+=self.metarData[start_index+i]
            return result
            
        return f"{ICAO} METAR NOT AVAILABLE"
