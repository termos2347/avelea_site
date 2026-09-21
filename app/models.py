from sqlalchemy import Column, Integer, String, Boolean, Text, Table, ForeignKey
from sqlalchemy.orm import relationship
from app.database import Base


# Таблица-связка many-to-many: товар ↔ категория
product_categories = Table(
    "product_categories",
    Base.metadata,
    Column("product_id", Integer, ForeignKey("products.id"), primary_key=True),
    Column("category_id", Integer, ForeignKey("categories.id"), primary_key=True),
)


class Product(Base):
    __tablename__ = "products"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(200), nullable=False)
    brand = Column(String(100), nullable=True)
    price = Column(Integer, nullable=False)
    popular = Column(Boolean, default=False)
    description = Column(Text, nullable=True)
    volume = Column(String(50), nullable=True)
    image = Column(String(200), nullable=True)

    # lazy="selectin" — подгружает категории одним запросом, без N+1
    categories = relationship(
        "Category",
        secondary=product_categories,
        backref="products",
        lazy="selectin",
    )


class Brand(Base):
    __tablename__ = "brands"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), unique=True, nullable=False, index=True)


class Category(Base):
    __tablename__ = "categories"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), unique=True, nullable=False, index=True)