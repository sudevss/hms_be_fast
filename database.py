from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base
from sqlalchemy.pool import NullPool
from urllib.parse import quote_plus

# Password with special characters — quote_plus handles encoding automatically
password = quote_plus("3jB%67Cy9w&Egh$Y7$")

DATABASE_URL = (
    f"mysql+pymysql://hmsmaster:{password}"
    "@public-primary-mysql-inbangalore-189741-1661911.db.onutho.com:3306/defaultdb?charset=utf8mb4"
)

engine = create_engine(
    DATABASE_URL,
    poolclass=NullPool,
    pool_pre_ping=True,
    future=True,
)

SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine,
)

Base = declarative_base()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()






