from datetime import datetime
from typing import List, Optional
from backend.models import Booking, BookingCreate, BookingStatus, SystemConfig

class ValidationError(Exception):
    def __init__(self, message: str):
        self.message = message
        super().__init__(self.message)


def parse_time(time_str: str) -> datetime:
    """Parse time string in HH:MM format."""
    return datetime.strptime(time_str, "%H:%M")


def parse_date(date_str: str) -> datetime:
    """Parse date string in YYYY-MM-DD format."""
    return datetime.strptime(date_str, "%Y-%m-%d")


def calculate_duration(start_time: str, end_time: str) -> int:
    """Calculate the duration in minutes between start and end times."""
    t_start = parse_time(start_time)
    t_end = parse_time(end_time)
    if t_end <= t_start:
        raise ValidationError("End time must be after start time.")
    delta = t_end - t_start
    return int(delta.total_seconds() / 60)


def is_30_minute_aligned(time_str: str) -> bool:
    """Check if the time string is aligned to a 30-minute interval (HH:00 or HH:30)."""
    t = parse_time(time_str)
    return t.minute in (0, 30)


def get_all_slots(start_time: str, end_time: str, slot_duration: int = 30) -> List[str]:
    """Get list of slot start times (e.g. ['11:00', '11:30']) for a booking."""
    from datetime import timedelta
    t_start = parse_time(start_time)
    t_end = parse_time(end_time)
    slots = []
    curr = t_start
    while curr < t_end:
        slots.append(curr.strftime("%H:%M"))
        curr += timedelta(minutes=slot_duration)
    return slots


def validate_booking_rules(
    booking_data: BookingCreate,
    config: SystemConfig,
    existing_bookings: List[Booking]
) -> None:
    """
    Validate standard booking business rules.
    Raises ValidationError if any business rule is violated.
    """
    # 1. Non-30-minute intervals
    if not is_30_minute_aligned(booking_data.start_time):
        raise ValidationError(f"Start time {booking_data.start_time} must be on a 30-minute interval (e.g. :00 or :30).")
    if not is_30_minute_aligned(booking_data.end_time):
        raise ValidationError(f"End time {booking_data.end_time} must be on a 30-minute interval (e.g. :00 or :30).")

    # 2. Duration calculations and range limits
    duration = calculate_duration(booking_data.start_time, booking_data.end_time)
    if duration < config.min_duration:
        raise ValidationError(f"Booking duration ({duration} minutes) is below minimum of {config.min_duration} minutes.")
    if duration > config.max_duration:
        raise ValidationError(f"Booking duration ({duration} minutes) exceeds maximum of {config.max_duration} minutes.")

    # 3. Inside working hours
    work_start = parse_time(config.working_hours_start)
    work_end = parse_time(config.working_hours_end)
    b_start = parse_time(booking_data.start_time)
    b_end = parse_time(booking_data.end_time)

    if b_start < work_start or b_start >= work_end:
        raise ValidationError(f"Booking start time {booking_data.start_time} is outside working hours ({config.working_hours_start} - {config.working_hours_end}).")
    if b_end > work_end or b_end <= work_start:
        raise ValidationError(f"Booking end time {booking_data.end_time} is outside working hours ({config.working_hours_start} - {config.working_hours_end}).")

    # 4. Future Date & Time Validation
    # Combine date and start time to verify it is in the future
    try:
        booking_dt = datetime.strptime(f"{booking_data.interview_date} {booking_data.start_time}", "%Y-%m-%d %H:%M")
        now = datetime.now()
        if booking_dt <= now:
            # For testing/demo convenience we might check date, but strictly speaking we enforce future booking
            raise ValidationError("Booking date and time must be in the future.")
    except Exception as e:
        if isinstance(e, ValidationError):
            raise e
        raise ValidationError("Invalid date or time format.")

    # 5. Duplicate Booking / Refresh Submission Prevention
    # Check if a student already has a pending/active booking on the exact same date & time
    for b in existing_bookings:
        if b.status in (BookingStatus.BOOKED, BookingStatus.WAITLISTED):
            if b.student_name.lower().strip() == booking_data.student_name.lower().strip():
                # Check for direct overlap of date
                if b.interview_date == booking_data.interview_date:
                    # check if time overlaps
                    b_s = parse_time(b.start_time)
                    b_e = parse_time(b.end_time)
                    if not (b_end <= b_s or b_start >= b_e):
                        raise ValidationError(
                            f"Duplicate booking detected. Student '{booking_data.student_name}' already has an active "
                            f"booking from {b.start_time} to {b.end_time} on {b.interview_date}."
                        )
