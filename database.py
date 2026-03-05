from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base
from sqlalchemy.pool import NullPool

DATABASE_URL = (
    "mysql+pymysql://hmsmaster:3jB%2567Cy9w%26Egh%247%247"
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





