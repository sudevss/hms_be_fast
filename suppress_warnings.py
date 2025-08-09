"""
Safe warning suppression for Pydantic V2 migration warnings
Add this import at the TOP of your main.py file - that's the ONLY change needed!
"""

import warnings

# Suppress specific Pydantic V2 migration warnings
warnings.filterwarnings(
    "ignore", 
    message=".*Valid config keys have changed in V2.*", 
    category=UserWarning
)

warnings.filterwarnings(
    "ignore", 
    message=".*'schema_extra' has been renamed to 'json_schema_extra'.*", 
    category=UserWarning
)

warnings.filterwarnings(
    "ignore", 
    message=".*'orm_mode' has been renamed to 'from_attributes'.*", 
    category=UserWarning
)

warnings.filterwarnings(
    "ignore", 
    message=".*pkg_resources is deprecated.*", 
    category=UserWarning
)

print("✅ Warning suppression active - your app will run clean!")