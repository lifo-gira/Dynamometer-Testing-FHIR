from motor import motor_asyncio
from uuid import uuid4
from datetime import datetime
from typing import List, Dict, Optional
from pydantic import BaseModel, EmailStr
import pytz
from datetime import datetime
from uuid import uuid4
from pytz import timezone
from fastapi import HTTPException
from models import PatientData, Therapist

IST = pytz.timezone("Asia/Kolkata")


# MongoDB setup
client = motor_asyncio.AsyncIOMotorClient("mongodb+srv://dynamometerXO:dynamometerXO@cluster0.n6f8six.mongodb.net/?retryWrites=true&w=majority&appName=Cluster0")
database = client.Main
user_collection = database.User 
patient_data_collection = database.PatientData 
therapist_data_collection = database.Therapist
test_data_collection = database.Reports

license = motor_asyncio.AsyncIOMotorClient("mongodb+srv://Ronald:Ronaldshaw068@cluster0.2w6n7hi.mongodb.net/?retryWrites=true&w=majority&appName=Cluster0")
database2 = license.production
devices = database2.licensed_devices
logging = database2.device_log

IST = timezone("Asia/Kolkata")

def generate_fhir_patient_bundle(patient: PatientData) -> dict:
    now = datetime.now(IST).replace(microsecond=0).isoformat()

    try:
        birth_date = (
            datetime.strptime(patient.dob, "%d-%m-%Y").date().isoformat()
            if patient.dob else "unknown"
        )
    except ValueError:
        raise HTTPException(status_code=400, detail="DOB must be in 'DD-MM-YYYY' format")

    patient_uuid = str(uuid4()).lower()

    bundle = {
        "resourceType": "Bundle",
        "type": "collection",
        "entry": []
    }

    # Add Patient Resource
    bundle["entry"].append({
        "fullUrl": f"urn:uuid:{patient_uuid}",
        "resource": {
            "resourceType": "Patient",
            "id": patient_uuid,
            "text": {
                "status": "generated",
                "div": f"<div xmlns=\"http://www.w3.org/1999/xhtml\">Patient record for {patient.first_name} {patient.last_name}</div>"
            },
            "name": [{
                "family": patient.last_name,
                "given": [patient.first_name]
            }],
            "gender": patient.gender or "unknown",
            "birthDate": birth_date
        }
    })

    def add_observation(display_text: str, code_text: str, value, value_type="valueString"):
        obs_id = str(uuid4()).lower()
        resource = {
            "resourceType": "Observation",
            "id": obs_id,
            "text": {
                "status": "generated",
                "div": f"<div xmlns=\"http://www.w3.org/1999/xhtml\">{display_text} Observation</div>"
            },
            "status": "final",
            "code": {"text": code_text},
            "subject": {"reference": f"urn:uuid:{patient_uuid}"},
            "effectiveDateTime": now,
            "performer": [{"display": "System Auto"}]
        }

        if value_type == "valueQuantity":
            resource["valueQuantity"] = value
        else:
            resource["valueString"] = value

        bundle["entry"].append({
            "fullUrl": f"urn:uuid:{obs_id}",
            "resource": resource
        })

    # Add all observations from PatientData
    add_observation("User ID", "User Id", patient.user_id)
    add_observation("Therapist Assigned", "Therapist Assigned", patient.therapist_assigned)
    if patient.username:
        add_observation("Username", "Username", patient.username)
    add_observation("Email", "Email", patient.email)
    add_observation("Phone Number", "Phone Number", patient.phone_number)
    if patient.blood_grp:
        add_observation("Blood Group", "Blood Group", patient.blood_grp)
    add_observation("Flag", "Flag", str(patient.flag))
    if patient.height is not None:
        add_observation("Height", "Height (cm)", {
            "value": patient.height,
            "unit": "cm",
            "system": "http://unitsofmeasure.org",
            "code": "cm"
        }, value_type="valueQuantity")
    if patient.weight is not None:
        add_observation("Weight", "Weight (kg)", {
            "value": patient.weight,
            "unit": "kg",
            "system": "http://unitsofmeasure.org",
            "code": "kg"
        }, value_type="valueQuantity")
    return bundle

def generate_fhir_therapist_bundle(therapist: Therapist) -> dict:
    practitioner_uuid = str(uuid4()).lower()

    # Validate DOB strictly
    if not therapist.dob:
        raise ValueError("DOB is required for FHIR Practitioner")

    try:
        birth_date = datetime.strptime(therapist.dob, "%Y-%m-%d").date().isoformat()
    except ValueError:
        raise ValueError(f"Invalid DOB format: {therapist.dob}. Expected YYYY-MM-DD.")

    bundle = {
        "resourceType": "Bundle",
        "type": "collection",
        "entry": [
            {
                "fullUrl": f"urn:uuid:{practitioner_uuid}",
                "resource": {
                    "resourceType": "Practitioner",
                    "id": practitioner_uuid,
                    "text": {
                        "status": "generated",
                        "div": f"<div xmlns='http://www.w3.org/1999/xhtml'>Practitioner record for {therapist.email}</div>"
                    },
                    "name": [
                        {
                            "text": therapist.username
                        }
                    ],
                    "telecom": [
                        {
                            "system": "email",
                            "value": therapist.email
                        }
                    ],
                    "birthDate": birth_date,
                    "qualification": [
                        {
                            "code": {
                                "text": "Therapist"
                            }
                        }
                    ]
                }
            }
        ]
    }

    if therapist.profile_image:
        bundle["entry"][0]["resource"]["photo"] = [
            {
                "contentType": "image/jpeg",
                "url": therapist.profile_image
            }
        ]

    return bundle

# def generate_fhir_exercise_bundle(user_id: str, patient_uuid: str, exercise_records: list, include_patient: bool = True) -> dict:
#     now = datetime.now(IST).replace(microsecond=0).isoformat()
#     patient_ref = f"urn:uuid:{patient_uuid}"

#     bundle = {
#         "resourceType": "Bundle",
#         "type": "collection",
#         "entry": []
#     }

#     if include_patient:
#         # Add Patient Resource
#         bundle["entry"].append({
#             "fullUrl": patient_ref,
#             "resource": {
#                 "resourceType": "Patient",
#                 "id": patient_uuid,
#                 "text": {
#                     "status": "generated",
#                     "div": f"<div xmlns=\"http://www.w3.org/1999/xhtml\">Patient reference for user ID {user_id}</div>"
#                 }
#             }
#         })

#         # Add User ID Observation
#         user_id_obs_id = str(uuid4())
#         bundle["entry"].append({
#             "fullUrl": f"urn:uuid:{user_id_obs_id}",
#             "resource": {
#                 "resourceType": "Observation",
#                 "id": user_id_obs_id,
#                 "text": {
#                     "status": "generated",
#                     "div": "<div xmlns=\"http://www.w3.org/1999/xhtml\">User ID Observation</div>"
#                 },
#                 "status": "final",
#                 "code": {"text": "User Id"},
#                 "subject": {"reference": patient_ref},
#                 "effectiveDateTime": now,
#                 "performer": [{"display": "System Auto"}],
#                 "valueString": user_id
#             }
#         })

#     # Add each exercise test (numbered)
#     for idx, record in enumerate(exercise_records):
#         test_number = idx + 1  # Test 1, Test 2, ...
#         device_name = record["device_name"]
#         record_date = record["date"]
#         reps = record["individual_reps"]

#         all_observation_refs = []

#         # Collect all observations from all reps
#         for rep_label, muscles in reps.items():
#             for muscle, values in muscles.items():
#                 obs_id = str(uuid4())
#                 observation = {
#                     "resourceType": "Observation",
#                     "id": obs_id,
#                     "text": {
#                         "status": "generated",
#                         "div": f"<div xmlns=\"http://www.w3.org/1999/xhtml\">{device_name} - {rep_label} - {muscle} Observation</div>"
#                     },
#                     "status": "final",
#                     "code": {
#                         "text": f"{device_name} - {rep_label} - {muscle}"
#                     },
#                     "subject": {
#                         "reference": patient_ref
#                     },
#                     "effectiveDateTime": f"{record_date}T00:00:00+05:30",
#                     "performer": [{"display": "System Auto"}],
#                     "valueSampledData": {
#                         "origin": {
#                             "value": 0,
#                             "unit": "kgf",
#                             "system": "http://unitsofmeasure.org",
#                             "code": "kgf"
#                         },
#                         "interval": 50,
#                         "intervalUnit": "ms",
#                         "dimensions": 1,
#                         "data": " ".join(map(str, values))
#                     }
#                 }

#                 bundle["entry"].append({
#                     "fullUrl": f"urn:uuid:{obs_id}",
#                     "resource": observation
#                 })
#                 all_observation_refs.append({"reference": f"urn:uuid:{obs_id}"})

#         # Create DiagnosticReport for this test
#         diag_id = str(uuid4())
#         diagnostic_report = {
#             "resourceType": "DiagnosticReport",
#             "id": diag_id,
#             "status": "final",
#             "code": {
#                 "text": f"Test {test_number} - {device_name} Exercise Test Report"
#             },
#             "subject": {
#                 "reference": patient_ref
#             },
#             "effectiveDateTime": f"{record_date}T00:00:00+05:30",
#             "issued": now,
#             "result": all_observation_refs,
#             "performer": [{"display": "System Auto"}],
#             "text": {
#                 "status": "generated",
#                 "div": f"<div xmlns=\"http://www.w3.org/1999/xhtml\">Full Exercise Report for {device_name} (Test {test_number})</div>"
#             },
#             "identifier": [
#   {
#     "system": "http://yourdomain.org/test-id",
#     "value": f"Test-{test_number}"
#   }
# ]

#         }

#         bundle["entry"].append({
#             "fullUrl": f"urn:uuid:{diag_id}",
#             "resource": diagnostic_report
#         })

#     return bundle

def generate_fhir_exercise_bundle(user_id: str, patient_uuid: str, exercise_records: list, include_patient: bool = True) -> dict:
    now = datetime.now(IST).replace(microsecond=0).isoformat()
    patient_ref = f"urn:uuid:{patient_uuid}"

    bundle = {
        "resourceType": "Bundle",
        "type": "collection",
        "entry": []
    }

    if include_patient:
        # Add Patient Resource
        bundle["entry"].append({
            "fullUrl": patient_ref,
            "resource": {
                "resourceType": "Patient",
                "id": patient_uuid,
                "text": {
                    "status": "generated",
                    "div": f"<div xmlns=\"http://www.w3.org/1999/xhtml\">Patient reference for user ID {user_id}</div>"
                }
            }
        })

        # Add User ID Observation
        user_id_obs_id = str(uuid4())
        bundle["entry"].append({
            "fullUrl": f"urn:uuid:{user_id_obs_id}",
            "resource": {
                "resourceType": "Observation",
                "id": user_id_obs_id,
                "text": {
                    "status": "generated",
                    "div": "<div xmlns=\"http://www.w3.org/1999/xhtml\">User ID Observation</div>"
                },
                "status": "final",
                "code": {"text": "User Id"},
                "subject": {"reference": patient_ref},
                "effectiveDateTime": now,
                "performer": [{"display": "System Auto"}],
                "valueString": user_id
            }
        })

    # Add each exercise test (numbered)
    for idx, record in enumerate(exercise_records):
        test_number = idx + 1
        device_name = record["device_name"]
        record_date = record["date"]
        record_date_obj = datetime.strptime(record_date, "%d-%m-%Y")
        record_date_iso = record_date_obj.date().isoformat()
        reps = record["individual_reps"]

        all_observation_refs = []

        for rep_label, muscles in reps.items():
            for muscle, values in muscles.items():
                for i, value in enumerate(values):
                    obs_id = str(uuid4())

                    observation = {
                        "resourceType": "Observation",
                        "id": obs_id,
                        "status": "final",
                        "code": {
                            "text": f"{device_name} - {muscle} - {rep_label}"
                        },
                        "subject": {
                            "reference": patient_ref
                        },
                        "effectiveDateTime": f"{record_date_iso}T00:00:00+05:30",
                        "performer": [{"display": "System Auto"}],
                        "valueQuantity": {
                            "value": value,
                            "unit": "kgf",
                            "system": "http://unitsofmeasure.org",
                            "code": "kgf"
                        },
                        "component": [
                            {
                                "code": {"text": "Muscle Group"},
                                "valueCodeableConcept": {"text": muscle}
                            },
                            {
                                "code": {"text": "Rep Label"},
                                "valueString": rep_label
                            },
                            {
                                "code": {"text": "Device Used"},
                                "valueString": device_name
                            },
                            {
                                "code": {"text": "Value Index"},
                                "valueInteger": i + 1
                            }
                        ],
                        "text": {
                            "status": "generated",
                            "div": f"<div xmlns=\"http://www.w3.org/1999/xhtml\">{device_name} - {rep_label} - {muscle} - Value {i + 1}</div>"
                        }
                    }

                    bundle["entry"].append({
                        "fullUrl": f"urn:uuid:{obs_id}",
                        "resource": observation
                    })
                    all_observation_refs.append({"reference": f"urn:uuid:{obs_id}"})

        # Create DiagnosticReport
        diag_id = str(uuid4())
        diagnostic_report = {
            "resourceType": "DiagnosticReport",
            "id": diag_id,
            "status": "final",
            "code": {
                "text": f"Test {test_number} - {device_name} Exercise Test Report"
            },
            "subject": {
                "reference": patient_ref
            },
            "effectiveDateTime": f"{record_date_iso}T00:00:00+05:30",
            "issued": now,
            "result": all_observation_refs,
            "performer": [{"display": "System Auto"}],
            "text": {
                "status": "generated",
                "div": f"<div xmlns=\"http://www.w3.org/1999/xhtml\">Full Exercise Report for {device_name} (Test {test_number})</div>"
            },
            "identifier": [
                {
                    "system": "http://yourdomain.org/test-id",
                    "value": f"Test-{test_number}"
                }
            ]
        }

        bundle["entry"].append({
            "fullUrl": f"urn:uuid:{diag_id}",
            "resource": diagnostic_report
        })

    return bundle


async def get_user_ids_for_therapist(therapist_email: str):
    user_ids = []

    bundles = await patient_data_collection.find({"resourceType": "Bundle"}).to_list(length=None)
    for bundle in bundles:  # ✅ CORRECT
        entries = bundle.get("entry", [])
        user_id = None
        therapist_assigned = None

        for entry in entries:
            resource = entry.get("resource", {})
            if resource.get("resourceType") == "Observation":
                code = resource.get("code", {}).get("text", "")
                value = resource.get("valueString", "")
                if code == "User Id":
                    user_id = value
                elif code == "Therapist Assigned":
                    therapist_assigned = value

        if user_id and therapist_assigned == therapist_email:
            user_ids.append(user_id)

    return user_ids