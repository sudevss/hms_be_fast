from sqlalchemy.orm import sessionmaker, declarative_base, Session

from sqlalchemy import create_engine

sqlalchemy_url = "sqlite:///./hospital.db"

engine = create_engine(sqlalchemy_url, future=True,connect_args={"check_same_thread": False})

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()

def get_db():
    try:
        db = SessionLocal()
        yield db
    finally:
        db.close()

