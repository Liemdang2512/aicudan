export type ReadingStatus =
  | "pending"
  | "needs_review"
  | "approved"
  | "rejected"

export type MeterType = "electric" | "water" | "unknown"

export type InvoiceSentStatus = "pending" | "sending" | "sent" | "failed"

export type NotificationJobStatus =
  | "queued"
  | "processing"
  | "completed"
  | "failed"

export interface BuildingContract {
  id: number
  owner_id: number
  name: string
  address: string | null
  is_active: boolean
  created_at: string
  room_count: number
}

export interface ReadingContract {
  id: number
  room_id: number | null
  reading_date: string
  meter_value: number | null
  meter_type: MeterType
  image_path: string | null
  confidence_score: number | null
  status: ReadingStatus
  notes: string | null
  batch_job_id: string | null
  created_at: string
  room_number: string | null
  resident_name: string | null
}

export interface FixedPriceConfig {
  price: number
  vat?: number
}

export interface PriceTier {
  min: number
  max: number | null
  price: number
  name?: string
}

export interface TieredPriceConfig {
  tiers: PriceTier[]
  vat: number
}

export interface PriceConfigContract {
  id: number
  config_name: string
  pricing_type: "fixed" | "tiered"
  config_json: string
  is_active: boolean
  is_default: boolean
  created_at: string
}

export interface InvoiceContract {
  id: number
  room_id: number
  invoice_month: string
  previous_reading: number
  current_reading: number
  consumption: number
  price_breakdown: string | null
  electricity_amount: number
  additional_fees: string | null
  total_amount: number
  sent_status: InvoiceSentStatus
  sent_at: string | null
  created_at: string
  room_number: string | null
  resident_name: string | null
}

export interface InvoiceGenerateRoomResultContract {
  room_id: number
  room_number: string
  status: "created" | "skipped" | "error"
  invoice_id: number | null
  detail: string
}

export interface InvoiceGenerateResponseContract {
  total_invoices: number
  total_amount: number
  invoices: InvoiceContract[]
  total_skipped: number
  total_errors: number
  results: InvoiceGenerateRoomResultContract[]
}

export interface DashboardStatsContract {
  total_rooms: number
  readings_done: number
  readings_pending: number
  readings_error: number
  total_invoices: number
  total_revenue: number
  current_month: string
}

export interface NotificationStatusContract {
  job_id: string
  status: NotificationJobStatus
  total: number
  processed: number
  sent: number
  failed: number
}

export interface NotificationSendBatchContract {
  job_id: string
  total: number
  status: "queued"
}
