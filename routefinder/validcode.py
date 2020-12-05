from PIL import Image
from PIL import ImageFont
from PIL import ImageDraw
from PIL import ImageFilter
import random
import io
 
def getRandomColor():
    c1 = random.randint(0,255)
    c2 = random.randint(0,255)
    c3 = random.randint(0,255)
    return (c1,c2,c3)
 
def getImageBytes(num,fontpath):
    image = Image.new('RGB',(90,30),getRandomColor())
    draw = ImageDraw.Draw(image)
    font=ImageFont.truetype(fontpath,size=26)
    draw.text((20,0),str(num),getRandomColor(),font=font)
    imgByteArr = io.BytesIO()
    image.save(imgByteArr, format='JPEG')
    imgByteArr = imgByteArr.getvalue()
    return imgByteArr
