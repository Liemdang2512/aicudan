"use client"

import React, { useState, useEffect, useCallback, useRef } from "react"
import { useDropzone } from "react-dropzone"
import {
  Upload,
  CheckCircle2,
  Loader2,
  FileText,
  Send,
  Download,
  Sparkles,
  ArrowLeft,
  Pencil,
  Check,
  Eye,
  Printer,
  Bot,
} from "lucide-react"
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Badge } from "@/components/ui/badge"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogFooter,
} from "@/components/ui/dialog"
import { apiGet, apiPost, apiUpload, apiPatch, apiDownload } from "@/lib/api"
import { toast } from "@/components/ui/use-toast"
import type {
  InvoiceGenerateResponseContract,
  InvoiceSentStatus,
  NotificationSendBatchContract,
  NotificationStatusContract,
} from "@/lib/types"

const NOTIFICATION_POLL_INTERVAL_MS = 1000
const NOTIFICATION_POLL_TIMEOUT_MS = 60_000
const BATCH_POLL_INTERVAL_MS = 2000
const BATCH_POLL_TIMEOUT_MS = 90_000
const INVOICE_LIST_LIMIT = 200

const waitForNextPoll = (delay: number, signal: AbortSignal) =>
  new Promise<void>((resolve, reject) => {
    const onAbort = () => {
      window.clearTimeout(timeoutId)
      reject(new DOMException("Polling cancelled", "AbortError"))
    }
    const timeoutId = window.setTimeout(() => {
      signal.removeEventListener("abort", onAbort)
      resolve()
    }, delay)
    signal.addEventListener("abort", onAbort, { once: true })
  })

const waitForNotificationJob = async (
  jobId: string,
  onUpdate: (status: NotificationStatusContract) => void,
  signal: AbortSignal
): Promise<NotificationStatusContract> => {
  const deadline = Date.now() + NOTIFICATION_POLL_TIMEOUT_MS
  while (!signal.aborted && Date.now() < deadline) {
    const status = await apiGet<NotificationStatusContract>(
      `/notifications/status/${jobId}`
    )
    if (signal.aborted) throw new DOMException("Polling cancelled", "AbortError")
    onUpdate(status)
    if (status.status === "completed" || status.status === "failed") {
      return status
    }
    await waitForNextPoll(NOTIFICATION_POLL_INTERVAL_MS, signal)
  }
  if (signal.aborted) throw new DOMException("Polling cancelled", "AbortError")
  throw new Error("Quá thời gian chờ kết quả gửi. Kiểm tra lại trạng thái hóa đơn.")
}

interface Building {
  id: number
  name: string
  address: string | null
  room_count: number
}

interface PriceConfig {
  id: number
  config_name: string
  pricing_type: string
}
interface Room { id: number; room_number: string; resident_name?: string | null }

interface ReadingResult {
  id: number | null
  staged_id: string | null
  room_id: number | null
  room_number: string | null
  meter_value: number | null
  meter_type: "electric" | "water" | "unknown"
  confidence_score: number | null
  status: "success" | "error" | "pending" | "approved" | "needs_review"
  image_path: string | null
  notes?: string
  resident_name?: string
}

const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8001/api/v1"

function ProtectedReadingImage({ imagePath, alt }: { imagePath: string | null; alt: string }) {
  const [objectUrl, setObjectUrl] = useState<string | null>(null)

  useEffect(() => {
    let active = true
    let loadedUrl: string | null = null
    if (!imagePath || !imagePath.startsWith("/readings/")) {
      setObjectUrl(null)
      return
    }

    const token = localStorage.getItem("token")
    fetch(`${API_BASE_URL}${imagePath}`, {
      headers: token ? { Authorization: `Bearer ${token}` } : {},
    })
      .then((response) => {
        if (!response.ok) throw new Error("Không thể tải ảnh")
        return response.blob()
      })
      .then((blob) => {
        if (!active) return
        loadedUrl = URL.createObjectURL(blob)
        setObjectUrl(loadedUrl)
      })
      .catch(() => {
        if (active) setObjectUrl(null)
      })

    return () => {
      active = false
      if (loadedUrl) URL.revokeObjectURL(loadedUrl)
    }
  }, [imagePath])

  if (!objectUrl) {
    return <div className="flex h-full items-center justify-center text-xs text-muted-foreground">Không có ảnh</div>
  }
  return <img src={objectUrl} alt={alt} className="h-full w-full object-cover" />
}

interface BatchStatus {
  job_id: string
  status: "processing" | "completed" | "failed"
  progress: number
  total: number
  processed: number
  failed: number
  results: ReadingResult[]
}

interface PreviewFile {
  file: File
  preview: string
}

interface Invoice {
  id: number
  room_id?: number
  room_number?: string | null
  resident_name?: string | null
  tenant_name?: string
  building_name?: string
  invoice_month?: string
  month?: string
  previous_reading: number
  current_reading: number
  consumption: number
  electricity_amount?: number
  price_breakdown?: string | null
  additional_fees?: string | null
  total_amount: number
  sent_status?: InvoiceSentStatus
  status?: string
  created_at: string
}

export default function WorkflowPage() {
  const [currentStep, setCurrentStep] = useState<number>(1)
  const [buildings, setBuildings] = useState<Building[]>([])
  const [rooms, setRooms] = useState<Room[]>([])
  const [isLoadingRooms, setIsLoadingRooms] = useState(false)
  const [selectedBuilding, setSelectedBuilding] = useState<string>("")
  const [readingDate, setReadingDate] = useState<string>(
    new Date().toISOString().split("T")[0]
  )
  const [selectedPriceConfig, setSelectedPriceConfig] = useState<string>("")
  const [surcharge] = useState<string>("0")

  // Step 1 states
  const [files, setFiles] = useState<PreviewFile[]>([])
  const [isUploading, setIsUploading] = useState(false)
  const [batchStatus, setBatchStatus] = useState<BatchStatus | null>(null)

  // Step 2 states (editing result)
  const [editingResult, setEditingResult] = useState<ReadingResult | null>(null)
  const [editValue, setEditValue] = useState<string>("")
  const [editRoomId, setEditRoomId] = useState<string>("")
  const [showEditDialog, setShowEditDialog] = useState(false)

  // Step 3 & 4 states
  const [isGeneratingInvoices, setIsGeneratingInvoices] = useState(false)
  const [invoices, setInvoices] = useState<Invoice[]>([])
  const [selectedInvoiceForDetail, setSelectedInvoiceForDetail] = useState<Invoice | null>(null)
  const [isSendingTelegram, setIsSendingTelegram] = useState(false)
  const [notificationStatus, setNotificationStatus] =
    useState<NotificationStatusContract | null>(null)
  const batchAbortRef = useRef<AbortController | null>(null)
  const notificationAbortRef = useRef<AbortController | null>(null)

  const fetchBuildings = useCallback(async () => {
    try {
      const data = await apiGet<Building[]>("/buildings")
      setBuildings(data)
      if (data.length > 0) {
        const buildingWithRooms = data.find((building) => building.room_count > 0)
        setSelectedBuilding((buildingWithRooms ?? data[0]).id.toString())
      }
    } catch {}
  }, [])

  const fetchPriceConfigs = useCallback(async () => {
    try {
      const data = await apiGet<PriceConfig[]>("/price-configs")
      if (data.length > 0) {
        setSelectedPriceConfig(data[0].id.toString())
      }
    } catch {}
  }, [])

  useEffect(() => {
    fetchBuildings()
    fetchPriceConfigs()
  }, [fetchBuildings, fetchPriceConfigs])
  useEffect(() => {
    if (!selectedBuilding) {
      setRooms([])
      setIsLoadingRooms(false)
      return
    }
    setRooms([])
    setIsLoadingRooms(true)
    apiGet<Room[]>(`/buildings/${selectedBuilding}/rooms`)
      .then(setRooms)
      .catch(() => setRooms([]))
      .finally(() => setIsLoadingRooms(false))
  }, [selectedBuilding])
  useEffect(
    () => () => {
      batchAbortRef.current?.abort()
      notificationAbortRef.current?.abort()
    },
    []
  )

  // Dropzone logic
  const onDrop = useCallback((acceptedFiles: File[]) => {
    const newFiles: PreviewFile[] = acceptedFiles.map((file) => ({
      file,
      preview: URL.createObjectURL(file),
    }))
    setFiles((prev) => [...prev, ...newFiles])
  }, [])

  const { getRootProps, getInputProps, isDragActive } = useDropzone({
    onDrop,
    accept: { "image/*": [".jpeg", ".jpg", ".png", ".webp"] },
    multiple: true,
    disabled: isLoadingRooms || rooms.length === 0,
  })

  const reviewResults = batchStatus?.results ?? []
  // Chỉ đếm những reading CÓ THỂ approve (có room_id). Hình chưa gán phòng không tính vào pending.
  const pendingReviewCount = reviewResults.filter(
    (result) =>
      result.status !== "approved" &&
      (result.id != null ||
        (result.staged_id != null && result.room_id != null && result.meter_value !== null))
  ).length
  const canGenerateInvoices =
    reviewResults.length > 0 && pendingReviewCount === 0

  const removeFile = (index: number) => {
    setFiles((prev) => {
      const updated = [...prev]
      URL.revokeObjectURL(updated[index].preview)
      updated.splice(index, 1)
      return updated
    })
  }

  // Handle Step 1 Upload
  const handleUpload = async () => {
    if (!selectedBuilding) {
      toast({ title: "Thiếu thông tin", description: "Vui lòng chọn tòa nhà", variant: "destructive" })
      return
    }
    if (isLoadingRooms || rooms.length === 0) {
      toast({
        title: "Tòa nhà chưa có phòng",
        description: "Thêm phòng trước khi tải ảnh công tơ.",
        variant: "destructive",
      })
      return
    }
    if (files.length === 0) {
      toast({ title: "Thiếu ảnh", description: "Vui lòng kéo thả hoặc chọn ít nhất 1 ảnh", variant: "destructive" })
      return
    }

    setIsUploading(true)
    setBatchStatus(null)

    try {
      const formData = new FormData()
      formData.append("building_id", selectedBuilding)
      formData.append("reading_date", readingDate)
      files.forEach((f) => formData.append("files", f.file))

      const response = await apiUpload<{ job_id: string }>("/readings/batch-upload", formData)

      toast({ title: "Upload thành công", description: "AI Cư Dân đang phân tích ảnh...", variant: "success" })
      batchAbortRef.current?.abort()
      const controller = new AbortController()
      batchAbortRef.current = controller
      const status = await pollBatchStatus(response.job_id, controller.signal)
      setBatchStatus(status)
      setIsUploading(false)

      if (status.status === "failed") {
        toast({
          title: "Không xử lý được ảnh",
          description: `Đã xử lý ${status.processed}/${status.total} ảnh. Thử tải lại các ảnh lỗi.`,
          variant: "destructive",
        })
        return
      }

      toast({
        title: "Đã xử lý ảnh",
        description: `AI đã phân tích ${status.processed}/${status.total} ảnh.`,
        variant: "success",
      })
      setCurrentStep(2)
    } catch (error) {
      if (batchAbortRef.current?.signal.aborted) return
      setIsUploading(false)
      toast({
        title: "Không thể xử lý ảnh",
        description: error instanceof Error ? error.message : "Không thể upload ảnh",
        variant: "destructive",
      })
    }
  }

  const pollBatchStatus = async (
    jobId: string,
    signal: AbortSignal
  ): Promise<BatchStatus> => {
    const deadline = Date.now() + BATCH_POLL_TIMEOUT_MS
    while (!signal.aborted && Date.now() < deadline) {
      const status = await apiGet<BatchStatus>(`/readings/batch-status/${jobId}`)
      if (signal.aborted) throw new DOMException("Polling cancelled", "AbortError")
      setBatchStatus(status)
      if (status.status === "completed" || status.status === "failed") return status
      await waitForNextPoll(BATCH_POLL_INTERVAL_MS, signal)
    }
    if (signal.aborted) throw new DOMException("Polling cancelled", "AbortError")
    throw new Error("Quá thời gian xử lý ảnh. Kiểm tra kết nối rồi thử lại.")
  }

  // Step 2 Approve / Edit
  const handleApproveResult = async (resultId: number) => {
    try {
      const updated = await apiPatch<ReadingResult>(`/readings/${resultId}`, { status: "approved" })
      setBatchStatus((prev) => {
        if (!prev) return prev
        return {
          ...prev,
          results: prev.results.map((r) => (r.id === resultId ? updated : r)),
        }
      })
      toast({ title: "Đã xác nhận", description: "Chỉ số đã được xác nhận thành công", variant: "success" })
    } catch {
      toast({ title: "Lỗi", description: "Không thể xác nhận chỉ số", variant: "destructive" })
    }
  }

  const handleEditSave = async () => {
    if (!editingResult) return
    const meterValue = Number(editValue)
    if (!editRoomId || !Number.isInteger(meterValue) || meterValue < 0) return
    try {
      const endpoint = editingResult.staged_id ? `/readings/staged/${editingResult.staged_id}` : `/readings/${editingResult.id}`
      const updated = await apiPatch<ReadingResult>(endpoint, { room_id: Number(editRoomId), meter_value: meterValue, meter_type: "electric", status: "approved" })
      setBatchStatus((prev) => {
        if (!prev) return prev
        return {
          ...prev,
          results: prev.results.map((r) =>
            (editingResult.staged_id ? r.staged_id === editingResult.staged_id : r.id === editingResult.id) ? updated : r
          ),
        }
      })
      setShowEditDialog(false)
      toast({ title: "Cập nhật thành công", description: "Chỉ số phòng đã được lưu", variant: "success" })
    } catch {
      toast({ title: "Lỗi", description: "Không thể cập nhật chỉ số", variant: "destructive" })
    }
  }

  const [selectedResultIds, setSelectedResultIds] = useState<Set<number | string>>(new Set())
  const [isBatchApproving, setIsBatchApproving] = useState(false)
  const [approveConfirmDialog, setApproveConfirmDialog] = useState<{
    open: boolean
    unmatchedCount: number
    toApprove: ReadingResult[]
    successMsg: string
  } | null>(null)

  const toggleSelectResult = (idKey: number | string) => {
    setSelectedResultIds((prev) => {
      const next = new Set(prev)
      if (next.has(idKey)) {
        next.delete(idKey)
      } else {
        next.add(idKey)
      }
      return next
    })
  }

  const unapprovedResults = reviewResults.filter((r) => r.status !== "approved")
  const isAllSelected = unapprovedResults.length > 0 && unapprovedResults.every((r) => selectedResultIds.has(r.id ?? r.staged_id ?? ""))

  const handleSelectAllToggle = () => {
    if (isAllSelected) {
      setSelectedResultIds(new Set())
    } else {
      const allIds = unapprovedResults.map((r) => r.id ?? r.staged_id).filter(Boolean) as (number | string)[]
      setSelectedResultIds(new Set(allIds))
    }
  }

  const canApproveResult = (r: ReadingResult) =>
    r.id != null || (r.staged_id != null && r.room_id != null && r.meter_value !== null)

  const executeApproveList = async (list: ReadingResult[], successMsg: string) => {
    setIsBatchApproving(true)
    try {
      let count = 0
      for (const r of list) {
        if (r.id) {
          await apiPatch(`/readings/${r.id}`, { status: "approved" })
          count++
        } else if (r.staged_id && r.room_id && r.meter_value !== null) {
          await apiPatch(`/readings/staged/${r.staged_id}`, {
            room_id: r.room_id,
            meter_value: r.meter_value,
            status: "approved",
          })
          count++
        }
      }
      toast({ title: "Xác nhận thành công", description: successMsg.replace("{count}", String(count)), variant: "success" })
      setSelectedResultIds(new Set())
      if (batchStatus?.job_id) {
        const updatedStatus = await apiGet<BatchStatus>(`/readings/batch-status/${batchStatus.job_id}`)
        setBatchStatus(updatedStatus)
        // Nếu không còn reading nào cần approve → tự động sang bước 3
        const remainingPending = updatedStatus.results.filter(
          (r) =>
            r.status !== "approved" &&
            (r.id != null || (r.staged_id != null && r.room_id != null && r.meter_value !== null))
        ).length
        if (remainingPending === 0 && updatedStatus.results.length > 0) {
          handleGenerateInvoices(true)
        }
      }
    } catch {
      toast({ title: "Lỗi", description: "Không thể xác nhận một số phòng", variant: "destructive" })
    } finally {
      setIsBatchApproving(false)
    }
  }

  const handleApproveAll = () => {
    if (!batchStatus) return
    const toApprove = batchStatus.results.filter((r) => r.status !== "approved")
    if (toApprove.length === 0) return
    const unmatched = toApprove.filter((r) => !canApproveResult(r))
    if (unmatched.length > 0) {
      setApproveConfirmDialog({ open: true, unmatchedCount: unmatched.length, toApprove, successMsg: "Đã xác nhận {count} phòng (bỏ qua {skip} hình chưa gán phòng)." })
    } else {
      executeApproveList(toApprove, "Đã tự động xác nhận {count} phòng!")
    }
  }

  const handleApproveSelected = () => {
    if (!batchStatus || selectedResultIds.size === 0) return
    const toApprove = batchStatus.results.filter(
      (r) => r.status !== "approved" && selectedResultIds.has(r.id ?? r.staged_id ?? "")
    )
    const unmatched = toApprove.filter((r) => !canApproveResult(r))
    if (unmatched.length > 0) {
      setApproveConfirmDialog({ open: true, unmatchedCount: unmatched.length, toApprove, successMsg: "Đã xác nhận {count} phòng được chọn (bỏ qua {skip} hình chưa gán phòng)." })
    } else {
      executeApproveList(toApprove, "Đã xác nhận {count} phòng được chọn!")
    }
  }

  // Step 3 Generate Invoices
  const handleGenerateInvoices = async (force = false) => {
    if (!selectedBuilding || !selectedPriceConfig) {
      toast({ title: "Thiếu thông tin", description: "Vui lòng chọn Tòa nhà và Bảng giá", variant: "destructive" })
      return
    }
    if (!force && !canGenerateInvoices) {
      toast({
        title: "Chưa thể tạo hóa đơn",
        description:
          reviewResults.length === 0
            ? "Chưa có chỉ số nào trong phiên làm việc này."
            : `Còn ${pendingReviewCount} chỉ số cần gán phòng hoặc xác nhận.`,
        variant: "destructive",
      })
      return
    }

    setIsGeneratingInvoices(true)
    const monthStr = readingDate.slice(0, 7)

    try {
      const surchargeVal = parseFloat(surcharge) || 0
      const additionalFees: Record<string, number> = {}
      if (surchargeVal > 0) {
        additionalFees["Phụ phí"] = surchargeVal
      }

      const result = await apiPost<InvoiceGenerateResponseContract>("/invoices/generate", {
        building_id: parseInt(selectedBuilding),
        invoice_month: monthStr,
        price_config_id: parseInt(selectedPriceConfig),
        additional_fees: additionalFees,
      })

      let availableInvoices: Invoice[] = result.invoices
      try {
        availableInvoices = await apiGet<Invoice[]>("/invoices", {
          building_id: selectedBuilding,
          invoice_month: monthStr,
          offset: "0",
          limit: INVOICE_LIST_LIMIT.toString(),
        })
      } catch {
        // The generate response still contains every invoice created by this request.
      }
      setInvoices(availableInvoices)

      if (result.total_invoices === 0 && availableInvoices.length === 0) {
        toast({
          title: "Chưa tạo được hóa đơn",
          description: `Bỏ qua ${result.total_skipped} phòng, ${result.total_errors} phòng lỗi. Kiểm tra chỉ số đã duyệt.`,
          variant: "destructive",
        })
        return
      }

      setCurrentStep(3)
      if (result.total_errors > 0) {
        toast({
          title: "Tạo hóa đơn chưa hoàn tất",
          description: `Đã tạo ${result.total_invoices}, bỏ qua ${result.total_skipped}, lỗi ${result.total_errors} phòng.`,
          variant: "destructive",
        })
      } else if (result.total_invoices === 0) {
        toast({
          title: "Không có hóa đơn mới",
          description: `Đang hiển thị ${availableInvoices.length} hóa đơn hiện có; bỏ qua ${result.total_skipped} phòng.`,
        })
      } else {
        toast({
          title: `Đã tạo ${result.total_invoices} hóa đơn`,
          description: result.total_skipped > 0
            ? `Bỏ qua ${result.total_skipped} phòng chưa đủ điều kiện.`
            : "Các hóa đơn mới đã sẵn sàng.",
          variant: "success",
        })
      }
    } catch (error) {
      toast({
        title: "Lỗi tạo hóa đơn",
        description: error instanceof Error ? error.message : "Không thể tạo hóa đơn",
        variant: "destructive",
      })
    } finally {
      setIsGeneratingInvoices(false)
    }
  }

  // Step 4 Send Telegram
  const handleSendTelegramBatch = async () => {
    if (invoices.length === 0) return

    setIsSendingTelegram(true)
    setNotificationStatus(null)
    notificationAbortRef.current?.abort()
    const controller = new AbortController()
    notificationAbortRef.current = controller
    try {
      const invoiceIds = invoices
        .filter(
          (invoice) =>
            invoice.sent_status === "pending" ||
            invoice.sent_status === "failed"
        )
        .map((invoice) => invoice.id)

      if (invoiceIds.length === 0) {
        toast({
          title: "Không có hóa đơn cần gửi",
          description: "Không có hóa đơn chờ gửi trong danh sách đang hiển thị.",
        })
        return
      }

      const queued = await apiPost<NotificationSendBatchContract>(
        "/notifications/send-batch",
        {
          invoice_ids: invoiceIds,
          include_image: true,
        }
      )

      setNotificationStatus({
        job_id: queued.job_id,
        status: queued.status,
        total: queued.total,
        processed: 0,
        sent: 0,
        failed: 0,
      })
      setCurrentStep(4)

      toast({
        title: "Đang gửi Telegram",
        description: `${queued.total} hóa đơn đã vào hàng đợi. Vui lòng chờ kết quả thực tế.`,
      })

      const result = await waitForNotificationJob(
        queued.job_id,
        setNotificationStatus,
        controller.signal
      )
      const refreshedInvoices = await apiGet<Invoice[]>("/invoices", {
        building_id: selectedBuilding,
        invoice_month: readingDate.slice(0, 7),
        offset: "0",
        limit: INVOICE_LIST_LIMIT.toString(),
      })
      setInvoices(refreshedInvoices)

      if (result.status === "failed") {
        toast({
          title: "Gửi Telegram thất bại",
          description: `Đã xử lý ${result.processed}/${result.total} hóa đơn: ${result.sent} gửi được, ${result.failed} gửi lỗi.`,
          variant: "destructive",
        })
      } else if (result.failed > 0) {
        toast({
          title: "Gửi Telegram chưa hoàn tất",
          description: `Đã gửi ${result.sent}/${result.total} hóa đơn; ${result.failed} hóa đơn gửi lỗi.`,
          variant: "destructive",
        })
      } else {
        toast({
          title: "Đã gửi Telegram",
          description: `Đã gửi thành công ${result.sent} hóa đơn.`,
          variant: "success",
        })
      }
    } catch (error) {
      if (controller.signal.aborted) return
      toast({
        title: "Lỗi gửi Telegram",
        description: error instanceof Error ? error.message : "Không thể gửi thông báo",
        variant: "destructive",
      })
    } finally {
      if (
        notificationAbortRef.current === controller &&
        !controller.signal.aborted
      ) {
        notificationAbortRef.current = null
        setIsSendingTelegram(false)
      }
    }
  }

  const handleExportExcel = async () => {
    try {
      const monthStr = readingDate.slice(0, 7)
      const blob = await apiDownload(`/invoices/export/excel?building_id=${selectedBuilding}&invoice_month=${monthStr}`)
      const url = window.URL.createObjectURL(blob)
      const a = document.createElement("a")
      a.href = url
      a.download = `bao-cao-hoa-don-${monthStr}.xlsx`
      document.body.appendChild(a)
      a.click()
      window.URL.revokeObjectURL(url)
      document.body.removeChild(a)

      toast({ title: "Tải Excel thành công", description: "File báo cáo đã tải về", variant: "success" })
    } catch {
      toast({ title: "Lỗi tải Excel", description: "Không thể xuất file Excel", variant: "destructive" })
    }
  }

  const formatCurrency = (val: number) => {
    return new Intl.NumberFormat("vi-VN", { style: "currency", currency: "VND" }).format(val)
  }

  const getInvoiceStatusBadge = (status?: InvoiceSentStatus) => {
    switch (status) {
      case "sending":
        return <Badge variant="outline"><Loader2 className="mr-1 h-3 w-3 animate-spin" />Đang gửi</Badge>
      case "sent":
        return <Badge variant="success">Đã gửi</Badge>
      case "failed":
        return <Badge variant="destructive">Gửi lỗi</Badge>
      default:
        return <Badge variant="warning">Chưa gửi</Badge>
    }
  }

  return (
    <>
    {approveConfirmDialog?.open && (
      <Dialog open onOpenChange={() => setApproveConfirmDialog(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Có hình chưa xác nhận được phòng</DialogTitle>
            <DialogDescription asChild>
              <div>
                <p>
                  Có <strong>{approveConfirmDialog.unmatchedCount} hình</strong> chưa nhận diện được phòng và sẽ bị bỏ qua.
                </p>
                <p className="mt-1">
                  Bạn có đồng ý tiếp tục xác nhận{" "}
                  <strong>{approveConfirmDialog.toApprove.filter(canApproveResult).length} hình</strong>{" "}
                  đã gán phòng không?
                </p>
              </div>
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="outline" onClick={() => setApproveConfirmDialog(null)}>
              Không
            </Button>
            <Button
              onClick={() => {
                const matched = approveConfirmDialog.toApprove.filter(canApproveResult)
                const msg = approveConfirmDialog.successMsg.replace("{skip}", String(approveConfirmDialog.unmatchedCount))
                setApproveConfirmDialog(null)
                executeApproveList(matched, msg)
              }}
            >
              Đồng ý, bỏ qua và xác nhận
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    )}
    <div className="space-y-6 max-w-6xl mx-auto pb-12">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
        <div>
          <h1 className="text-3xl font-bold tracking-tight flex items-center gap-2">
            <Sparkles className="h-7 w-7 text-primary" />
            Quy Trình Tự Động 4 Bước
          </h1>
          <p className="text-muted-foreground">
            Từ Upload ảnh công tơ ➔ AI nhận diện ➔ Tự động lập hóa đơn ➔ Gửi Telegram từng phòng
          </p>
        </div>
      </div>

      {/* Stepper Navigation */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3 bg-card p-4 rounded-xl border shadow-sm">
        {[
          { step: 1, title: "1. Upload & AI OCR", desc: "Tải ảnh công tơ điện" },
          { step: 2, title: "2. Rà Soát Chỉ Số", desc: "Duyệt & Sửa chỉ số" },
          { step: 3, title: "3. Lập Hóa Đơn", desc: "Tính tiền EVN lũy tiến" },
          { step: 4, title: "4. Gửi Telegram", desc: "Gửi ảnh & hóa đơn" },
        ].map((s) => (
          <button
            key={s.step}
            onClick={() => setCurrentStep(s.step)}
            className={`flex flex-col text-left p-3 rounded-lg border transition-all ${
              currentStep === s.step
                ? "bg-primary text-primary-foreground border-primary shadow-sm"
                : currentStep > s.step
                ? "bg-green-500/10 border-green-500/30 text-foreground"
                : "bg-muted/40 border-transparent text-muted-foreground hover:bg-muted"
            }`}
          >
            <div className="flex items-center justify-between font-bold text-sm">
              <span>{s.title}</span>
              {currentStep > s.step && <CheckCircle2 className="h-4 w-4 text-green-600 dark:text-green-400" />}
            </div>
            <span className={`text-xs mt-1 ${currentStep === s.step ? "text-primary-foreground/80" : "text-muted-foreground"}`}>
              {s.desc}
            </span>
          </button>
        ))}
      </div>

      {/* STEP 1: UPLOAD & AI OCR */}
      {currentStep === 1 && (
        <Card className="border-primary/20 shadow-sm">
          <CardHeader>
            <CardTitle className="text-xl flex items-center gap-2">
              <Upload className="h-5 w-5 text-primary" />
              Bước 1: Chọn Tòa Nhà & Upload Ảnh Công Tơ Điện
            </CardTitle>
            <CardDescription>
              Kéo thả hoặc tải lên ảnh công tơ điện. AI Cư Dân sẽ tự động đọc chỉ số và nhận diện số phòng.
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-6">
            <div className="grid gap-4 sm:grid-cols-2">
              <div className="space-y-2">
                <Label>Tòa nhà</Label>
                <Select value={selectedBuilding} onValueChange={setSelectedBuilding}>
                  <SelectTrigger>
                    <SelectValue placeholder="Chọn tòa nhà" />
                  </SelectTrigger>
                  <SelectContent>
                    {buildings.map((b) => (
                      <SelectItem key={b.id} value={b.id.toString()}>
                        {b.name} ({b.room_count} phòng)
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
                {!isLoadingRooms && selectedBuilding && rooms.length === 0 && (
                  <p className="text-sm font-medium text-destructive">
                    Tòa nhà này chưa có phòng. Thêm phòng trước khi tải ảnh.
                  </p>
                )}
              </div>

              <div className="space-y-2">
                <Label>Ngày ghi chỉ số</Label>
                <Input type="date" value={readingDate} onChange={(e) => setReadingDate(e.target.value)} />
              </div>
            </div>

            {/* Dropzone */}
            <div
              {...getRootProps()}
              className={`cursor-pointer rounded-xl border-2 border-dashed p-8 text-center transition-colors ${
                isDragActive ? "border-primary bg-primary/5" : "border-muted-foreground/25 hover:border-primary/50"
              }`}
            >
              <input {...getInputProps()} />
              <Upload className="mx-auto h-12 w-12 text-primary/60" />
              <p className="mt-3 text-base font-semibold">Kéo thả ảnh công tơ điện tại đây hoặc click để chọn</p>
              <p className="mt-1 text-xs text-muted-foreground">Hỗ trợ JPG, PNG, WebP — Chọn nhiều ảnh cùng lúc</p>
            </div>

            {/* Preview Grid */}
            {files.length > 0 && (
              <div className="grid grid-cols-2 gap-3 sm:grid-cols-4 md:grid-cols-6">
                {files.map((f, idx) => (
                  <div key={idx} className="group relative aspect-square overflow-hidden rounded-lg border bg-muted">
                    <img src={f.preview} alt="preview" className="h-full w-full object-cover" />
                    <button
                      onClick={() => removeFile(idx)}
                      className="absolute right-1 top-1 rounded-full bg-black/60 p-1 text-white opacity-0 transition-opacity group-hover:opacity-100"
                    >
                      ✕
                    </button>
                  </div>
                ))}
              </div>
            )}

            {/* Action */}
            <Button
              onClick={handleUpload}
              disabled={isUploading || isLoadingRooms || rooms.length === 0 || files.length === 0 || !selectedBuilding}
              size="lg"
              className="w-full text-base font-bold bg-primary hover:bg-primary/90"
            >
              {isUploading ? (
                <div className="flex items-center gap-2">
                  <Loader2 className="h-5 w-5 animate-spin" />
                  AI Cư Dân đang đọc chỉ số ({files.length} ảnh)...
                </div>
              ) : (
                <div className="flex items-center gap-2">
                  <Sparkles className="h-5 w-5" />
                  Bắt Đầu AI Cư Dân Đọc Chỉ Số ({files.length} ảnh) ➔
                </div>
              )}
            </Button>
          </CardContent>
        </Card>
      )}

      {/* STEP 2: REVIEW READINGS */}
      {currentStep === 2 && (
        <Card className="border-primary/20 shadow-sm">
          <CardHeader className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
            <div>
              <CardTitle className="text-xl flex items-center gap-2">
                <CheckCircle2 className="h-5 w-5 text-green-500" />
                Bước 2: Rà Soát & Xác Nhận Chỉ Số AI
              </CardTitle>
              <CardDescription>
                Kiểm tra các chỉ số điện AI vừa đọc. Bạn có thể Sửa hoặc bấm Xác nhận trước khi lập hóa đơn.
              </CardDescription>
            </div>
            <div className="flex gap-2">
              <Button variant="outline" onClick={() => setCurrentStep(1)}>
                <ArrowLeft className="mr-1 h-4 w-4" /> Quay lại Bước 1
              </Button>
              <Button onClick={() => handleGenerateInvoices()} disabled={isGeneratingInvoices || !canGenerateInvoices} className="bg-green-600 hover:bg-green-700 text-white font-bold">
                {isGeneratingInvoices ? <Loader2 className="h-4 w-4 animate-spin" /> : "Tạo Hóa Đơn & Sang Bước 3 ➔"}
              </Button>
            </div>
          </CardHeader>
          <CardContent className="space-y-6">
            {pendingReviewCount > 0 && (
              <div className="rounded-md border border-amber-300 bg-amber-50 px-4 py-3 text-sm text-amber-900">
                Còn {pendingReviewCount} chỉ số cần gán phòng hoặc xác nhận trước khi tạo hóa đơn.
              </div>
            )}
            {/* Batch Action Bar */}
            {unapprovedResults.length > 0 && (
              <div className="flex flex-wrap items-center justify-between gap-3 p-3 bg-muted/40 rounded-xl border border-primary/20">
                <div className="flex items-center gap-3">
                  <label className="flex items-center gap-2 text-sm font-semibold cursor-pointer select-none">
                    <input
                      type="checkbox"
                      checked={isAllSelected}
                      onChange={handleSelectAllToggle}
                      className="h-4 w-4 rounded border-gray-300 text-primary focus:ring-primary"
                    />
                    Chọn tất cả ({unapprovedResults.length} phòng chờ duyệt)
                  </label>
                </div>

                <div className="flex items-center gap-2">
                  {selectedResultIds.size > 0 && (
                    <Button
                      onClick={handleApproveSelected}
                      disabled={isBatchApproving}
                      size="sm"
                      className="bg-blue-600 hover:bg-blue-700 text-white font-semibold gap-1"
                    >
                      {isBatchApproving ? (
                        <Loader2 className="h-4 w-4 animate-spin" />
                      ) : (
                        <Check className="h-4 w-4" />
                      )}
                      Xác Nhận ({selectedResultIds.size}) Phòng Đã Chọn
                    </Button>
                  )}

                  <Button
                    onClick={handleApproveAll}
                    disabled={isBatchApproving}
                    size="sm"
                    className="bg-green-600 hover:bg-green-700 text-white font-bold gap-1 shadow-sm"
                  >
                    {isBatchApproving ? (
                      <Loader2 className="h-4 w-4 animate-spin" />
                    ) : (
                      <CheckCircle2 className="h-4 w-4" />
                    )}
                    ✅ Xác Nhận Tất Cả ({unapprovedResults.length} phòng)
                  </Button>
                </div>
              </div>
            )}

            {batchStatus && batchStatus.results && batchStatus.results.length > 0 ? (
              <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
                {batchStatus.results.map((result) => {
                  const idKey = result.id ?? result.staged_id ?? ""
                  const isSelected = selectedResultIds.has(idKey)
                  return (
                    <div
                      key={idKey}
                      className={`overflow-hidden rounded-xl border bg-card shadow-xs transition-all ${
                        isSelected ? "ring-2 ring-primary border-primary bg-primary/5" : ""
                      }`}
                    >
                      <div className="relative aspect-video bg-muted">
                        <ProtectedReadingImage
                          imagePath={result.image_path}
                          alt={result.room_number ? `Phòng ${result.room_number}` : "Ảnh chưa gán phòng"}
                        />
                      </div>
                      <div className="p-3 space-y-2">
                        <div className="flex items-center justify-between">
                          <div className="flex items-center gap-2">
                            {result.status !== "approved" && (
                              <input
                                type="checkbox"
                                checked={isSelected}
                                onChange={() => toggleSelectResult(idKey)}
                                className="h-4 w-4 rounded border-gray-300 text-primary focus:ring-primary cursor-pointer"
                              />
                            )}
                            <span className="font-bold text-base text-primary">{result.room_number ? `Phòng ${result.room_number}` : "Chưa gán phòng"}</span>
                          </div>
                          <Badge variant={result.status === "approved" ? "success" : "warning"}>
                            {result.status === "approved" ? "Đã xác nhận" : "Cần xem lại"}
                          </Badge>
                        </div>

                      <div className="flex items-center gap-2">
                        <span className="text-xs text-muted-foreground">Chỉ số:</span>
                        <span className="text-xl font-black font-mono">{result.meter_value} kWh</span>
                      </div>

                      {result.notes && <p className="text-xs text-muted-foreground line-clamp-2">{result.notes}</p>}

                      <div className="flex gap-2 pt-1">
                        {result.status !== "approved" && result.id !== null && (
                          <Button size="sm" onClick={() => handleApproveResult(result.id as number)} className="flex-1 text-xs">
                            <Check className="mr-1 h-3 w-3" /> Xác nhận
                          </Button>
                        )}
                        <Button
                          size="sm"
                          variant="outline"
                          onClick={() => {
                            setEditingResult(result)
                            setEditValue(result.meter_value?.toString() || "")
                            setEditRoomId(result.room_id?.toString() || "")
                            setShowEditDialog(true)
                          }}
                          className="flex-1 text-xs"
                        >
                          <Pencil className="mr-1 h-3 w-3" /> Sửa chỉ số
                        </Button>
                      </div>
                    </div>
                  </div>
                )
              })}
              </div>
            ) : (
              <div className="py-12 text-center text-muted-foreground border border-dashed rounded-xl">
                Chưa có chỉ số nào được chốt trong phiên làm việc này. Hãy nhấn Quay lại Bước 1 để Upload ảnh.
              </div>
            )}
          </CardContent>
        </Card>
      )}

      {/* STEP 3: GENERATE & VIEW INVOICES */}
      {currentStep === 3 && (
        <Card className="border-primary/20 shadow-sm">
          <CardHeader className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
            <div>
              <CardTitle className="text-xl flex items-center gap-2">
                <FileText className="h-5 w-5 text-primary" />
                Bước 3: Lập Hóa Đơn & Diễn Giải Tiền Điện EVN
              </CardTitle>
              <CardDescription>
                Hệ thống đã tự động tính tiền điện theo bậc thang EVN + thuế VAT cho {invoices.length} phòng.
                {invoices.length === INVOICE_LIST_LIMIT
                  ? ` Đang hiển thị ${INVOICE_LIST_LIMIT} hóa đơn đầu tiên.`
                  : ""}
              </CardDescription>
            </div>
            <div className="flex gap-2">
              <Button variant="outline" onClick={() => setCurrentStep(2)}>
                <ArrowLeft className="mr-1 h-4 w-4" /> Quay lại Bước 2
              </Button>
              <Button onClick={() => setCurrentStep(4)} className="bg-primary hover:bg-primary/90 text-primary-foreground font-bold">
                🚀 Gửi Telegram Từng Phòng (Bước 4) ➔
              </Button>
            </div>
          </CardHeader>
          <CardContent className="space-y-6">
            {/* Invoice list table */}
            <div className="overflow-x-auto rounded-xl border">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b bg-muted/60 text-muted-foreground">
                    <th className="px-3 py-3 text-left font-semibold">Phòng</th>
                    <th className="px-3 py-3 text-left font-semibold">Cư dân</th>
                    <th className="px-3 py-3 text-right font-semibold">Chỉ số cũ</th>
                    <th className="px-3 py-3 text-right font-semibold">Chỉ số mới</th>
                    <th className="px-3 py-3 text-right font-semibold">Tiêu thụ</th>
                    <th className="px-3 py-3 text-right font-semibold">Tổng tiền</th>
                    <th className="px-3 py-3 text-center font-semibold">Thao tác</th>
                  </tr>
                </thead>
                <tbody>
                  {invoices.map((inv) => (
                    <tr key={inv.id} className="border-b hover:bg-muted/40 transition-colors">
                      <td className="px-3 py-3 font-bold text-primary">Phòng {inv.room_number}</td>
                      <td className="px-3 py-3 font-medium">{inv.resident_name || inv.tenant_name || "N/A"}</td>
                      <td className="px-3 py-3 text-right font-mono">{inv.previous_reading}</td>
                      <td className="px-3 py-3 text-right font-mono">{inv.current_reading}</td>
                      <td className="px-3 py-3 text-right font-mono font-semibold">{inv.consumption} kWh</td>
                      <td className="px-3 py-3 text-right font-mono font-bold text-green-600 dark:text-green-400">
                        {formatCurrency(inv.total_amount)}
                      </td>
                      <td className="px-3 py-3 text-center">
                        <Button
                          variant="outline"
                          size="sm"
                          className="h-8 text-xs gap-1"
                          onClick={() => setSelectedInvoiceForDetail(inv)}
                        >
                          <Eye className="h-3.5 w-3.5" /> Xem chi tiết
                        </Button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </CardContent>
        </Card>
      )}

      {/* STEP 4: TELEGRAM NOTIFICATIONS */}
      {currentStep === 4 && (
        <Card className="border-primary/20 shadow-sm">
          <CardHeader className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
            <div>
              <CardTitle className="text-xl flex items-center gap-2">
                <Send className="h-5 w-5 text-blue-500" />
                Bước 4: Gửi Thông Báo Telegram Cho Cư Dân
              </CardTitle>
              <CardDescription>
                {notificationStatus &&
                notificationStatus.status !== "completed" &&
                notificationStatus.status !== "failed"
                  ? `Đang gửi: đã xử lý ${notificationStatus.processed}/${notificationStatus.total} hóa đơn.`
                  : notificationStatus
                  ? `Kết quả: gửi được ${notificationStatus.sent}, gửi lỗi ${notificationStatus.failed} hóa đơn.`
                  : "Hệ thống tự động gửi tin nhắn báo tiền điện kèm ảnh công tơ điện trực tiếp tới tài khoản Telegram cư dân."}
              </CardDescription>
            </div>
            <div className="flex gap-2 flex-wrap">
              <Button variant="outline" onClick={() => setCurrentStep(3)} disabled={isSendingTelegram}>
                <ArrowLeft className="mr-1 h-4 w-4" /> Quay lại Bước 3
              </Button>
              <Button variant="outline" onClick={handleExportExcel}>
                <Download className="mr-1 h-4 w-4" /> Xuất Excel Báo Cáo
              </Button>
              <Button onClick={() => setCurrentStep(1)} className="bg-primary hover:bg-primary/90 text-primary-foreground font-bold">
                ✨ Hoàn Tất & Làm Phiên Mới
              </Button>
            </div>
          </CardHeader>
          <CardContent className="space-y-6">
            {/* Telegram Preview Card */}
            <div className="bg-muted/40 p-4 rounded-xl border space-y-3">
              <div className="flex items-center gap-2 font-bold text-sm text-blue-600 dark:text-blue-400">
                <Bot className="h-4 w-4" /> Xem trước nội dung tin nhắn Telegram gửi cư dân:
              </div>
              <div className="bg-card p-4 rounded-lg border font-mono text-xs space-y-1.5 shadow-inner leading-relaxed">
                <p className="font-bold text-primary">🧾 HÓA ĐƠN TIỀN ĐIỆN THÁNG {readingDate.slice(0, 7)}</p>
                <p>👤 Cư dân: Nguyễn Văn A (Phòng 1814)</p>
                <p>🔹 Chỉ số cũ: 120 kWh | Chỉ số mới: 252 kWh</p>
                <p>⚡ Tổng tiêu thụ: 132 kWh</p>
                <p className="font-bold text-green-600 dark:text-green-400">💰 TỔNG CỘNG THANH TOÁN: 312.450 VNĐ</p>
                <p className="text-muted-foreground italic mt-2">📸 Ảnh chụp mặt đồng hồ điện công tơ được đính kèm bên dưới tin nhắn.</p>
              </div>
            </div>

            {/* Confirm Send Button */}
            {!notificationStatus && (
              <div className="flex justify-center">
                <Button
                  onClick={handleSendTelegramBatch}
                  disabled={isSendingTelegram}
                  size="lg"
                  className="bg-blue-600 hover:bg-blue-700 text-white font-bold px-8"
                >
                  {isSendingTelegram ? (
                    <><Loader2 className="mr-2 h-5 w-5 animate-spin" /> Đang gửi...</>
                  ) : (
                    <><Send className="mr-2 h-5 w-5" /> Xác Nhận Gửi Telegram Cho Tất Cả Phòng</>
                  )}
                </Button>
              </div>
            )}

            {/* Sending progress banner */}
            {notificationStatus && notificationStatus.status !== "completed" && notificationStatus.status !== "failed" && (
              <div className="flex items-center gap-3 p-4 rounded-xl border border-blue-200 bg-blue-50 dark:bg-blue-950/30 dark:border-blue-800">
                <Loader2 className="h-6 w-6 text-blue-600 animate-spin shrink-0" />
                <div>
                  <p className="font-semibold text-blue-700 dark:text-blue-400">Đang gửi Telegram...</p>
                  <p className="text-sm text-blue-600 dark:text-blue-500">
                    Đã xử lý {notificationStatus.processed}/{notificationStatus.total} hóa đơn
                    {notificationStatus.sent > 0 && ` — đã gửi được ${notificationStatus.sent}`}
                  </p>
                </div>
              </div>
            )}

            {/* Result banner */}
            {notificationStatus && (notificationStatus.status === "completed" || notificationStatus.status === "failed") && (
              <div className={`flex items-start gap-3 p-4 rounded-xl border ${
                notificationStatus.failed === 0
                  ? "border-green-200 bg-green-50 dark:bg-green-950/30 dark:border-green-800"
                  : "border-yellow-200 bg-yellow-50 dark:bg-yellow-950/30 dark:border-yellow-800"
              }`}>
                <div className="text-2xl shrink-0">
                  {notificationStatus.failed === 0 ? "✅" : "⚠️"}
                </div>
                <div className="flex-1">
                  <p className={`font-bold text-base ${notificationStatus.failed === 0 ? "text-green-700 dark:text-green-400" : "text-yellow-700 dark:text-yellow-400"}`}>
                    {notificationStatus.failed === 0
                      ? `Đã gửi thành công ${notificationStatus.sent} tin nhắn Telegram!`
                      : `Gửi hoàn tất: ${notificationStatus.sent} thành công, ${notificationStatus.failed} thất bại`}
                  </p>
                  <p className="text-sm text-muted-foreground mt-0.5">
                    Tổng cộng {notificationStatus.total} hóa đơn đã được xử lý. Xem trạng thái từng phòng bên dưới.
                  </p>
                </div>
              </div>
            )}

            {/* Room delivery list */}
            <div className="space-y-3">
              <h4 className="font-bold text-sm">Trạng thái gửi theo phòng:</h4>
              <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
                {invoices.map((inv) => (
                  <div key={inv.id} className="p-3 bg-card border rounded-lg flex items-center justify-between text-xs">
                    <div>
                      <span className="font-bold block text-sm">Phòng {inv.room_number}</span>
                      <span className="text-muted-foreground">{inv.resident_name || inv.tenant_name}</span>
                    </div>
                    {getInvoiceStatusBadge(inv.sent_status)}
                  </div>
                ))}
              </div>
            </div>
          </CardContent>
        </Card>
      )}

      {/* Edit Single Reading Dialog */}
      <Dialog open={showEditDialog} onOpenChange={setShowEditDialog}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{editingResult?.room_number ? `Sửa chỉ số điện — Phòng ${editingResult.room_number}` : "Gán phòng và duyệt chỉ số"}</DialogTitle>
          </DialogHeader>
          <div className="space-y-4 py-4">
            <div className="space-y-2">
              <Label>Phòng</Label>
              <Select value={editRoomId} onValueChange={setEditRoomId}>
                <SelectTrigger><SelectValue placeholder="Chọn phòng" /></SelectTrigger>
                <SelectContent>{rooms.map((room) => <SelectItem key={room.id} value={room.id.toString()}>Phòng {room.room_number}{room.resident_name ? ` — ${room.resident_name}` : ""}</SelectItem>)}</SelectContent>
              </Select>
            </div>
            <div className="space-y-2">
              <Label>Chỉ số điện (kWh)</Label>
              <Input type="number" step="1" value={editValue} onChange={(e) => setEditValue(e.target.value)} />
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setShowEditDialog(false)}>
              Hủy
            </Button>
            <Button
              onClick={handleEditSave}
              disabled={!editRoomId || !Number.isInteger(Number(editValue)) || Number(editValue) < 0}
            >
              Lưu & Duyệt
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Single Invoice Detail Dialog */}
      <Dialog open={!!selectedInvoiceForDetail} onOpenChange={(open) => !open && setSelectedInvoiceForDetail(null)}>
        {selectedInvoiceForDetail && (
          <DialogContent className="sm:max-w-lg max-h-[90vh] overflow-y-auto">
            <DialogHeader className="border-b pb-3">
              <DialogTitle className="text-xl font-bold text-primary">
                HÓA ĐƠN TIỀN ĐIỆN PHÒNG {selectedInvoiceForDetail.room_number}
              </DialogTitle>
              <DialogDescription className="text-xs">
                Kỳ tính tiền: Tháng {selectedInvoiceForDetail.invoice_month || readingDate.slice(0, 7)}
              </DialogDescription>
            </DialogHeader>
            <div className="space-y-3 py-2 text-sm">
              {/* Cư dân + chỉ số */}
              <div className="grid grid-cols-3 gap-2 bg-muted/40 p-3 rounded-lg border text-xs">
                <div>
                  <span className="text-muted-foreground block">Cư dân:</span>
                  <span className="font-semibold">{selectedInvoiceForDetail.resident_name || "N/A"}</span>
                </div>
                <div>
                  <span className="text-muted-foreground block">Chỉ số cũ:</span>
                  <span className="font-mono">{selectedInvoiceForDetail.previous_reading} kWh</span>
                </div>
                <div>
                  <span className="text-muted-foreground block">Chỉ số mới:</span>
                  <span className="font-mono">{selectedInvoiceForDetail.current_reading} kWh</span>
                </div>
              </div>

              {/* Tiêu thụ */}
              <div className="flex justify-between text-xs px-1">
                <span className="text-muted-foreground">Tổng tiêu thụ:</span>
                <span className="font-bold text-primary font-mono">{selectedInvoiceForDetail.consumption} kWh</span>
              </div>

              {/* Bảng chi tiết giá */}
              {(() => {
                try {
                  const bd = selectedInvoiceForDetail.price_breakdown
                    ? JSON.parse(selectedInvoiceForDetail.price_breakdown)
                    : null
                  if (!bd) return null
                  return (
                    <div className="border rounded-lg overflow-hidden text-xs">
                      <table className="w-full">
                        <thead className="bg-muted/60">
                          <tr>
                            <th className="px-3 py-2 text-left font-medium">Nội dung</th>
                            <th className="px-3 py-2 text-right font-medium">kWh</th>
                            <th className="px-3 py-2 text-right font-medium">Đơn giá</th>
                            <th className="px-3 py-2 text-right font-medium">Thành tiền</th>
                          </tr>
                        </thead>
                        <tbody className="divide-y">
                          {bd.tiers
                            ? bd.tiers.map((t: { name: string; kwh: number; price: number; amount: number }, i: number) => (
                                <tr key={i}>
                                  <td className="px-3 py-1.5">{t.name}</td>
                                  <td className="px-3 py-1.5 text-right font-mono">{t.kwh}</td>
                                  <td className="px-3 py-1.5 text-right font-mono">{formatCurrency(t.price)}</td>
                                  <td className="px-3 py-1.5 text-right font-mono">{formatCurrency(t.amount)}</td>
                                </tr>
                              ))
                            : (
                                <tr>
                                  <td className="px-3 py-1.5">Giá cố định</td>
                                  <td className="px-3 py-1.5 text-right font-mono">{selectedInvoiceForDetail.consumption}</td>
                                  <td className="px-3 py-1.5 text-right font-mono">{formatCurrency(bd.price_per_kwh)}</td>
                                  <td className="px-3 py-1.5 text-right font-mono">{formatCurrency(bd.subtotal)}</td>
                                </tr>
                              )}
                        </tbody>
                        <tfoot className="bg-muted/30 divide-y">
                          <tr>
                            <td colSpan={3} className="px-3 py-1.5">Tiền điện (trước VAT)</td>
                            <td className="px-3 py-1.5 text-right font-mono">{formatCurrency(bd.subtotal)}</td>
                          </tr>
                          {bd.vat_rate > 0 && (
                            <tr>
                              <td colSpan={3} className="px-3 py-1.5">VAT ({Math.round(bd.vat_rate * 100)}%)</td>
                              <td className="px-3 py-1.5 text-right font-mono">{formatCurrency(bd.vat_amount)}</td>
                            </tr>
                          )}
                        </tfoot>
                      </table>
                    </div>
                  )
                } catch { return null }
              })()}

              {/* Phí phụ */}
              {selectedInvoiceForDetail.additional_fees && (() => {
                try {
                  const fees = JSON.parse(selectedInvoiceForDetail.additional_fees) as Record<string, number>
                  const entries = Object.entries(fees)
                  if (!entries.length) return null
                  return (
                    <div className="text-xs space-y-1 px-1 border-t pt-2">
                      {entries.map(([name, amount]) => (
                        <div key={name} className="flex justify-between">
                          <span className="text-muted-foreground">{name}:</span>
                          <span className="font-mono">{formatCurrency(amount)}</span>
                        </div>
                      ))}
                    </div>
                  )
                } catch { return null }
              })()}

              {/* Tổng */}
              <div className="flex items-center justify-between p-3 bg-green-500/10 border border-green-500/30 rounded-xl">
                <span className="font-bold text-sm text-green-800 dark:text-green-300">TỔNG THANH TOÁN:</span>
                <span className="text-xl font-black text-green-600 dark:text-green-400 font-mono">
                  {formatCurrency(selectedInvoiceForDetail.total_amount)}
                </span>
              </div>
            </div>
            <DialogFooter>
              <Button
                variant="outline"
                className="gap-1 text-xs"
                onClick={async () => {
                  try {
                    const blob = await apiDownload(`/invoices/${selectedInvoiceForDetail.id}/pdf`)
                    const url = window.URL.createObjectURL(blob)
                    const a = document.createElement("a")
                    a.href = url
                    const month = (selectedInvoiceForDetail.invoice_month ?? "").replace("-", "")
                    const room = (selectedInvoiceForDetail.room_number || "phong").replace(/\s/g, "_")
                    a.download = `hoa-don-${room}-${month}.pdf`
                    document.body.appendChild(a)
                    a.click()
                    window.URL.revokeObjectURL(url)
                    document.body.removeChild(a)
                  } catch {
                    toast({ title: "Lỗi xuất PDF", description: "Không thể tải hóa đơn PDF", variant: "destructive" })
                  }
                }}
              >
                <Printer className="h-3.5 w-3.5" /> Xuất PDF
              </Button>
              <Button onClick={() => setSelectedInvoiceForDetail(null)} className="text-xs">
                Đóng
              </Button>
            </DialogFooter>
          </DialogContent>
        )}
      </Dialog>
    </div>
    </>
  )
}
