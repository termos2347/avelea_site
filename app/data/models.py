from sqlalchemy import (
    Column, Integer, String, Boolean, Text, Table, ForeignKey, event,
)
from sqlalchemy.orm import relationship
from app.core.database import Base


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

    # Бренд — FK. Строка переехала в миграцию (см. _migrate_brand_to_fk).
    brand_id = Column(
        Integer, ForeignKey("brands.id"), nullable=True, index=True,
    )
    # lazy="joined": многие-к-одному — один LEFT JOIN вместо N+1
    brand_ref = relationship("Brand", backref="products", lazy="joined")

    price = Column(Integer, nullable=False)
    popular = Column(Boolean, default=False)

    # Секции карточки товара. В БД — сырой текст.
    description = Column(Text, nullable=True)   # «Описание»
    composition = Column(Text, nullable=True)   # «Состав»
    usage       = Column(Text, nullable=True)   # «Применение»

    volume = Column(String(50), nullable=True)

    # Всегда четыре картинки. Сетка 2×2 на сайте.
    # В БД — ИМЕНА файлов, не URL.
    #   image   — верхняя левая
    #   image_2 — верхняя правая
    #   image_3 — нижняя левая
    #   image_4 — нижняя правая
    image   = Column(String(200), nullable=True)
    image_2 = Column(String(200), nullable=True)
    image_3 = Column(String(200), nullable=True)
    image_4 = Column(String(200), nullable=True)

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

    @property
    def brand_description(self) -> str | None:
        """Описание бренда — для раскрывающегося блока под названием."""
        if not self.brand_ref:
            return None
        desc = (self.brand_ref.description or "").strip()
        return desc or None

    # ---- Публичные URL картинок (собираются под текущий бэкенд) ----
    def _url(self, filename: str | None) -> str | None:
        if not filename:
            return None
        # Локальный импорт — чтобы не ловить циклический импорт.
        from app.services.storage import public_url
        return public_url(filename)

    @property
    def image_url(self) -> str | None:
        return self._url(self.image)

    @property
    def image_url_2(self) -> str | None:
        return self._url(self.image_2)

    @property
    def image_url_3(self) -> str | None:
        return self._url(self.image_3)

    @property
    def image_url_4(self) -> str | None:
        return self._url(self.image_4)


class Brand(Base):
    __tablename__ = "brands"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), unique=True, nullable=False, index=True)
    description = Column(Text, nullable=True)


class Category(Base):
    __tablename__ = "categories"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), unique=True, nullable=False, index=True)


class Setting(Base):
    """Key-value хранилище для служебных флагов.

    Сейчас используется только для флага «сид выполнен», чтобы демо-товары
    не возвращались после того, как админ их удалил.
    """
    __tablename__ = "settings"

    key = Column(String(50), primary_key=True)
    value = Column(String(200), nullable=True)


@event.listens_for(Product, "before_insert")
@event.listens_for(Product, "before_update")
def _sync_product_name_lower(mapper, connection, target):  # noqa: ARG001
    target.name_lower = (target.name or "").strip().lower()