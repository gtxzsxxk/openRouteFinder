# Airway-Route-Finder
#### This is a Web version working in Django Framework
--------------------------------------------
#### 在线演示：http://www.routefinder.top
#### Update comments
1. This branch is the latest branch of project Airway-Route-Finder,featuring Django's using. <br>
2. Clone this project to your server or pc,make sure apData_as_v110_2006.dat NotoSansHans-Regular.ttf and navRTE_as_v110_2006.dat exist in folder routefinder.If you don't have them,
you can make it by yourself through packData.py in another branch(you should have installed aerosoft navigraph data before),or download it at http://www.routefinder.top/alldatafile.zip<br>
3. Then modify routefinder/config.py<br>
4. You should fit it into an WSGI supporting server like nginx.<br>
---------------------------------------------
#### 简介
RouteFinderLib是由Python编写的开源航路查询库。<br>
使用dijkstra算法和aerosoft的导航数据。navRTE_as.dat是预烘焙好的航路数据文件。版本是1805。<br>
RouteFinderLib.py是库的代码。routefinder.py是库的调用demo。packData.py用来烘焙航路数据，便于快速加载图。<br>
使用RouteFinderLib，必须先让RouteFinderLib（以下简称RFL）读取数据。<br>
读取数据可以通过ReadASData()来读取。<br>
读取后的整个图维护在nodeList中，因此在packData.py中，我使用pickle库将nodeList对象序列化到二进制文件navRTE_as.dat中。<br>
所以这个方式，使读取数据快速高效。执行ReadASData函数在我的机器上需要6分钟。<br>
然而读取已经“烘焙”过的navRTE_as.dat文件，只需要几百毫秒。<br>
你可以通过packData.py，随时烘焙更新后的导航数据。<br>
		RFL中dijkstra算法的执行，只需要3步：<br>
		1、使nodeList维护整张图（读取“烘焙”的文件或者从0开始建立图）。<br>
		2、设置RFL内的起始点。<br>
		3、获取起点与中点的IID。<br>
IID是点在nodeList的下标。使用IID表示点是为了迅速的找点。<br>
在dijkstra中寻找点，如果用名称一个一个搜是非常耗时间而且不准确的（有同名冲突点，因此我引入了点的hashcode）。<br>
读出出度指向的下一个点，直接使用IID访问，提高了dijkstra执行效率。<br>
<br>
