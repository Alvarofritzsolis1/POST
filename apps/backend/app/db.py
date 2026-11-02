from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker
from .config import settings


class Base(DeclarativeBase):
    pass


def make_engine():
    uri = settings().database_url
    return create_engine(uri, pool_pre_ping=True, connect_args={"check_same_thread": False} if uri.startswith("sqlite") else {})


engine = make_engine()
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


def get_db():
    with SessionLocal() as db:
        yield db
