from django.shortcuts import render
from django.http import HttpResponse
import airwayroutefinder.settings
import os
import routefinder.config
import routefinder.validcode
import random
import RouteFinderLib
import pickle
from .models import PVlog

navRTE=open(routefinder.config.SET_NAVDAT_PATH,"rb")
PerloadNodeList=pickle.load(navRTE)
navRTE.close()

apDat=open(routefinder.config.SET_APDAT_PATH,"rb")
RouteFinderLib.airport_maps=pickle.load(apDat)
apDat.close()

# Create your views here.

def favico(request):
    file=open(os.path.join(airwayroutefinder.settings.BASE_DIR,"template/favicon.ico"),"rb")
    bytedata=file.read()
    file.close()
    return HttpResponse(bytedata,content_type='image/jpg')

def get_client_ip(request):
    x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
    if x_forwarded_for:
        ip = x_forwarded_for.split(',')[-1].strip()     
    else:         
        ip = request.META.get('REMOTE_ADDR')
    return ip

def index(request):
    context={}
    context["YourBingMapsKey"]=routefinder.config.YourBingMapsKey
    ip=get_client_ip(request)
    print(ip)
    records=PVlog.objects.all()
    haveIP=False
    totalroutes=0
    for i in records:
        if i.usrIP==ip:
            haveIP=True
            i.TotalPV=i.TotalPV+1
            i.save()
        for j in i.Route.split('\r\n'):
                if j.__len__()>4:
                    totalroutes=totalroutes+1;
    if haveIP==False:
        s=PVlog(usrIP=ip,Place="unknown",Route="",TotalPV=1)
        s.Place=s.IPGET(s.usrIP)
        s.save()
    context["pagevisit"]=records.__len__()
    context["routecalc"]=totalroutes
    return render(request,"index.html",context)

def getImage(request):
    validnum=random.randint(1111,9999)
    imageBytes=routefinder.validcode.getImageBytes(validnum,\
        os.path.join(airwayroutefinder.settings.BASE_DIR,"routefinder/NotoSansHans-Regular.ttf"))
    request.session['reqInstance']=str(validnum)
    return HttpResponse(imageBytes,content_type="image/jpg")

def getCycle(request):
    return HttpResponse(routefinder.config.NAVDAT_CYCLE)

def getRoute(request,orig,dest,valid):
    if valid!=request.session.get('reqInstance',None):
        return HttpResponse("Auth errs.")
    def SearchRoute(orig,dest):
        if RouteFinderLib.airport_maps.__contains__(orig)==False or RouteFinderLib.airport_maps.__contains__(dest)==False:
            return "查找的机场在本版本数据中不存在。"
        objsearch=RouteFinderLib.RTFCALC()
        objsearch.nodeList=PerloadNodeList
        objsearch.startNode=objsearch.ReadSIDAirport(orig)
        objsearch.endNode=objsearch.ReadSTARAirport(dest)
        ans=objsearch.Dijkstra(objsearch.startNode.iid,objsearch.endNode.iid)
        if objsearch.startNode==None or objsearch.endNode==None:
            return "算法发现Dijkstra丢失起点或终点，无法计算航路。"
        del objsearch
        return ans
    response=SearchRoute(orig,dest)
    route=response.split('||||')[0].split('\r\n')[0]
    ip=get_client_ip(request)
    records=PVlog.objects.all()
    for i in records:
        if i.usrIP==ip:
            i.Route=i.Route+"\r\n"+route.replace("\r\n","")
            print("添加航路至数据库"+route)
            i.save()
    return HttpResponse(response)

    
