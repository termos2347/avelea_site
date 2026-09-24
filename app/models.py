from sqlalchemy import (
    Column, Integer, String, Boolean, Text, Table, ForeignKey, event,
)
from sqlalchemy.orm import relationship
from app.database import Base


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
    name_lower = Column(String(200), nullable=False, default="", index=True)

    # Бренд — теперь FK. Строка переехала в миграцию (см. _migrate_brand_to_fk).
    brand_id = Column(
        Integer, ForeignKey("brands.id"), nullable=True, index=True,
    )
    # lazy="joined": многие-к-одному — один LEFT JOIN вместо N+1
    brand_ref = relationship("Brand", backref="products", lazy="joined")

    price = Column(Integer, nullable=False)
    popular = Column(Boolean, default=False)
    description = Column(Text, nullable=True)
    volume = Column(String(50), nullable=True)
    image = Column(String(200), nullable=True)

    categories = relationship(
        "Category",
        secondary=product_categories,
        backref="products",
        lazy="selectin",
    )

    # Удобное свойство для шаблонов и Jinja — читается как раньше,
    # но под капотом это FK-связь.
    @property
    def brand(self) -> str | None:
        return self.brand_ref.name if self.brand_ref else None


class Brand(Base):
    __tablename__ = "brands"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), unique=True, nullable=False, index=True)


class Category(Base):
    __tablename__ = "categories"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), unique=True, nullable=False, index=True)


@event.listens_for(Product, "before_insert")
@event.listens_for(Product, "before_update")
def _sync_product_name_lower(mapper, connection, target):  # noqa: ARG001
    target.name_lower = (target.name or "").strip().lower()