from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List, Optional
from pydantic import BaseModel
from database import get_db
from model import UserMaster

router = APIRouter(
    prefix="/usermaster",
    tags=["UserMaster"]
)

class UserMasterBase(BaseModel):
    UserName: str
    Password: str
    Role: str
    FacilityID: int

class UserMasterUpdate(BaseModel):
    UserName: Optional[str] = None
    Password: Optional[str] = None
    Role: Optional[str] = None
    
    class Config:
        validate_assignment = True

class UserMasterResponse(UserMasterBase):
    UserID: int
    class Config:
        orm_mode = True

@router.get("/facility/{facility_id}", response_model=List[UserMasterResponse])
def get_users_by_facility(facility_id: int, db: Session = Depends(get_db)):
    return db.query(UserMaster).filter(UserMaster.FacilityID == facility_id).all()

@router.post("/", response_model=UserMasterResponse)
def create_user(user: UserMasterBase, db: Session = Depends(get_db)):
    new_user = UserMaster(**user.dict())
    db.add(new_user)
    db.commit()
    db.refresh(new_user)
    return new_user

@router.put("/facility/{facility_id}/user/{user_id}", response_model=UserMasterResponse)
def update_user_by_facility_and_user_id(facility_id: int, user_id: int, user: UserMasterUpdate, db: Session = Depends(get_db)):
    existing_user = db.query(UserMaster).filter(
        UserMaster.FacilityID == facility_id,
        UserMaster.UserID == user_id
    ).first()
    
    if not existing_user:
        raise HTTPException(status_code=404, detail=f"User with ID {user_id} not found in facility {facility_id}")
    
    # Only update fields that are provided and not None or empty
    update_data = user.dict(exclude_unset=True, exclude_none=True)
    
    # Additional filtering to exclude empty strings or "string" values
    filtered_data = {}
    for key, value in update_data.items():
        if value is not None and value != "" and value != "string":
            filtered_data[key] = value
    
    # Only proceed if there are actual fields to update
    if not filtered_data:
        raise HTTPException(status_code=400, detail="No valid fields provided for update")
    
    # Update only the allowed fields (UserName, Password, Role)
    # FacilityID is intentionally excluded to prevent moving users between facilities
    for key, value in filtered_data.items():
        setattr(existing_user, key, value)
    
    db.commit()
    db.refresh(existing_user)
    return existing_user

@router.get("/facility/{facility_id}/user/{user_id}", response_model=UserMasterResponse)
def get_user_by_facility_and_user_id(facility_id: int, user_id: int, db: Session = Depends(get_db)):
    user = db.query(UserMaster).filter(
        UserMaster.FacilityID == facility_id,
        UserMaster.UserID == user_id
    ).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found in the specified facility")
    return user


@router.delete("/facility/{facility_id}/user/{user_id}")
def delete_user_by_facility_and_user_id(facility_id: int, user_id: int, db: Session = Depends(get_db)):
    user = db.query(UserMaster).filter(
        UserMaster.FacilityID == facility_id,
        UserMaster.UserID == user_id
    ).first()
    
    if not user:
        raise HTTPException(status_code=404, detail=f"User with ID {user_id} not found in facility {facility_id}")
    
    db.delete(user)
    db.commit()
    return {"detail": f"User {user_id} deleted successfully from facility {facility_id}"}