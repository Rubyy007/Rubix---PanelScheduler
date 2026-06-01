import uuid
from datetime import datetime
from backend.models import AuditLog, AuditAction

def create_audit_log_record(
    booking_id: str,
    action: AuditAction,
    old_value: str,
    new_value: str,
    performed_by: str,
    reason: str
) -> AuditLog:
    """Helper to instantiate a standard AuditLog schema with a unique ID and current timestamp."""
    return AuditLog(
        AuditID=f"AUD-{uuid.uuid4().hex[:6].upper()}",
        Timestamp=datetime.now().isoformat(),
        Action=action,
        BookingID=booking_id,
        OldValue=old_value,
        NewValue=new_value,
        PerformedBy=performed_by,
        Reason=reason
    )
