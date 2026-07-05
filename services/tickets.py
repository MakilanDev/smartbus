import os,io,qrcode
from PIL import Image
from reportlab.lib.pagesizes import A4
from reportlab.lib.colors import HexColor,white
from reportlab.pdfgen import canvas
from flask import current_app

def create_ticket(booking,details):
 path=os.path.join(current_app.config["TICKET_DIR"],f'{booking["booking_code"]}.pdf')
 qr=qrcode.make(booking["booking_code"]); q=io.BytesIO(); qr.save(q,format="PNG"); q.seek(0)
 qr_image=Image.open(q)  # reportlab's drawInlineImage needs a real PIL Image, not a raw byte buffer
 c=canvas.Canvas(path,pagesize=A4); w,h=A4
 c.setFillColor(HexColor("#11142b")); c.rect(0,0,w,h,fill=1,stroke=0); c.setFillColor(HexColor("#7c5cff")); c.roundRect(32,h-130,w-64,92,18,fill=1,stroke=0)
 c.setFillColor(white); c.setFont("Helvetica-Bold",26); c.drawString(55,h-82,"SmartBus eTicket"); c.setFont("Helvetica",11); c.drawString(55,h-105,booking["booking_code"])
 y=h-175; c.setFont("Helvetica-Bold",16); c.drawString(45,y,details.get("route","Bus Journey")); y-=35
 for label,key in [("Customer","customer"),("Date / Time","datetime"),("Bus","bus"),("Driver","driver"),("Seats","seats"),("Amount","amount"),("Payment","payment")]:
  c.setFillColor(HexColor("#9da4c7")); c.setFont("Helvetica",10); c.drawString(45,y,label.upper()); c.setFillColor(white); c.setFont("Helvetica-Bold",12); c.drawString(165,y,str(details.get(key,"—"))); y-=31
 c.drawInlineImage(qr_image,w-155,h-300,100,100); c.setFillColor(HexColor("#9da4c7")); c.setFont("Helvetica",8); c.drawString(45,55,"Arrive 20 minutes before departure. Ticket is valid with photo identification."); c.save(); return path
