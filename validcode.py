from PIL import Image
from PIL import ImageFont
from PIL import ImageDraw
from PIL import ImageFilter
import random
import io
import base64


def getRandomColor():
    c1 = random.randint(0, 255)
    c2 = random.randint(0, 255)
    c3 = random.randint(0, 255)
    return (c1, c2, c3)


def getImageBytes(num):
    image = Image.new("RGB", (90, 30), getRandomColor())
    draw = ImageDraw.Draw(image)
    font = ImageFont.truetype("static/NotoSansHans-Regular.ttf", size=26)
    draw.text((20, 0), str(num), getRandomColor(), font=font)
    imgByteArr = io.BytesIO()
    image.save(imgByteArr, format="JPEG")
    imgByteArr = imgByteArr.getvalue()
    return imgByteArr


def RotateImage(angle):
    img = Image.open("static/runway.png")
    size_s = img.size
    img = img.rotate(360 - angle)
    img = img.resize((32, 32))
    bIO = io.BytesIO()
    img.save(bIO, format="PNG")
    img_bytes = bIO.getvalue()
    b64_data = base64.b64encode(img_bytes).decode(encoding="utf-8")
    return "data:image/png;base64," + b64_data
