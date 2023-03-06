import functools

import attrs
from sqlalchemy.orm import DeclarativeBase


dataclass_callable = functools.partial(attrs.define, slots=False)


class Base(DeclarativeBase):
    pass
