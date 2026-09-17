from sqlalchemy import Column, Integer, String, Boolean, Text
from app.database import Base


class Product(Base):
    __tablename__ = "products"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(200), nullable=False)
    # Категории — строка через запятую: "Очищение,Уход"
    category = Column(String(300), nullable=True)
    brand = Column(String(100), nullable=True)
    price = Column(Integer, nullable=False)
    popular = Column(Boolean, default=False)
    description = Column(Text, nullable=True)
    volume = Column(String(50), nullable=True)
    image = Column(String(200), nullable=True)
    # LEGACY: оставлено только для миграции старых тегов в категории
    tags = Column(String(200), nullable=True)


class Brand(Base):
    __tablename__ = "brands"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), unique=True, nullable=False, index=True)


class Category(Base):
    __tablename__ = "categories"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), unique=True, nullable=False, index=True)