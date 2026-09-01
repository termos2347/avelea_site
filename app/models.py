from sqlalchemy import Column, Integer, String, Float, Boolean, Text
from app.database import Base

class Product(Base):
    __tablename__ = "products"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(200), nullable=False)
    category = Column(String(100), nullable=False)
    brand = Column(String(100), nullable=True)
    price = Column(Integer, nullable=False)
    popular = Column(Boolean, default=False)
    description = Column(Text, nullable=True)
    volume = Column(String(50), nullable=True)
    image = Column(String(200), nullable=True)
    tags = Column(String(200), nullable=True)