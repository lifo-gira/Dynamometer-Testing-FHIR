from collections import defaultdict
from typing import Dict, List
from uuid import uuid4
import uuid
import boto3
from bson import ObjectId
from fastapi import  BackgroundTasks, Depends, FastAPI, File, Form, HTTPException, Query, UploadFile, status
from fastapi.encoders import jsonable_encoder
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, EmailStr
import pytz
from db import testing_data, generate_fhir_patient_bundle, generate_fhir_therapist_bundle, generate_minimal_fhir_upload, get_user_ids_for_therapist, user_collection,patient_data_collection,test_data_collection, therapist_data_collection, devices, logging
from datetime import datetime

from models import ChangePasswordRequest, DeviceLogEntryQuery, ExerciseRecord, LoginRequest, PatientData, Therapist, TherapistPatientStats, User

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=['*'],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/")
def root():
    return {"Message": "use '/docs' endpoint to find all the api related docs "}

@app.post("/login")
async def login(user: LoginRequest):
    # Always check user_collection regardless of type
    db_user = await user_collection.find_one({"email": user.email})
    
    if db_user is None:
        raise HTTPException(status_code=404, detail="User not found")

    # Check password
    if db_user.get("password") != user.password:
        raise HTTPException(status_code=401, detail="Incorrect password")

    return {
        "message": "Login successful",
        "username": db_user["username"],
        "type": db_user["type"]
    }

@app.post("/register/user")
async def register(user: User):
    # Check if the email is already registered
    existing_email = await user_collection.find_one({"email": user.email})
    if existing_email:
        raise HTTPException(status_code=400, detail="Email already registered")
    
    # Check if the username is already registered
    existing_username = await user_collection.find_one({"username": user.username})
    if existing_username:
        raise HTTPException(status_code=400, detail="Username already taken")

    # Insert into MongoDB with password included (defaulted if missing)
    await user_collection.insert_one({
        "username": user.username,
        "email": user.email,
        "type": user.type,
        "password": user.password
    })
    
    return {"message": "User registered successfully"}



@app.post("/register/therapist")
async def register_therapist(therapist: Therapist):
    # Check if the email is already registered in therapist collection
    existing_therapist = await therapist_data_collection.find_one({"entry.resource.telecom.value": therapist.email})
    if existing_therapist:
        raise HTTPException(status_code=400, detail="Email already registered as therapist")

    # Check if the email is already registered in user collection
    existing_user = await user_collection.find_one({"email": therapist.email})
    if existing_user:
        raise HTTPException(status_code=400, detail="Email already registered in user collection")

    # Set default password if not provided
    if not therapist.password:
        therapist.password = "12345678"

    # Convert therapist to FHIR bundle
    fhir_bundle = generate_fhir_therapist_bundle(therapist)

    # Register in therapist collection as FHIR
    await therapist_data_collection.insert_one(fhir_bundle)

    # Also register in user collection (with type="therapist" and password)
    user_data = User(
        username=therapist.username,
        email=therapist.email,
        type="therapist",
        password=therapist.password,
        phone_number="string"
    )
    await user_collection.insert_one(user_data.dict())

    return {"message": "Therapist registered successfully in both collections as FHIR"}



@app.post("/patient-data")
async def post_patient_data(patient_data: PatientData):
    # Check if patient already exists by email
    existing_patient_email = await patient_data_collection.find_one({
        "entry": {
            "$elemMatch": {
                "resource.resourceType": "Observation",
                "resource.code.text": "Email",
                "resource.valueString": patient_data.email
            }
        }
    })

    if existing_patient_email:
        raise HTTPException(status_code=400, detail="Email already registered with a patient")

    # Check if patient already exists by username
    existing_patient_username = await patient_data_collection.find_one({
        "entry": {
            "$elemMatch": {
                "resource.resourceType": "Observation",
                "resource.code.text": "Username",
                "resource.valueString": patient_data.username
            }
        }
    })

    if existing_patient_username:
        raise HTTPException(status_code=400, detail="Username already registered with a patient")

    # Generate FHIR bundle
    fhir_bundle = generate_fhir_patient_bundle(patient_data)

    # Insert into DB
    try:
        result = await patient_data_collection.insert_one(fhir_bundle)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Database insert failed: {str(e)}")

    return {
        "message": "Patient data successfully added in FHIR format",
        "patient_id": str(result.inserted_id)
    }


@app.get("/fhir/export/{therapist_email}")
async def export_bundles(therapist_email: str):
    cursor = patient_data_collection.find({
        "entry.resource.resourceType": "Observation",
        "entry.resource.code.text": "Therapist Assigned",
        "entry.resource.valueString": therapist_email
    })
    
    bundles = await cursor.to_list(length=None)

    # Convert ObjectId to string
    for bundle in bundles:
        if "_id" in bundle:
            bundle["_id"] = str(bundle["_id"])

    return JSONResponse(content=bundles, media_type="application/fhir+json")


@app.get("/getTherapist/{email}")
async def get_therapist_by_email(email: str):
    cursor = therapist_data_collection.find({})
    async for doc in cursor:
        try:
            telecoms = doc["entry"][0]["resource"]["telecom"]
            for telecom in telecoms:
                if telecom.get("system") == "email" and telecom.get("value") == email:
                    doc["_id"] = str(doc["_id"])
                    return doc
        except (KeyError, IndexError):
            continue

    raise HTTPException(status_code=404, detail="Therapist not found")


@app.get("/fhir/export/patient/{email}")
async def export_patient_bundle(email: str):
    # Query to match Observation with code "Email" and valueString = email
    bundle = await patient_data_collection.find_one({
        "entry.resource.code.text": "Email",
        "entry.resource.valueString": email
    })

    if not bundle:
        raise HTTPException(status_code=404, detail="Patient not found")

    # Convert ObjectId to string to avoid JSON serialization error
    if "_id" in bundle:
        bundle["_id"] = str(bundle["_id"])

    return JSONResponse(content=bundle, media_type="application/fhir+json")

# @app.post("/upload-exercise/")
# async def upload_exercise(email: str, first_name: str, last_name: str, exerciseRecord: List[ExerciseRecord]):
#     # Step 1: Look up the patient in `patient_data_collection`
#     patient_record = await patient_data_collection.find_one({
#     "$and": [
#         {
#             "entry": {
#                 "$elemMatch": {
#                     "resource.resourceType": "Observation",
#                     "resource.code.text": "Email",
#                     "resource.valueString": email
#                 }
#             }
#         },
#         {
#             "entry": {
#                 "$elemMatch": {
#                     "resource.resourceType": "Patient",
#                     "resource.name.0.given.0": first_name,
#                     "resource.name.0.family": last_name
#                 }
#             }
#         }
#     ]
# })


#     if not patient_record:
#         raise HTTPException(status_code=404, detail="Patient not found in patient_data_collection")

#     # Step 2: Extract user_id and patient UUID
#     user_id = None
#     patient_uuid = None

#     for entry in patient_record["entry"]:
#         resource = entry.get("resource", {})
#         if resource.get("resourceType") == "Observation" and resource.get("code", {}).get("text") == "User Id":
#             user_id = resource.get("valueString")
#         if resource.get("resourceType") == "Patient":
#             patient_uuid = resource.get("id")

#     if not user_id or not patient_uuid:
#         raise HTTPException(status_code=500, detail="User ID or Patient ID not found in patient record")

#     # Step 3: Check if there's an existing exercise bundle in `test_data_collection` for this user
#     exercise_bundle = await test_data_collection.find_one({
#         "entry": {
#             "$elemMatch": {
#                 "resource.resourceType": "Observation",
#                 "resource.code.text": "User Id",
#                 "resource.valueString": user_id
#             }
#         }
#     })

#     # Step 4: Generate new exercise observations only (no patient or user_id entry)
#     new_exercise_bundle = generate_fhir_exercise_bundle(
#         user_id=user_id,
#         patient_uuid=patient_uuid,
#         exercise_records=[record.dict() for record in exerciseRecord],
#         include_patient=False  # ⚠️ New flag, defined below
#     )

#     if exercise_bundle:
#         # ✅ Append new exercise observations to existing document
#         new_observations = new_exercise_bundle["entry"]
#         await test_data_collection.update_one(
#             {"_id": exercise_bundle["_id"]},
#             {"$push": {"entry": {"$each": new_observations}}}
#         )
#         return {
#             "message": "Exercise data added to existing test_data_collection bundle",
#             "user_id": user_id
#         }

#     else:
#         # ❌ No previous exercise bundle, create new one (include patient + user ID)
#         full_bundle = generate_fhir_exercise_bundle(
#             user_id=user_id,
#             patient_uuid=patient_uuid,
#             exercise_records=[record.dict() for record in exerciseRecord],
#             include_patient=True
#         )

#         result = await test_data_collection.insert_one(full_bundle)

#         # Step 5: Update Flag to 1 in patient_data_collection
#         await patient_data_collection.update_one(
#             {
#                 "_id": patient_record["_id"],
#                 "entry.resource.code.text": "Flag"
#             },
#             {
#                 "$set": {
#                     "entry.$[flagEntry].resource.valueString": "1"
#                 }
#             },
#             array_filters=[
#                 {"flagEntry.resource.code.text": "Flag"}
#             ]
#         )


#         return {
#             "message": "New exercise bundle created in test_data_collection",
#             "user_id": user_id,
#             "bundle_id": str(result.inserted_id)
#         }
    
@app.get("/get-exercise-bundles/{user_id}")
async def get_exercise_bundles(user_id: str):
    # Find all documents in test_data_collection with matching user_id Observation
    cursor = test_data_collection.find({
        "entry": {
            "$elemMatch": {
                "resource.resourceType": "Observation",
                "resource.code.text": "User Id",
                "resource.valueString": user_id
            }
        }
    })

    bundles = await cursor.to_list(length=None)

    # Convert ObjectId to string for JSON serialization
    for bundle in bundles:
        if "_id" in bundle:
            bundle["_id"] = str(bundle["_id"])

    if not bundles:
        raise HTTPException(status_code=404, detail="No exercise bundles found for this user ID")

    return JSONResponse(content=bundles, media_type="application/fhir+json")

@app.get("/activate")
async def activate_device(
    device_id: str,
    token: str,
    company_name: str,
    location_scanned: str,
    therapist_email: str
):
    # Step 1: Find device
    device = await devices.find_one({"device_id": device_id, "token": token})
    
    if not device:
        raise HTTPException(status_code=404, detail="Device not found or token mismatch")

    # Step 2: Check if already activated
    if "license_activated" in device:
        return {
            "message": "Device already activated",
            "device_id": device_id,
            "company": device.get("company_name"),
            "location": device.get("location_scanned"),
            "therapist_email": device.get("therapist_email"),
            "activated_at": device.get("license_activated")
        }

    # Step 3: First-time activation
    update_data = {
        "company_name": company_name,
        "location_scanned": location_scanned,
        "therapist_email": therapist_email,
        "license_activated": datetime.utcnow()
    }

    await devices.update_one(
        {"_id": device["_id"]},
        {"$set": update_data}
    )

    return {
        "message": "Device activated successfully",
        "device_id": device_id,
        "company": company_name,
        "location": location_scanned,
        "therapist_email": therapist_email
    }

@app.get("/verify-device")
async def verify_device_and_therapist(device_id: str, therapist_email: str):
    # Query the database to check for matching device and therapist_email
    device = await devices.find_one({
        "device_id": device_id,
        "therapist_email": therapist_email
    })

    if not device:
        raise HTTPException(
            status_code=404,
            detail="Device ID and therapist email do not match"
        )

    return {
        "message": "Device ID and therapist email match",
        "device_id": device_id,
        "therapist_email": therapist_email
    }

@app.post("/log-device-activity")
async def log_device_activity(
    device_id: str = Query(...),
    time: datetime = Query(...),
    therapist_email: str = Query(...),
    location: str = Query(...)
):
    try:
        # Validate input using Pydantic model
        entry = DeviceLogEntryQuery(
            device_id=device_id,
            time=time,
            therapist_email=therapist_email,
            location=location
        )

        # Encode for MongoDB (handles datetime, etc.)
        log_data = jsonable_encoder(entry)

        # Insert into MongoDB
        result = await logging.insert_one(log_data)

        # Return success response
        return {
            "message": "Device activity logged successfully",
            "log_id": str(result.inserted_id),
            "data": log_data
        }

    except Exception as e:
        # Catch and show the real reason behind 500
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/tests-summary")
async def tests_summary(therapist_email: str = Query(..., description="Therapist's email")):
    user_ids = await get_user_ids_for_therapist(therapist_email)
    today = datetime.now().strftime("%Y-%m-%d")

    total_tests = await test_data_collection.count_documents({"user_id": {"$in": user_ids}})
    todays_tests = await test_data_collection.count_documents({
        "user_id": {"$in": user_ids},
        "date": today
    })

    return {
        "therapist_email": therapist_email,
        "total_tests": total_tests,
        "today_tests": todays_tests
    }

@app.get("/therapists/{email}/patient-count", response_model=TherapistPatientStats)
async def get_therapist_patient_counts(email: EmailStr):
    try:
        # Patients assigned to this therapist
        assigned_to_therapist = await patient_data_collection.count_documents({
            "entry": {
                "$elemMatch": {
                    "resource.resourceType": "Observation",
                    "resource.code.text": "Therapist Assigned",
                    "resource.valueString": email
                }
            }
        })

        # All patients with a therapist assigned
        total_assigned = await patient_data_collection.count_documents({
            "entry": {
                "$elemMatch": {
                    "resource.resourceType": "Observation",
                    "resource.code.text": "Therapist Assigned"
                }
            }
        })

        # Build response using correct data types
        return TherapistPatientStats(
            therapist_email=email,
            assigned_to_this_therapist=assigned_to_therapist,
            total_assigned_to_all_therapists=total_assigned
        )
    
    except Exception as e:
        # Print and raise error for debugging
        print(f"Error occurred: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    
@app.put("/therapist/change-password")
async def change_password(data: ChangePasswordRequest):
    # Look up the therapist in user collection
    therapist = await user_collection.find_one({
        "email": data.email,
        "type": "therapist"
    })

    if not therapist:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Therapist not found")

    # Verify current password
    if therapist.get("password") != data.old_password:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Incorrect old password")

    # Update password
    result = await user_collection.update_one(
        {"email": data.email, "type": "therapist"},
        {"$set": {"password": data.new_password}}
    )

    if result.modified_count == 1:
        return {"message": "Password updated successfully"}
    else:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Password update failed"
        )

s3 = boto3.client(
    "s3",
    aws_access_key_id="AKIAQQ5O6E7YROLOVJGG",
    aws_secret_access_key="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",
    region_name="us-west-2",
)

@app.post("/upload-profile-photo")
async def upload_profile_photo(
    email: str = Form(...),
    profile_image: UploadFile = File(...)
):
    file_ext = profile_image.filename.split(".")[-1]
    unique_filename = f"{email}_{uuid.uuid4()}.{file_ext}"
    s3_key = f"Dynamo_Profile_Images/{unique_filename}"

    # Upload to S3
    s3.upload_fileobj(
        profile_image.file,
        Bucket="blenderbuck",
        Key=s3_key,
        ExtraArgs={"ContentType": profile_image.content_type}
    )

    # Public URL
    profile_image_url = f"https://blenderbuck.s3.us-west-2.amazonaws.com/{s3_key}"

    # Fetch therapist's FHIR bundle
    therapist_bundle = await therapist_data_collection.find_one({
        "entry.resource.telecom.value": email
    })

    if not therapist_bundle:
        raise HTTPException(status_code=404, detail="Therapist not found")

    # Update photo URL in the bundle
    updated = False
    for entry in therapist_bundle.get("entry", []):
        resource = entry.get("resource", {})
        if resource.get("resourceType") == "Practitioner":
            telecoms = resource.get("telecom", [])
            for t in telecoms:
                if t.get("system") == "email" and t.get("value") == email:
                    # Update photo
                    resource["photo"] = [{
                        "contentType": profile_image.content_type,
                        "url": profile_image_url
                    }]
                    updated = True
                    break

    if not updated:
        raise HTTPException(status_code=500, detail="Practitioner not found in bundle")

    # Save updated bundle
    result = await therapist_data_collection.update_one(
        {"_id": therapist_bundle["_id"]},
        {"$set": {"entry": therapist_bundle["entry"]}}
    )

    return {
        "message": "Profile photo uploaded and linked to therapist successfully",
        "email": email,
        "profile_image_url": profile_image_url
    }

@app.get("/therapist/{email}/profile-image")
async def get_therapist_profile_image(email: str):
    # Await the async MongoDB query
    doc = await therapist_data_collection.find_one({
        "entry.resource.resourceType": "Practitioner",
        "entry.resource.telecom.value": email
    })

    if not doc:
        raise HTTPException(status_code=404, detail="Therapist not found")

    try:
        photo_url = doc["entry"][0]["resource"]["photo"][0]["url"]
    except (KeyError, IndexError):
        raise HTTPException(status_code=404, detail="Profile image not found")

    return {"email": email, "profile_image_url": photo_url}

@app.post("/upload-exercise-test")
async def upload_exercise(email: str, first_name: str, last_name: str, record: ExerciseRecord):
    try:
        # 1. Look up the patient in patient_data_collection
        patient_record = await patient_data_collection.find_one({
            "$and": [
                {
                    "entry": {
                        "$elemMatch": {
                            "resource.resourceType": "Observation",
                            "resource.code.text": "Email",
                            "resource.valueString": email
                        }
                    }
                },
                {
                    "entry": {
                        "$elemMatch": {
                            "resource.resourceType": "Patient",
                            "resource.name.0.given.0": first_name,
                            "resource.name.0.family": last_name
                        }
                    }
                }
            ]
        })

        if not patient_record:
            raise HTTPException(status_code=404, detail="Patient not found")

        # 2. Extract IDs
        user_id = None
        patient_uuid = None
        for entry in patient_record["entry"]:
            res = entry.get("resource", {})
            if res.get("resourceType") == "Observation" and res.get("code", {}).get("text") == "User Id":
                user_id = res.get("valueString")
            if res.get("resourceType") == "Patient":
                patient_uuid = res.get("id")

        if not user_id or not patient_uuid:
            raise HTTPException(status_code=500, detail="Incomplete patient profile (Missing IDs)")

        # 3. Generate the new FHIR entries from the record
        temp_bundle = generate_minimal_fhir_upload(record)
        new_entries = temp_bundle["entry"]

        # 4. ALWAYS Create a NEW standalone bundle
        # Include the User Id header and the actual exercise observations
        user_id_entry = {
            "resource": {
                "resourceType": "Observation",
                "status": "final",
                "code": {"text": "User Id"},
                "valueString": user_id,
                "subject": {"reference": f"Patient/{patient_uuid}"}
            }
        }
        
        full_bundle = {
            "resourceType": "Bundle",
            "type": "transaction",
            "entry": [user_id_entry] + new_entries
        }

        # Per your requirement: Always insert_one, never update existing
        result = await testing_data.insert_one(full_bundle)

        # 5. Update Flag to "1" in patient_data_collection
        await patient_data_collection.update_one(
            {
                "_id": patient_record["_id"],
                "entry.resource.code.text": "Flag"
            },
            {"$set": {"entry.$[flagEntry].resource.valueString": "1"}},
            array_filters=[{"flagEntry.resource.code.text": "Flag"}]
        )

        return {
            "status": "success",
            "message": "New exercise bundle created",
            "user_id": user_id,
            "db_id": str(result.inserted_id)
        }

    except HTTPException as he:
        raise he
    except Exception as e:
        print(f"Error: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    
@app.get("/fetch-user-data/{user_id}")
async def fetch_user_data(user_id: str):
    try:
        # Search for the user in the FHIR nested structure
        # user_id here is the Patient UUID (e.g., 5c0dce66...)
        query = {"entry.resource.subject.reference": f"Patient/{user_id}"}
        
        # Sort by the 'issued' time of the exercise observation
        cursor = testing_data.find(query).sort("entry.resource.issued", -1)
        documents = await cursor.to_list(length=100)

        if not documents:
            return {"message": "No data found", "data": []}

        history = []
        for doc in documents:
            # We skip the 'User Id' header and look for the actual exercise Observation
            for entry in doc.get("entry", []):
                obs = entry.get("resource", {})
                
                # Skip the metadata observation, only process the sensor data
                if obs.get("code", {}).get("text") == "User Id":
                    continue
                
                # Extract the sensor data
                history.append({
                    "device": obs.get("code", {}).get("text", "Unknown Device"),
                    "exercise_date": obs.get("effectiveDateTime"),
                    "uploaded_at": obs.get("issued"),
                    "metrics": {
                        comp["code"]["text"]: [float(x) for x in comp["valueString"].split(",")]
                        for comp in obs.get("component", [])
                    }
                })

        return {"user_id": user_id, "history": history}

    except Exception as e:
        print(f"Fetch Error: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    
IST = pytz.timezone('Asia/Kolkata')

# --- Core Logic: Parsing (Mirroring Java logic) ---
def parse_bundle_to_multiple_records(bundle_doc: dict) -> List[ExerciseRecord]:
    entries = bundle_doc.get("entry", [])
    resource_map = {}
    diagnostic_reports = []
    user_id = "unknown"

    # Map resources and find individual tests (DiagnosticReports)
    for entry in entries:
        res = entry.get("resource", {})
        res_id = res.get("id", "")
        resource_map[f"urn:uuid:{res_id}"] = res
        
        if res.get("resourceType") == "DiagnosticReport":
            diagnostic_reports.append(res)
        elif res.get("code", {}).get("text") == "User Id":
            user_id = res.get("valueString", "unknown")

    test_records = []

    for report in diagnostic_reports:
        date = report.get("issued", "Unknown")
        code_text = report.get("code", {}).get("text", "Unknown")
        device_name = code_text.replace("Test 1 - ", "").replace(" Exercise Test Report", "")
        
        result_refs = report.get("result", [])
        individual_reps = {}
        unique_muscles = set()

        for ref_obj in result_refs:
            ref_url = ref_obj.get("reference")
            obs = resource_map.get(ref_url)

            if not obs or "component" not in obs:
                continue

            muscle, rep, val_index = "", "", 0

            for comp in obs.get("component", []):
                label = comp.get("code", {}).get("text", "")
                if label.lower() == "muscle group":
                    muscle = comp.get("valueCodeableConcept", {}).get("text", "")
                elif label.lower() == "rep label":
                    rep = comp.get("valueString", "")
                elif label.lower() == "value index":
                    val_index = comp.get("valueInteger", 0)

            if not muscle or not rep or val_index == 0:
                continue

            unique_muscles.add(muscle)
            raw_value = obs.get("valueQuantity", {}).get("value", 0.0)

            if rep not in individual_reps: individual_reps[rep] = {}
            if muscle not in individual_reps[rep]: individual_reps[rep][muscle] = []

            target_list = individual_reps[rep][muscle]
            while len(target_list) < val_index:
                target_list.append(0.0)
            
            target_list[val_index - 1] = float(raw_value)

        test_records.append(ExerciseRecord(
            user_id=user_id,
            total_muscles=len(unique_muscles),
            device_name=device_name,
            date=date,
            individual_reps=individual_reps
        ))

    return test_records

# --- Background Task ---
async def run_single_index_migration(target_index: int):
    try:
        # 0. Fetch the legacy document
        cursor = test_data_collection.find().skip(target_index - 1).limit(1)
        docs = await cursor.to_list(length=1)
        
        if not docs:
            print(f"Index {target_index} not found.")
            return

        # 1. Split the bundle into individual ExerciseRecord objects
        test_records = parse_bundle_to_multiple_records(docs[0])
        if not test_records:
            return

        # 2. User ID Logic: Lookup the patient to get the internal UUID
        # (Assuming all records in this legacy bundle belong to the same user)
        user_id = test_records[0].user_id
        patient_record = await patient_data_collection.find_one({
            "entry": {
                "$elemMatch": {
                    "resource.resourceType": "Observation",
                    "resource.code.text": "User Id",
                    "resource.valueString": user_id
                }
            }
        })

        if not patient_record:
            print(f"Migration Error: Patient '{user_id}' not found. Skipping.")
            return

        # Extract patient_uuid for the subject reference
        patient_uuid = None
        for entry in patient_record.get("entry", []):
            res = entry.get("resource", {})
            if res.get("resourceType") == "Patient":
                patient_uuid = res.get("id")
                break

        # 3. For each test record, generate a NEW standalone FHIR Bundle
        for record in test_records:
            # Generate the observation entries from the record
            temp_bundle = generate_minimal_fhir_upload(record)
            new_entries = temp_bundle["entry"]

            # Define the required User Id header observation for this specific test document
            user_id_entry = {
                "resource": {
                    "resourceType": "Observation",
                    "status": "final",
                    "code": {"text": "User Id"},
                    "valueString": user_id,
                    "subject": {"reference": f"Patient/{patient_uuid}"}
                }
            }
            
            # Combine into a single new Bundle document
            full_bundle = {
                "resourceType": "Bundle",
                "type": "transaction",
                "entry": [user_id_entry] + new_entries
            }

            # Insert as a new document (Every test creates a new doc)
            await testing_data.insert_one(full_bundle)
        
        # 4. Update Flag to "1" in patient_data_collection (Logic from your Upload API)
        await patient_data_collection.update_one(
            {
                "_id": patient_record["_id"],
                "entry.resource.code.text": "Flag"
            },
            {"$set": {"entry.$[flagEntry].resource.valueString": "1"}},
            array_filters=[{"flagEntry.resource.code.text": "Flag"}]
        )

        print(f"Successfully migrated index {target_index}. Saved {len(test_records)} individual test bundles for {user_id}.")

    except Exception as e:
        print(f"Error during migration: {str(e)}")

# --- API Endpoint ---
@app.post("/convert-single-record/{target}")
async def start_conversion(target: int, background_tasks: BackgroundTasks):
    """
    Triggers migration for the document index specified in the URL.
    """
    # The value you type in the Swagger text box is passed here
    background_tasks.add_task(run_single_index_migration, target)
    
    return {
        "status": "Migration Queued", 
        "target_index": target
    }

@app.get("/therapist/{therapist_email}/all-patients-exercise-data")
async def get_all_patients_exercise_data(therapist_email: str):
    try:
        # Step 1: Find all patient profiles assigned to this therapist (1 Query)
        patient_cursor = patient_data_collection.find({
            "entry": {
                "$elemMatch": {
                    "resource.resourceType": "Observation",
                    "resource.code.text": "Therapist Assigned",
                    "resource.valueString": therapist_email
                }
            }
        })
        
        assigned_patients = await patient_cursor.to_list(length=None)
        
        if not assigned_patients:
            return JSONResponse(content={"message": "No patients found for this therapist", "data": []})

        # Step 2: Extract User Ids into a list
        user_ids = []
        for patient in assigned_patients:
            for entry in patient.get("entry", []):
                resource = entry.get("resource", {})
                if resource.get("resourceType") == "Observation" and resource.get("code", {}).get("text") == "User Id":
                    user_ids.append(resource.get("valueString"))
                    break

        if not user_ids:
            return JSONResponse(content={"therapist_email": therapist_email, "data": []})

        # Step 3: BATCH FETCH - Get ALL exercise data for ALL users in ONE query
        exercise_cursor = testing_data.find({
            "entry": {
                "$elemMatch": {
                    "resource.resourceType": "Observation",
                    "resource.code.text": "User Id",
                    "resource.valueString": {"$in": user_ids}  # <--- The magic happens here
                }
            }
        })
        
        all_patient_exercise_bundles = await exercise_cursor.to_list(length=None)

        # Step 4: DATA STRUCTURE - Group data in-memory using a Hash Map (Dictionary)
        # defaultdict(list) creates a new list automatically if a key doesn't exist yet
        grouped_data = defaultdict(list)
        
        for bundle in all_patient_exercise_bundles:
            # Fix ObjectId for JSON serialization
            if "_id" in bundle:
                bundle["_id"] = str(bundle["_id"])
                
            # Extract the user_id from this specific bundle to use as the dictionary key
            bundle_user_id = None
            for entry in bundle.get("entry", []):
                res = entry.get("resource", {})
                if res.get("resourceType") == "Observation" and res.get("code", {}).get("text") == "User Id":
                    bundle_user_id = res.get("valueString")
                    break
            
            # Map the bundle to the correct user in O(1) time
            if bundle_user_id:
                grouped_data[bundle_user_id].append(bundle)

        # Step 5: Format the final response
        final_response_data = []
        for user_id in user_ids:
            # If a user has no data, grouped_data[user_id] will safely return an empty []
            user_bundles = grouped_data[user_id] 
            final_response_data.append({
                "user_id": user_id,
                "total_records": len(user_bundles),
                "exercise_data": user_bundles
            })

        return JSONResponse(content={
            "therapist_email": therapist_email,
            "data": final_response_data
        })

    except Exception as e:
        print(f"Error fetching aggregated patient data: {e}")
        raise HTTPException(status_code=500, detail="Internal Server Error while fetching patient data")