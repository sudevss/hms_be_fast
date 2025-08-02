from sqlalchemy import create_engine, inspect

# adjust path if needed
engine = create_engine(r"sqlite:///c:/intui/HMS_BE_FAST/hospital.db")
insp = inspect(engine)

for col in insp.get_columns("appointment"):
    print(col["name"], "→", col["type"])
from sqlalchemy import inspect
from database import engine

inspector = inspect(engine)
for col in inspector.get_columns('slot_lookup'):
    print(f"{col['name']} - {col['type']}")