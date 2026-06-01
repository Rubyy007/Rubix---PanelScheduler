import re
from datetime import datetime
from enum import Enum
from typing import Dict, Optional
from pydantic import BaseModel, Field, field_validator

# --- ENUMS ---

class BookingStatus(str, Enum):
    BOOKED = "BOOKED"
    WAITLISTED = "WAITLISTED"
    CANCELLED = "CANCELLED"
    COMPLETED = "COMPLETED"
    NO_SHOW = "NO_SHOW"
    RESCHEDULED = "RESCHEDULED"


class AuditAction(str, Enum):
    CREATE_BOOKING = "CREATE_BOOKING"
    CANCEL_BOOKING = "CANCEL_BOOKING"
    RESCHEDULE_BOOKING = "RESCHEDULE_BOOKING"
    COMPLETE_BOOKING = "COMPLETE_BOOKING"
    NOSHOW_BOOKING = "NOSHOW_BOOKING"
    MOVE_PANEL = "MOVE_PANEL"
    DISABLE_PANEL = "DISABLE_PANEL"
    AUTO_PROMOTE = "AUTO_PROMOTE"


# --- FIELD VALIDATORS ---

def validate_date_format(v: str) -> str:
    if not re.match(r"^\d{4}-\d{2}-\d{2}$", v):
        raise ValueError("Date must be in YYYY-MM-DD format")
    try:
        datetime.strptime(v, "%Y-%m-%d")
    except ValueError:
        raise ValueError("Invalid date value")
    return v


def validate_time_format(v: str) -> str:
    if not re.match(r"^\d{2}:\d{2}$", v):
        raise ValueError("Time must be in HH:MM format")
    try:
        datetime.strptime(v, "%H:%M")
    except ValueError:
        raise ValueError("Invalid time value")
    return v


# --- BOOKING MODELS ---

class Booking(BaseModel):
    booking_id: str = Field(..., alias="BookingID")
    created_at: str = Field(..., alias="CreatedAt")
    student_name: str = Field(..., alias="StudentName")
    company: str = Field(..., alias="Company")
    interview_date: str = Field(..., alias="InterviewDate")
    start_time: str = Field(..., alias="StartTime")
    end_time: str = Field(..., alias="EndTime")
    duration: int = Field(..., alias="Duration")
    allocated_panel: Optional[str] = Field(None, alias="AllocatedPanel")
    status: BookingStatus = Field(..., alias="Status")
    previous_booking_id: Optional[str] = Field(None, alias="PreviousBookingID")
    modified_at: Optional[str] = Field(None, alias="ModifiedAt")
    notes: Optional[str] = Field("", alias="Notes")

    model_config = {
        "populate_by_name": True,
        "use_enum_values": True
    }


class BookingCreate(BaseModel):
    student_name: str = Field(..., min_length=2, max_length=100)
    company: str = Field(..., min_length=1, max_length=100)
    interview_date: str
    start_time: str
    end_time: str
    notes: Optional[str] = ""

    @field_validator("interview_date")
    @classmethod
    def check_date(cls, v: str) -> str:
        return validate_date_format(v)

    @field_validator("start_time", "end_time")
    @classmethod
    def check_time(cls, v: str) -> str:
        return validate_time_format(v)


class BookingReschedule(BaseModel):
    interview_date: str
    start_time: str
    end_time: str
    notes: Optional[str] = ""

    @field_validator("interview_date")
    @classmethod
    def check_date(cls, v: str) -> str:
        return validate_date_format(v)

    @field_validator("start_time", "end_time")
    @classmethod
    def check_time(cls, v: str) -> str:
        return validate_time_format(v)


# --- SYSTEM CONFIG MODEL ---

class SystemConfig(BaseModel):
    working_hours_start: str = Field("09:00", description="HH:MM format start time")
    working_hours_end: str = Field("18:00", description="HH:MM format end time")
    slot_duration: int = Field(30, description="Duration of slot in minutes")
    max_duration: int = Field(120, description="Max allowed booking duration in minutes")
    min_duration: int = Field(30, description="Min allowed booking duration in minutes")
    auto_promote_waitlist: bool = Field(True, description="Automatically promote waitlist on cancellation")
    panel_enabled_flags: Dict[str, bool] = Field(
        default_factory=lambda: {"Panel-1": True, "Panel-2": True, "Panel-3": True},
        description="Dictionary mapping panel names to enabled boolean"
    )

    @field_validator("working_hours_start", "working_hours_end")
    @classmethod
    def check_time(cls, v: str) -> str:
        return validate_time_format(v)


# --- AUDIT LOG MODEL ---

class AuditLog(BaseModel):
    audit_id: str = Field(..., alias="AuditID")
    timestamp: str = Field(..., alias="Timestamp")
    action: AuditAction = Field(..., alias="Action")
    booking_id: str = Field(..., alias="BookingID")
    old_value: Optional[str] = Field(None, alias="OldValue")
    new_value: Optional[str] = Field(None, alias="NewValue")
    performed_by: str = Field(..., alias="PerformedBy")
    reason: Optional[str] = Field(None, alias="Reason")

    model_config = {
        "populate_by_name": True,
        "use_enum_values": True
    }


# --- ADMIN PAYLOADS ---

class MovePanelPayload(BaseModel):
    performed_by: str = Field("Admin", min_length=2)
    target_panel: str = Field(...)
    reason: str = Field(..., min_length=3)


class DisablePanelPayload(BaseModel):
    performed_by: str = Field("Admin", min_length=2)
    panel_name: str = Field(...)
    disabled: bool = Field(...)
    reason: str = Field(..., min_length=3)
