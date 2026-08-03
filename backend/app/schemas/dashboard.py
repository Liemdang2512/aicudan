from pydantic import BaseModel


class DashboardStats(BaseModel):
    total_buildings: int = 0
    total_rooms: int = 0
    readings_done: int = 0
    readings_pending: int = 0
    readings_error: int = 0
    total_invoices: int = 0
    total_revenue: float = 0
    current_month: str = ""


class ActivityItem(BaseModel):
    id: int
    type: str  # reading / invoice / notification
    description: str
    status: str
    created_at: str
