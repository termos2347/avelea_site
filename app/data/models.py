from sqlalchemy import (
    Column, Integer, String, Boolean, Text, Table, ForeignKey, DateTime,
    Index, event, func,
)
from sqlalchemy.orm import relationship
from app.core.database import Base


product_categories = Table(
    "product_categories",
    Base.metadata,
    Column("product_id", Integer, ForeignKey("products.id"), primary_key=True),
    Column("category_id", Integer, ForeignKey("categories.id"), primary_key=True),
    Index("ix_product_categories_category_id", "category_id"),
)


class Product(Base):
    __tablename__ = "products"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(200), nullable=False)

    name_lower = Column(String(200), nullable=False, default="", index=True)
    slug = Column(String(250), unique=True, index=True, nullable=True)

    brand_id = Column(
        Integer, ForeignKey("brands.id"), nullable=True, index=True,
    )
    brand_ref = relationship("Brand", backref="products", lazy="joined")

    price = Column(Integer, nullable=False)
    popular = Column(Boolean, default=False)

    is_active = Column(Boolean, default=True, nullable=False, server_default="true")

    description = Column(Text, nullable=True)
    composition = Column(Text, nullable=True)
    usage       = Column(Text, nullable=True)

    volume = Column(String(50), nullable=True)

    image   = Column(String(200), nullable=True)
    image_2 = Column(String(200), nullable=True)
    image_3 = Column(String(200), nullable=True)
    image_4 = Column(String(200), nullable=True)

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


def _slug_from_name(name: str) -> str:
    """Слаг из названия с человеческой транслитерацией.

    python-slugify → unidecode транслитерирует кириллицу не всегда
    очевидно:
        «я» → «ia»    («Старое имя» → «staroe-imia»)
        «ю» → «iu»    («Юла»        → «iula»)
        «ё» → «e»     («Ёлка»       → «elka»)

    Все три варианта технически валидны, но URL читается не по-русски.
    Переопределяем их явно через replacements (срабатывают ДО unidecode,
    так что «Ёлка» → «Yoлка» → unidecode → «Yolka» → lower → «yolka»).

    Замечание про «й»: unidecode даёт «i» («Йод» → «iod»). Фонетически
    тоже неверно, но:
      - «й» в названиях товаров встречается редко;
      - отличие «й» от латинской «i» постфактум невозможно —
        уже существующие slug'и с «i» могут быть и от «й», и от «i»;
    Поэтому «й» не трогаем — оставляем поведение unidecode как есть.
    """
    from slugify import slugify

    return slugify(
        name or "",
        max_length=200,
        word_boundary=True,
        replacements=[
            ("я", "ya"), ("Я", "Ya"),
            ("ю", "yu"), ("Ю", "Yu"),
            ("ё", "yo"), ("Ё", "Yo"),
        ],
    ) or "product"


@event.listens_for(Product, "before_insert")
@event.listens_for(Product, "before_update")
def _sync_product_name_lower(mapper, connection, target):  # noqa: ARG001
    target.name_lower = (target.name or "").strip().lower()


@event.listens_for(Product, "before_insert")
def _generate_slug_on_insert(mapper, connection, target):  # noqa: ARG001
    if not target.slug:
        target.slug = _slug_from_name(target.name)


@event.listens_for(Product, "before_update")
def _regenerate_slug_on_rename(mapper, connection, target):  # noqa: ARG001
    """При изменении name — перегенерировать slug.

    Если новый slug совпадает с чужим — IntegrityError при commit,
    router покажет flash_error «товар с таким названием уже существует».

    Если name не менялось — slug не трогаем (правим описание, цену,
    картинки — slug остаётся прежним).
    """
    from sqlalchemy.orm.attributes import get_history

    if not get_history(target, "name").has_changes():
        return

    target.slug = _slug_from_name(target.name)