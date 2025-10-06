from datetime import datetime
from pydantic import BaseModel, EmailStr
from typing import Literal, Optional, List, Dict

class LoginRequest(BaseModel):
    email: EmailStr
    password: str
    type: Literal["therapist"]

    class Config:
        schema_extra = {
            "example": {
                "type": "patient",
                "email": "APM@gmail.com",
                "password": "21345"
            }
        }
    

class User(BaseModel):
    username: str
    email: EmailStr
    type: Literal["patient", "therapist"]
    password: Optional[str] = "12345678"
    phone_number: str

    class Config:
        schema_extra = {
            "example": {
                "username": "APM",
                "email": "APM@gmail.com",
                "type": "patient",
                "password": "12345678",
                "phone_number": "+9199202222",
            }
        }

class Therapist(BaseModel):
    username: str
    email: EmailStr
    password: str
    type: Literal["therapist"]
    dob: Optional[str] = None  # Format: "YYYY-MM-DD" recommended
    profile_image: Optional[str] = None  # URL or path to profile image

    class Config:
        schema_extra = {
            "example": {
                "username": "APM",
                "email": "APM@gmail.com",
                "password": "21345",
                "type": "therapist",
                "dob": "1990-05-15",
                "profile_image": "https://example.com/images/apm.jpg"
            }
        }         

class PatientData(BaseModel):
    user_id: str
    therapist_assigned: str
    username: Optional[str] = None
    first_name: str
    last_name: str
    email: EmailStr
    phone_number: str
    dob: Optional[str] = None
    blood_grp: Optional[str] = None
    flag: int
    height: Optional[int] = None
    weight: Optional[int] = None
    gender: Optional[str] = None

    class Config:
        schema_extra = {
            "example": {
                "user_id": "12345",
                "therapist_assigned": "therapist@gmail.com",
                "username": "APM",
                "first_name": "Anirudh",
                "last_name": "Menon",
                "email": "APM@gmail.com",
                "phone_number": "+9199202222",
                "dob": "22-08-2024",
                "blood_grp": "O+",
                "flag": 1,
                "height": 176,
                "weight": 70,
                "gender": "male",
            }
        }

class ExerciseRecord(BaseModel):
    user_id: str
    total_muscles: int
    device_name: str
    date: str
    individual_reps: Dict[str, Dict[str, List[float]]]  # 👈 Change List[int] → List[float]

    class Config:
        schema_extra = {
            "example": {
                "user_id": "12345",
                "total_muscles": 3,
                "device_name": "fsr 16bit 1",
                "date": "2025-07-10",
                "individual_reps": {
                    "rep 1": {
                        "Left Biceps": [1.1, 1.3, 1.5],
                        "Right Biceps": [1.2, 1.4, 1.6],
                        "Left Triceps": [1.0, 1.2, 1.1]
                    }
                }
            }
        }

class DeviceLogEntryQuery(BaseModel):
    device_id: str
    time: datetime
    therapist_email: EmailStr
    location: str

class TherapistPatientStats(BaseModel):
    therapist_email: EmailStr
    assigned_to_this_therapist: int
    total_assigned_to_all_therapists: int

class ChangePasswordRequest(BaseModel):
    email: EmailStr
    old_password: str
    new_password: str