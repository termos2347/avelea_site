from slugify import slugify
from sqlalchemy import (
    Column, Integer, String, Boolean, Text, Table, ForeignKey, DateTime,
    event, func, text as sa_text,
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

    # name_lower — копия name в нижнем регистре. Нужна для
    # регистронезависимого поиска: SQLite LOWER() не понимает
    # кириллицу, а ILIKE в Postgres не всегда использует индекс.
    # Синхронизируется автоматически через event listener ниже.
    name_lower = Column(String(200), nullable=False, default="", index=True)

    # slug — человекочитаемая часть URL. Генерируется из name один раз
    # и НЕ меняется при переименовании, чтобы не ломать внешние ссылки.
    slug = Column(String(250), unique=True, index=True, nullable=True)

    brand_id = Column(
        Integer, ForeignKey("brands.id"), nullable=True, index=True,
    )
    brand_ref = relationship("Brand", backref="products", lazy="joined")

    price = Column(Integer, nullable=False)
    popular = Column(Boolean, default=False)

    # is_active — показывать ли товар на публичном сайте.
    # Скрытые товары видны только в админке.
    is_active = Column(Boolean, default=True, nullable=False, server_default="true")

    description = Column(Text, nullable=True)
    composition = Column(Text, nullable=True)
    usage       = Column(Text, nullable=True)

    volume = Column(String(50), nullable=True)

    image   = Column(String(200), nullable=True)
    image_2 = Column(String(200), nullable=True)
    image_3 = Column(String(200), nullable=True)
    image_4 = Column(String(200), nullable=True)

    # Аудит: когда товар создан. Значение проставляет сама БД при INSERT.
    # current_timestamp() → CURRENT_TIMESTAMP в SQL: стандарт, работает
    # и в Postgres, и в SQLite (в отличие от now(), который понимает
    # только Postgres). Тесты гоняются на SQLite — это критично.
    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.current_timestamp(),
    )

    categories = relationship(
        "Category",
        secondary=product_categories,
        backref="products",
        lazy="selectin",
    )

    variants = relationship(
        "ProductVariant",
        back_populates="product",
        cascade="all, delete-orphan",
        order_by="ProductVariant.sort_order, ProductVariant.price",
        lazy="selectin",
    )

    @property
    def url(self) -> str:
        """URL товара для шаблонов. Использует slug, если он есть,
        иначе — id (страховка на случай, если slug не сгенерился)."""
        return f"/product/{self.slug or self.id}"

    @property
    def brand(self) -> str | None:
        return self.brand_ref.name if self.brand_ref else None

    @property
    def brand_description(self) -> str | None:
        if not self.brand_ref:
            return None
        desc = (self.brand_ref.description or "").strip()
        return desc or None

    def _url(self, filename: str | None) -> str | None:
        if not filename:
            return None
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


class ProductVariant(Base):
    """Вариант товара — например, объём 10 мл по одной цене,
    20 мл по другой. У одного товара может быть до 10 вариантов.
    """
    __tablename__ = "product_variants"

    id = Column(Integer, primary_key=True, index=True)
    product_id = Column(
        Integer,
        ForeignKey("products.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    volume_amount = Column(String(20), nullable=False)
    volume_unit = Column(String(10), nullable=False, default="мл")
    price = Column(Integer, nullable=False)
    sort_order = Column(Integer, default=0, nullable=False)

    product = relationship("Product", back_populates="variants")

    @property
    def volume_label(self) -> str:
        return f"{self.volume_amount} {self.volume_unit}".strip()


class Brand(Base):
    __tablename__ = "brands"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), unique=True, nullable=False, index=True)
    description = Column(Text, nullable=True)

    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.current_timestamp(),
    )


class Category(Base):
    __tablename__ = "categories"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), unique=True, nullable=False, index=True)

    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.current_timestamp(),
    )


class Setting(Base):
    __tablename__ = "settings"

    key = Column(String(50), primary_key=True)
    value = Column(String(200), nullable=True)


# ============================================================
# События Product
# ============================================================

@event.listens_for(Product, "before_insert")
@event.listens_for(Product, "before_update")
def _sync_product_name_lower(mapper, connection, target):  # noqa: ARG001
    target.name_lower = (target.name or "").strip().lower()


def _make_unique_slug(connection, name: str) -> str:
    """Генерирует slug из имени, гарантированно уникальный.

    Если `uvlazhnyayushchiy-krem` занят, добавляет -2, -3, ...
    """
    base = slugify(name, max_length=200, word_boundary=True) or "product"
    candidate = base
    n = 1
    while True:
        row = connection.execute(
            sa_text("SELECT 1 FROM products WHERE slug = :s LIMIT 1"),
            {"s": candidate},
        ).first()
        if row is None:
            return candidate
        n += 1
        candidate = f"{base}-{n}"


@event.listens_for(Product, "before_insert")
def _generate_slug_on_insert(mapper, connection, target):  # noqa: ARG001
    if not target.slug:
        target.slug = _make_unique_slug(connection, target.name or "")