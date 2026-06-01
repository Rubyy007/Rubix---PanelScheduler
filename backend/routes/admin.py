import logging
from datetime import datetime
from typing import List, Dict, Any, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field

from backend.models import Booking, BookingStatus, SystemConfig, AuditLog, AuditAction, MovePanelPayload, DisablePanelPayload
from backend.sheets_service import SheetsService, SHEET_TRANSACTION_LOCK
from backend.config_manager import ConfigManager
from backend.validation_engine import get_all_slots
from backend.panel_grid_generator import generate_grid_for_date, generate_and_update_grid
from backend.audit_logger import create_audit_log_record

router = APIRouter(prefix="/admin", tags=["admin"])
logger = logging.getLogger("routes.admin")

# Dependency injection helpers
def get_sheets_service() -> SheetsService:
    service = SheetsService()
    if not service.spreadsheet:
        service.connect_spreadsheet()
    return service

def get_config_manager(sheets_service: SheetsService = Depends(get_sheets_service)) -> ConfigManager:
    return ConfigManager(sheets_service)


# --- RESPONSE SCHEMAS ---

class DashboardSummary(BaseModel):
    date: str
    stats: Dict[str, int]
    panel_grid_headers: List[str]
    panel_grid_rows: List[List[str]]
    bookings: List[Booking]
    config: SystemConfig
    recent_logs: List[AuditLog]


# --- ROUTE HANDLERS ---

@router.get("/dashboard", response_model=DashboardSummary)
async def get_dashboard_summary(
    date: Optional[str] = Query(None, description="Select date for grid (YYYY-MM-DD)"),
    sheets_service: SheetsService = Depends(get_sheets_service),
    config_manager: ConfigManager = Depends(get_config_manager)
):
    """
    Returns a unified dashboard response containing statistics, a real-time
    panel grid for the selected date, recent bookings, configuration, and audit logs.
    """
    bookings = sheets_service.get_all_bookings()
    config = config_manager.get_config()
    logs = sheets_service.get_audit_logs()
    
    # Default to current date if not specified
    target_date = date or datetime.now().strftime("%Y-%m-%d")
    
    # 1. Generate visual grid rows for the dashboard
    headers, rows = generate_grid_for_date(bookings, config, target_date)
    
    # 2. Calculate general statistics
    stats = {
        "total": len(bookings),
        "booked": len([b for b in bookings if b.status == BookingStatus.BOOKED]),
        "waitlisted": len([b for b in bookings if b.status == BookingStatus.WAITLISTED]),
        "cancelled": len([b for b in bookings if b.status == BookingStatus.CANCELLED]),
        "completed": len([b for b in bookings if b.status == BookingStatus.COMPLETED]),
        "noshow": len([b for b in bookings if b.status == BookingStatus.NO_SHOW]),
        "rescheduled": len([b for b in bookings if b.status == BookingStatus.RESCHEDULED])
    }
    
    return DashboardSummary(
        date=target_date,
        stats=stats,
        panel_grid_headers=headers,
        panel_grid_rows=rows,
        bookings=bookings,
        config=config,
        recent_logs=logs[:20]  # Return top 20 latest logs
    )


@router.get("/panels")
async def get_panels_list(
    sheets_service: SheetsService = Depends(get_sheets_service),
    config_manager: ConfigManager = Depends(get_config_manager)
):
    """Retrieves list of all panels, their state (enabled/disabled), and active allocation count."""
    config = config_manager.get_config()
    bookings = sheets_service.get_all_bookings()
    
    active_bookings = [b for b in bookings if b.status == BookingStatus.BOOKED]
    
    panels_info = []
    for panel_name, enabled in config.panel_enabled_flags.items():
        panel_allocations = len([b for b in active_bookings if b.allocated_panel == panel_name])
        panels_info.append({
            "panel_name": panel_name,
            "enabled": enabled,
            "allocation_count": panel_allocations
        })
        
    return panels_info


@router.post("/move-panel/{booking_id}", response_model=Booking)
async def manual_panel_override(
    booking_id: str,
    payload: MovePanelPayload,
    sheets_service: SheetsService = Depends(get_sheets_service),
    config_manager: ConfigManager = Depends(get_config_manager)
):
    """
    Performs an admin manual override, moving a booking from its current panel to another panel.
    Strictly checks that the target panel is enabled and fully available for the booking duration.
    """
    async with SHEET_TRANSACTION_LOCK:
        bookings = sheets_service.get_all_bookings()
        config = config_manager.get_config()
        
        # 1. Locate the booking
        target_booking = None
        for b in bookings:
            if b.booking_id == booking_id:
                target_booking = b
                break
                
        if not target_booking:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Booking with ID {booking_id} not found."
            )
            
        if target_booking.status != BookingStatus.BOOKED:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Only active BOOKED bookings can be moved. Current status: {target_booking.status}"
            )

        # 2. Check if target panel is valid and enabled
        target_panel = payload.target_panel
        if target_panel not in config.panel_enabled_flags:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Panel '{target_panel}' does not exist in configuration."
            )
            
        if not config.panel_enabled_flags[target_panel]:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Panel '{target_panel}' is currently disabled. Enable it before allocating bookings."
            )
            
        if target_booking.allocated_panel == target_panel:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Booking is already allocated to panel '{target_panel}'."
            )

        # 3. Check availability of the target panel
        requested_slots = get_all_slots(target_booking.start_time, target_booking.end_time, config.slot_duration)
        
        # Get active allocations for the target panel on this date (exclude current booking we are moving)
        other_active_bookings = [
            b for b in bookings 
            if b.booking_id != booking_id 
            and b.interview_date == target_booking.interview_date
            and b.status in (BookingStatus.BOOKED, BookingStatus.COMPLETED)
            and b.allocated_panel == target_panel
        ]
        
        occupied_slots = []
        for b in other_active_bookings:
            occupied_slots.extend(get_all_slots(b.start_time, b.end_time, config.slot_duration))
            
        # Check for intersection
        overlap = any(slot in occupied_slots for slot in requested_slots)
        if overlap:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Cannot move booking. Target panel '{target_panel}' is occupied during {target_booking.start_time} - {target_booking.end_time}."
            )
            
        # 4. Perform the move
        old_panel = target_booking.allocated_panel
        target_booking.allocated_panel = target_panel
        target_booking.modified_at = datetime.now().isoformat()
        target_booking.notes = (target_booking.notes or "") + f" [Moved from {old_panel} to {target_panel} at {target_booking.modified_at} by {payload.performed_by}]"
        
        # Save to Google Sheets
        sheets_service.save_bookings_batch(bookings)
        
        # Log the audit trail
        audit_log = create_audit_log_record(
            booking_id=booking_id,
            action=AuditAction.MOVE_PANEL,
            old_value=f"Panel: {old_panel}",
            new_value=f"Panel: {target_panel}",
            performed_by=payload.performed_by,
            reason=payload.reason
        )
        sheets_service.append_audit_log(audit_log)
        
        # Regenerate visual sheet grid
        generate_and_update_grid(bookings, config, sheets_service, target_booking.interview_date)
        
        return target_booking


@router.post("/disable-panel")
async def disable_or_enable_panel(
    payload: DisablePanelPayload,
    sheets_service: SheetsService = Depends(get_sheets_service),
    config_manager: ConfigManager = Depends(get_config_manager)
):
    """
    Enables or disables a panel.
    Updates the system configuration file in CONFIG and records an audit log.
    Already existing bookings on the disabled panel are untouched, but no new bookings will occupy it.
    """
    async with SHEET_TRANSACTION_LOCK:
        config = config_manager.get_config()
        panel_name = payload.panel_name
        
        if panel_name not in config.panel_enabled_flags:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Panel '{panel_name}' does not exist in configuration."
            )
            
        old_state = config.panel_enabled_flags[panel_name]
        new_state = not payload.disabled  # disabled=True means enabled=False
        
        if old_state == new_state:
            state_str = "disabled" if payload.disabled else "enabled"
            return {"message": f"Panel '{panel_name}' is already {state_str}."}
            
        # Update config state
        config.panel_enabled_flags[panel_name] = new_state
        success = config_manager.update_config(config)
        
        if not success:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to save disabled panel state to CONFIG worksheet."
            )
            
        # Log audit trail
        action_type = AuditAction.DISABLE_PANEL
        audit_log = create_audit_log_record(
            booking_id="SYSTEM",
            action=action_type,
            old_value=f"Panel: {panel_name}, Enabled: {old_state}",
            new_value=f"Panel: {panel_name}, Enabled: {new_state}",
            performed_by=payload.performed_by,
            reason=f"Action: {'DISABLE' if payload.disabled else 'ENABLE'}. Reason: {payload.reason}"
        )
        sheets_service.append_audit_log(audit_log)
        
        return {"message": f"Successfully {'disabled' if payload.disabled else 'enabled'} panel '{panel_name}'."}


@router.get("/audit", response_model=List[AuditLog])
async def get_all_audit_logs(
    sheets_service: SheetsService = Depends(get_sheets_service)
):
    """Fetch the chronological audit trail (newest first)."""
    return sheets_service.get_audit_logs()
