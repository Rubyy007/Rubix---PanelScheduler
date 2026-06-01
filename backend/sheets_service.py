import os
import json
import asyncio
import logging
from datetime import datetime
from typing import List, Optional, Tuple
import gspread
from google.oauth2.service_account import Credentials
from backend.models import Booking, BookingStatus, SystemConfig, AuditLog, AuditAction

# Setup logger
logger = logging.getLogger("sheets_service")
logging.basicConfig(level=logging.INFO)

# Thread/Async Lock to guarantee ACID-like transactions on Google Sheets operations
SHEET_TRANSACTION_LOCK = asyncio.Lock()

class SheetsService:
    def __init__(self):
        self.gc: Optional[gspread.Client] = None
        self.spreadsheet: Optional[gspread.Spreadsheet] = None
        self.credentials_path = os.path.join(os.path.dirname(__file__), "credentials.json")
        
        # Worksheets names
        self.WS_BOOKINGS = "MASTER_BOOKINGS"
        self.WS_PANEL_GRID = "PANEL_GRID"
        self.WS_CONFIG = "CONFIG"
        self.WS_AUDIT_LOG = "AUDIT_LOG"
        
        # Columns
        self.BOOKING_HEADERS = [
            "BookingID", "CreatedAt", "StudentName", "Company", "InterviewDate",
            "StartTime", "EndTime", "Duration", "AllocatedPanel", "Status",
            "PreviousBookingID", "ModifiedAt", "Notes"
        ]
        self.AUDIT_HEADERS = [
            "AuditID", "Timestamp", "Action", "BookingID", "OldValue",
            "NewValue", "PerformedBy", "Reason"
        ]
        self.CONFIG_HEADERS = ["Key", "Value"]

    def authenticate(self) -> bool:
        """Authenticate with Google Sheets API."""
        if self.gc is not None:
            return True
            
        scopes = [
            "https://www.googleapis.com/auth/spreadsheets",
            "https://www.googleapis.com/auth/drive"
        ]
        
        creds = None
        # 1. Try environment variable
        creds_json = os.environ.get("GOOGLE_SHEETS_CREDENTIALS")
        if creds_json:
            try:
                info = json.loads(creds_json)
                creds = Credentials.from_service_account_info(info, scopes=scopes)
                logger.info("Authenticated using GOOGLE_SHEETS_CREDENTIALS environment variable")
            except Exception as e:
                logger.error(f"Failed to parse credentials from environment: {e}")

        # 2. Try credentials.json file
        if not creds and os.path.exists(self.credentials_path):
            try:
                creds = Credentials.from_service_account_file(self.credentials_path, scopes=scopes)
                logger.info(f"Authenticated using service account key file: {self.credentials_path}")
            except Exception as e:
                logger.error(f"Failed to load credentials from file {self.credentials_path}: {e}")

        if not creds:
            logger.warning("No Google Sheets credentials found. Operations will fail until configured.")
            return False

        try:
            self.gc = gspread.authorize(creds)
            return True
        except Exception as e:
            logger.error(f"Failed to authorize gspread client: {e}")
            return False

    def connect_spreadsheet(self) -> bool:
        """Connect to the spreadsheet, creating it if it doesn't exist."""
        if not self.authenticate():
            return False
            
        spreadsheet_name = os.environ.get("GOOGLE_SPREADSHEET_NAME", "Mock Interview Panel Allocation System")
        spreadsheet_id = os.environ.get("GOOGLE_SPREADSHEET_ID")
        
        try:
            if spreadsheet_id:
                self.spreadsheet = self.gc.open_by_key(spreadsheet_id)
                logger.info(f"Opened existing spreadsheet by ID: {spreadsheet_id}")
            else:
                try:
                    self.spreadsheet = self.gc.open(spreadsheet_name)
                    logger.info(f"Opened existing spreadsheet by name: '{spreadsheet_name}'")
                except gspread.SpreadsheetNotFound:
                    logger.info(f"Spreadsheet '{spreadsheet_name}' not found. Creating a new one...")
                    self.spreadsheet = self.gc.create(spreadsheet_name)
                    logger.info(f"Created new spreadsheet. Share with your Service Account Email! Link: {self.spreadsheet.url}")
            
            # Ensure worksheets exist
            self._ensure_worksheets()
            return True
        except Exception as e:
            logger.error(f"Failed to connect to spreadsheet: {e}", exc_info=True)
            return False

    def _ensure_worksheets(self):
        """Checks and creates required worksheets if they are missing."""
        existing_worksheets = [ws.title for ws in self.spreadsheet.worksheets()]
        
        # MASTER_BOOKINGS
        if self.WS_BOOKINGS not in existing_worksheets:
            ws = self.spreadsheet.add_worksheet(title=self.WS_BOOKINGS, rows=1000, cols=len(self.BOOKING_HEADERS))
            ws.append_row(self.BOOKING_HEADERS)
            logger.info(f"Created worksheet '{self.WS_BOOKINGS}' with headers")
            
        # CONFIG
        if self.WS_CONFIG not in existing_worksheets:
            ws = self.spreadsheet.add_worksheet(title=self.WS_CONFIG, rows=100, cols=2)
            ws.append_row(self.CONFIG_HEADERS)
            # Default values
            default_config = [
                ["working_hours_start", "09:00"],
                ["working_hours_end", "18:00"],
                ["slot_duration", "30"],
                ["max_duration", "120"],
                ["min_duration", "30"],
                ["auto_promote_waitlist", "true"],
                ["panel_enabled_flags", '{"Panel-1": true, "Panel-2": true, "Panel-3": true}']
            ]
            ws.append_rows(default_config)
            logger.info(f"Created worksheet '{self.WS_CONFIG}' with default configuration")
            
        # AUDIT_LOG
        if self.WS_AUDIT_LOG not in existing_worksheets:
            ws = self.spreadsheet.add_worksheet(title=self.WS_AUDIT_LOG, rows=2000, cols=len(self.AUDIT_HEADERS))
            ws.append_row(self.AUDIT_HEADERS)
            logger.info(f"Created worksheet '{self.WS_AUDIT_LOG}' with headers")
            
        # PANEL_GRID
        if self.WS_PANEL_GRID not in existing_worksheets:
            # We will initialize it with time slots. Let's create it.
            ws = self.spreadsheet.add_worksheet(title=self.WS_PANEL_GRID, rows=50, cols=4)
            ws.append_row(["Time", "Panel-1", "Panel-2", "Panel-3"])
            logger.info(f"Created worksheet '{self.WS_PANEL_GRID}'")

    # --- BOOKING OPERATIONS ---

    def get_all_bookings(self) -> List[Booking]:
        """Fetch all bookings from Google Sheets."""
        if not self.spreadsheet:
            if not self.connect_spreadsheet():
                return []
        try:
            ws = self.spreadsheet.worksheet(self.WS_BOOKINGS)
            records = ws.get_all_records()
            bookings = []
            for r in records:
                try:
                    # Clean records
                    cleaned = {
                        "BookingID": str(r.get("BookingID", "")),
                        "CreatedAt": str(r.get("CreatedAt", "")),
                        "StudentName": str(r.get("StudentName", "")),
                        "Company": str(r.get("Company", "")),
                        "InterviewDate": str(r.get("InterviewDate", "")),
                        "StartTime": str(r.get("StartTime", "")),
                        "EndTime": str(r.get("EndTime", "")),
                        "Duration": int(r.get("Duration", 0)) if r.get("Duration") else 0,
                        "AllocatedPanel": str(r.get("AllocatedPanel", "")) if r.get("AllocatedPanel") else None,
                        "Status": str(r.get("Status", "BOOKED")),
                        "PreviousBookingID": str(r.get("PreviousBookingID", "")) if r.get("PreviousBookingID") else None,
                        "ModifiedAt": str(r.get("ModifiedAt", "")) if r.get("ModifiedAt") else None,
                        "Notes": str(r.get("Notes", ""))
                    }
                    bookings.append(Booking(**cleaned))
                except Exception as e:
                    logger.error(f"Error parsing booking row: {r}, error: {e}")
            return bookings
        except Exception as e:
            logger.error(f"Error fetching bookings from sheet: {e}")
            return []

    def save_bookings_batch(self, bookings: List[Booking]) -> bool:
        """Atomically overwrite the MASTER_BOOKINGS sheet with a new list of bookings."""
        if not self.spreadsheet:
            if not self.connect_spreadsheet():
                return False
        try:
            ws = self.spreadsheet.worksheet(self.WS_BOOKINGS)
            rows = [self.BOOKING_HEADERS] # Header row
            for b in bookings:
                dict_b = b.model_dump(by_alias=True)
                row = [
                    dict_b.get("BookingID", ""),
                    dict_b.get("CreatedAt", ""),
                    dict_b.get("StudentName", ""),
                    dict_b.get("Company", ""),
                    dict_b.get("InterviewDate", ""),
                    dict_b.get("StartTime", ""),
                    dict_b.get("EndTime", ""),
                    dict_b.get("Duration", 0),
                    dict_b.get("AllocatedPanel", "") or "",
                    dict_b.get("Status", "BOOKED"),
                    dict_b.get("PreviousBookingID", "") or "",
                    dict_b.get("ModifiedAt", "") or "",
                    dict_b.get("Notes", "") or ""
                ]
                rows.append(row)
            
            # Clear old and write all
            ws.clear()
            ws.update("A1", rows)
            logger.info(f"Successfully batch updated {len(bookings)} bookings in MASTER_BOOKINGS")
            return True
        except Exception as e:
            logger.error(f"Failed to batch update bookings: {e}")
            return False

    # --- CONFIG OPERATIONS ---

    def get_config(self) -> SystemConfig:
        """Fetch system configurations from CONFIG worksheet."""
        default_config = SystemConfig()
        if not self.spreadsheet:
            if not self.connect_spreadsheet():
                return default_config
        try:
            ws = self.spreadsheet.worksheet(self.WS_CONFIG)
            records = ws.get_all_records()
            config_dict = {}
            for r in records:
                key = r.get("Key")
                val = r.get("Value")
                if key:
                    config_dict[key] = val
            
            # Convert values to correct types
            kwargs = {}
            if "working_hours_start" in config_dict:
                kwargs["working_hours_start"] = str(config_dict["working_hours_start"])
            if "working_hours_end" in config_dict:
                kwargs["working_hours_end"] = str(config_dict["working_hours_end"])
            if "slot_duration" in config_dict:
                kwargs["slot_duration"] = int(config_dict["slot_duration"])
            if "max_duration" in config_dict:
                kwargs["max_duration"] = int(config_dict["max_duration"])
            if "min_duration" in config_dict:
                kwargs["min_duration"] = int(config_dict["min_duration"])
            if "auto_promote_waitlist" in config_dict:
                kwargs["auto_promote_waitlist"] = str(config_dict["auto_promote_waitlist"]).lower() in ("true", "1", "yes")
            if "panel_enabled_flags" in config_dict:
                try:
                    kwargs["panel_enabled_flags"] = json.loads(config_dict["panel_enabled_flags"])
                except Exception as ex:
                    logger.error(f"Failed to parse panel_enabled_flags JSON: {ex}")
            
            return SystemConfig(**kwargs)
        except Exception as e:
            logger.error(f"Error fetching config: {e}. Using system default.")
            return default_config

    def save_config(self, config: SystemConfig) -> bool:
        """Save configuration back to the CONFIG worksheet."""
        if not self.spreadsheet:
            if not self.connect_spreadsheet():
                return False
        try:
            ws = self.spreadsheet.worksheet(self.WS_CONFIG)
            rows = [
                self.CONFIG_HEADERS,
                ["working_hours_start", config.working_hours_start],
                ["working_hours_end", config.working_hours_end],
                ["slot_duration", str(config.slot_duration)],
                ["max_duration", str(config.max_duration)],
                ["min_duration", str(config.min_duration)],
                ["auto_promote_waitlist", "true" if config.auto_promote_waitlist else "false"],
                ["panel_enabled_flags", json.dumps(config.panel_enabled_flags)]
            ]
            ws.clear()
            ws.update("A1", rows)
            logger.info("Successfully saved system configuration to CONFIG worksheet")
            return True
        except Exception as e:
            logger.error(f"Error saving config: {e}")
            return False

    # --- AUDIT LOG OPERATIONS ---

    def append_audit_log(self, log: AuditLog) -> bool:
        """Appends a row to the AUDIT_LOG sheet."""
        if not self.spreadsheet:
            if not self.connect_spreadsheet():
                return False
        try:
            ws = self.spreadsheet.worksheet(self.WS_AUDIT_LOG)
            row = [
                log.audit_id,
                log.timestamp,
                log.action,
                log.booking_id,
                log.old_value or "",
                log.new_value or "",
                log.performed_by,
                log.reason or ""
            ]
            ws.append_row(row)
            logger.info(f"Logged audit: {log.action} for booking {log.booking_id}")
            return True
        except Exception as e:
            logger.error(f"Failed to log audit event: {e}")
            return False

    def get_audit_logs(self) -> List[AuditLog]:
        """Fetch all audit logs, sorted by timestamp descending."""
        if not self.spreadsheet:
            if not self.connect_spreadsheet():
                return []
        try:
            ws = self.spreadsheet.worksheet(self.WS_AUDIT_LOG)
            records = ws.get_all_records()
            logs = []
            for r in records:
                try:
                    cleaned = {
                        "AuditID": str(r.get("AuditID", "")),
                        "Timestamp": str(r.get("Timestamp", "")),
                        "Action": str(r.get("Action", "")),
                        "BookingID": str(r.get("BookingID", "")),
                        "OldValue": str(r.get("OldValue", "")) if r.get("OldValue") else None,
                        "NewValue": str(r.get("NewValue", "")) if r.get("NewValue") else None,
                        "PerformedBy": str(r.get("PerformedBy", "")),
                        "Reason": str(r.get("Reason", "")) if r.get("Reason") else None
                    }
                    logs.append(AuditLog(**cleaned))
                except Exception as ex:
                    logger.error(f"Error parsing audit log row: {r}, error: {ex}")
            logs.reverse() # Show newest first
            return logs
        except Exception as e:
            logger.error(f"Failed to fetch audit logs: {e}")
            return []

    # --- PANEL GRID OPERATIONS ---

    def update_panel_grid_sheet(self, headers: List[str], grid_rows: List[List[str]]) -> bool:
        """Atomically overwrite the PANEL_GRID sheet with a pre-calculated timetable."""
        if not self.spreadsheet:
            if not self.connect_spreadsheet():
                return False
        try:
            ws = self.spreadsheet.worksheet(self.WS_PANEL_GRID)
            ws.clear()
            all_rows = [headers] + grid_rows
            ws.update("A1", all_rows)
            logger.info("Successfully updated PANEL_GRID worksheet visual layout")
            return True
        except Exception as e:
            logger.error(f"Failed to update PANEL_GRID sheet: {e}")
            return False
