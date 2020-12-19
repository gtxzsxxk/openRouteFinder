from django.db import models
import requests

# Create your models here.

class PVlog(models.Model):
    usrIP=models.TextField(max_length=36,unique=True)
    TIME=models.DateTimeField(auto_now=True)
    Place=models.TextField(max_length=16)
    Route=models.TextField(max_length=512)
    TotalPV=models.IntegerField(default=0)

    def IPGET(self,ip):
        url = "http://whois.pconline.com.cn/ip.jsp?ip="+ip
        r=requests.get(url)
        return r.text

    def __str__(self):
        totalroutes=0
        for j in self.Route.split('\r\n'):
                if j.__len__()>4:
                    totalroutes=totalroutes+1;
        return "用户IP："+self.usrIP+" 位于："+self.Place+"\t访问次数："+str(self.TotalPV)\
            +"\t查询航路："+str(totalroutes)
