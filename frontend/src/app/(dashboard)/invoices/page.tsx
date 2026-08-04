"use client"

import React, { useState, useEffect, useCallback, useRef } from "react"
import {
  FileText,
  Send,
  Download,
  Plus,
  Loader2,
  CheckCircle2,
  Clock,
  XCircle,
  RefreshCw,
  Eye,
  Printer,
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
import { apiGet, apiPost, apiDownload } from "@/lib/api"
import { toast } from "@/components/ui/use-toast"
import type {
  BuildingContract,
  InvoiceContract,
  InvoiceGenerateResponseContract,
  NotificationSendBatchContract,
  NotificationStatusContract,
  PriceConfigContract,
} from "@/lib/types"

const NOTIFICATION_POLL_INTERVAL_MS = 1000
const NOTIFICATION_POLL_TIMEOUT_MS = 60_000
const INVOICE_LIST_LIMIT = 200

const waitForNextPoll = (signal: AbortSignal) =>
  new Promise<void>((resolve, reject) => {
    const onAbort = () => {
      window.clearTimeout(timeoutId)
      reject(new DOMException("Polling cancelled", "AbortError"))
    }
    const timeoutId = window.setTimeout(() => {
      signal.removeEventListener("abort", onAbort)
      resolve()
    }, NOTIFICATION_POLL_INTERVAL_MS)
    signal.addEventListener("abort", onAbort, { once: true })
  })

const waitForNotificationJob = async (
  jobId: string,
  signal: AbortSignal
): Promise<NotificationStatusContract> => {
  const deadline = Date.now() + NOTIFICATION_POLL_TIMEOUT_MS
  while (!signal.aborted && Date.now() < deadline) {
    const status = await apiGet<NotificationStatusContract>(
      `/notifications/status/${jobId}`
    )
    if (signal.aborted) throw new DOMException("Polling cancelled", "AbortError")
    if (status.status === "completed" || status.status === "failed") {
      return status
    }
    await waitForNextPoll(signal)
  }
  if (signal.aborted) throw new DOMException("Polling cancelled", "AbortError")
  throw new Error("Quá thời gian chờ kết quả gửi. Kiểm tra lại danh sách hóa đơn.")
}

interface PriceBreakdownTier {
  name: string
  kwh: number
  price: number
  amount: number
}

interface PriceBreakdown {
  tiers?: PriceBreakdownTier[]
  subtotal?: number
  vat_rate?: number
  vat_amount?: number
}

export default function InvoicesPage() {
  const [buildings, setBuildings] = useState<BuildingContract[]>([])
  const [priceConfigs, setPriceConfigs] = useState<PriceConfigContract[]>([])
  const [invoices, setInvoices] = useState<InvoiceContract[]>([])
  const [selectedInvoice, setSelectedInvoice] = useState<InvoiceContract | null>(null)
  const [isLoading, setIsLoading] = useState(false)
  const [isGenerating, setIsGenerating] = useState(false)
  const [isSending, setIsSending] = useState(false)
  const notificationAbortRef = useRef<AbortController | null>(null)

  // Generate form
  const [selectedBuilding, setSelectedBuilding] = useState<string>("")
  const [selectedMonth, setSelectedMonth] = useState<string>(
    new Date().toISOString().slice(0, 7) // YYYY-MM format
  )
  const [selectedPriceConfig, setSelectedPriceConfig] = useState<string>("")
  const [surcharge, setSurcharge] = useState<string>("0")
  const [showGenerateDialog, setShowGenerateDialog] = useState(false)

  // Filter
  const [filterBuilding, setFilterBuilding] = useState<string>("all")
  const [filterMonth, setFilterMonth] = useState<string>(
    new Date().toISOString().slice(0, 7)
  )

  const fetchBuildings = useCallback(async () => {
    try {
      const data = await apiGet<BuildingContract[]>("/buildings")
      setBuildings(data)
      if (data.length > 0) {
        setSelectedBuilding((prev) => prev || data[0].id.toString())
      }
    } catch {
      // Silently handle
    }
  }, [])

  const fetchPriceConfigs = useCallback(async () => {
    try {
      const data = await apiGet<PriceConfigContract[]>("/price-configs")
      setPriceConfigs(data)
      if (data.length > 0) {
        setSelectedPriceConfig((prev) => prev || data[0].id.toString())
      }
    } catch {
      // Silently handle
    }
  }, [])

  const fetchInvoices = useCallback(async () => {
    setIsLoading(true)
    try {
      const params: Record<string, string> = {
        offset: "0",
        limit: INVOICE_LIST_LIMIT.toString(),
      }
      if (filterBuilding && filterBuilding !== "all") {
        params.building_id = filterBuilding
      }
      if (filterMonth) {
        params.invoice_month = filterMonth
      }
      const data = await apiGet<InvoiceContract[]>("/invoices", params)
      setInvoices(data)
    } catch {
      setInvoices([])
    } finally {
      setIsLoading(false)
    }
  }, [filterBuilding, filterMonth])

  useEffect(() => {
    fetchBuildings()
    fetchPriceConfigs()
  }, [fetchBuildings, fetchPriceConfigs])

  useEffect(() => {
    fetchInvoices()
  }, [fetchInvoices])

  useEffect(
    () => () => {
      notificationAbortRef.current?.abort()
    },
    []
  )

  const handleGenerate = async () => {
    if (!selectedBuilding || !selectedMonth || !selectedPriceConfig) {
      toast({
        title: "Thiếu thông tin",
        description: "Vui lòng chọn Tòa nhà và Bảng giá",
        variant: "destructive",
      })
      return
    }

    setIsGenerating(true)
    try {
      const surchargeVal = parseFloat(surcharge) || 0
      const additionalFees: Record<string, number> = {}
      if (surchargeVal > 0) {
        additionalFees["Phụ phí"] = surchargeVal
      }

      const result = await apiPost<InvoiceGenerateResponseContract>(
        "/invoices/generate",
        {
          building_id: parseInt(selectedBuilding),
          invoice_month: selectedMonth,
          price_config_id: parseInt(selectedPriceConfig),
          additional_fees: additionalFees,
        }
      )

      if (result.total_errors > 0) {
        toast({
          title: "Tạo hóa đơn chưa hoàn tất",
          description: `Đã tạo ${result.total_invoices}, bỏ qua ${result.total_skipped}, lỗi ${result.total_errors} phòng.`,
          variant: "destructive",
        })
      } else if (result.total_invoices === 0) {
        toast({
          title: "Không có hóa đơn mới",
          description: `Đã bỏ qua ${result.total_skipped} phòng. Kiểm tra chỉ số đã duyệt hoặc hóa đơn hiện có.`,
        })
      } else {
        toast({
          title: `Đã tạo ${result.total_invoices} hóa đơn`,
          description:
            result.total_skipped > 0
              ? `Bỏ qua ${result.total_skipped} phòng chưa đủ điều kiện.`
              : "Tất cả phòng đủ điều kiện đã được tạo hóa đơn.",
          variant: "success",
        })
      }

      setShowGenerateDialog(false)
      await fetchInvoices()
    } catch (error) {
      toast({
        title: "Lỗi tạo hóa đơn",
        description:
          error instanceof Error
            ? error.message
            : "Không thể tạo hóa đơn. Vui lòng kiểm tra lại chỉ số.",
        variant: "destructive",
      })
    } finally {
      setIsGenerating(false)
    }
  }

  const handleSendTelegram = async () => {
    if (invoices.length === 0) {
      toast({
        title: "Không có hóa đơn",
        description: "Không có hóa đơn nào để gửi",
        variant: "destructive",
      })
      return
    }

    setIsSending(true)
    notificationAbortRef.current?.abort()
    const controller = new AbortController()
    notificationAbortRef.current = controller
    try {
      const invoiceIds = invoices
        .filter(
          (inv) =>
            inv.sent_status === "pending" || inv.sent_status === "failed"
        )
        .map((inv) => inv.id)

      if (invoiceIds.length === 0) {
        toast({
          title: "Thông báo",
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

      toast({
        title: "Đang gửi Telegram",
        description: `${queued.total} hóa đơn đã vào hàng đợi. Hệ thống đang gửi và cập nhật kết quả.`,
      })

      const result = await waitForNotificationJob(queued.job_id, controller.signal)
      await fetchInvoices()

      if (result.status === "failed") {
        toast({
          title: "Gửi Telegram thất bại",
          description: `Đã xử lý ${result.processed}/${result.total} hóa đơn: ${result.sent} gửi được, ${result.failed} gửi lỗi.`,
          variant: "destructive",
        })
      } else if (result.failed > 0) {
        toast({
          title: "Gửi Telegram chưa hoàn tất",
          description: `Đã gửi ${result.sent}/${result.total} hóa đơn; ${result.failed} hóa đơn gửi lỗi. Bạn có thể thử gửi lại các hóa đơn lỗi.`,
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
        description:
          error instanceof Error ? error.message : "Không thể gửi thông báo",
        variant: "destructive",
      })
    } finally {
      if (
        notificationAbortRef.current === controller &&
        !controller.signal.aborted
      ) {
        notificationAbortRef.current = null
        setIsSending(false)
      }
    }
  }

  const handleExportExcel = async () => {
    if (!filterBuilding || filterBuilding === "all") {
      toast({
        title: "Chưa chọn tòa nhà",
        description: "Chọn một tòa nhà trước khi xuất Excel.",
        variant: "destructive",
      })
      return
    }

    try {
      const queryString = new URLSearchParams({
        building_id: filterBuilding,
        invoice_month: filterMonth,
      }).toString()
      const blob = await apiDownload(
        `/invoices/export/excel?${queryString}`
      )

      // Trigger download
      const url = window.URL.createObjectURL(blob)
      const a = document.createElement("a")
      a.href = url
      a.download = `hoa-don-${filterMonth || "all"}.xlsx`
      document.body.appendChild(a)
      a.click()
      window.URL.revokeObjectURL(url)
      document.body.removeChild(a)

      toast({
        title: "Export thành công",
        description: "File Excel đã được tải về",
        variant: "success",
      })
    } catch (error) {
      toast({
        title: "Lỗi export",
        description: "Không thể xuất file Excel",
        variant: "destructive",
      })
    }
  }

  const getStatusBadge = (status: string) => {
    switch (status) {
      case "pending":
        return (
          <Badge variant="warning">
            <Clock className="mr-1 h-3 w-3" />
            Chưa gửi
          </Badge>
        )
      case "sending":
        return (
          <Badge variant="outline">
            <Loader2 className="mr-1 h-3 w-3 animate-spin" />
            Đang gửi
          </Badge>
        )
      case "sent":
        return (
          <Badge variant="success">
            <CheckCircle2 className="mr-1 h-3 w-3" />
            Đã gửi
          </Badge>
        )
      case "failed":
        return (
          <Badge variant="destructive">
            <XCircle className="mr-1 h-3 w-3" />
            Gửi lỗi
          </Badge>
        )
      default:
        return <Badge variant="outline">{status}</Badge>
    }
  }

  const formatCurrency = (amount: number) => {
    return new Intl.NumberFormat("vi-VN", {
      style: "currency",
      currency: "VND",
    }).format(amount)
  }

  const totalAmount = invoices.reduce((sum, inv) => sum + inv.total_amount, 0)
  const pendingCount = invoices.filter((inv) => inv.sent_status === "pending").length
  const sendingCount = invoices.filter((inv) => inv.sent_status === "sending").length
  const failedCount = invoices.filter((inv) => inv.sent_status === "failed").length
  const sentCount = invoices.filter((inv) => inv.sent_status === "sent").length
  const sendableCount = invoices.filter(
    (inv) => inv.sent_status === "pending" || inv.sent_status === "failed"
  ).length
  const filteredBuildingName = buildings.find(
    (building) => building.id.toString() === filterBuilding
  )?.name

  return (
    <div className="space-y-6">
      {/* Page header */}
      <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h1 className="text-3xl font-bold tracking-tight">Hóa đơn</h1>
          <p className="text-muted-foreground">
            Quản lý và xuất hóa đơn điện cho cư dân
          </p>
        </div>
        <div className="flex gap-2">
          <Button onClick={() => setShowGenerateDialog(true)}>
            <Plus className="mr-2 h-4 w-4" />
            Tạo hóa đơn
          </Button>
        </div>
      </div>

      {/* Summary cards */}
      <div className="grid gap-4 sm:grid-cols-3">
        <Card>
          <CardContent className="p-4">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-sm text-muted-foreground">Hóa đơn đang hiển thị</p>
                <p className="text-2xl font-bold">{invoices.length}</p>
              </div>
              <FileText className="h-8 w-8 text-muted-foreground/50" />
            </div>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="p-4">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-sm text-muted-foreground">Tổng tiền đang hiển thị</p>
                <p className="text-2xl font-bold">{formatCurrency(totalAmount)}</p>
              </div>
              <FileText className="h-8 w-8 text-green-500/50" />
            </div>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="p-4">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-sm text-muted-foreground">Chờ / Đang gửi / Lỗi / Đã gửi</p>
                <p className="text-2xl font-bold">
                  {pendingCount} / {sendingCount} / {failedCount} / {sentCount}
                </p>
              </div>
              <Send className="h-8 w-8 text-blue-500/50" />
            </div>
          </CardContent>
        </Card>
      </div>

      {/* Filters & Actions */}
      <Card>
        <CardHeader>
          <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
            <div>
              <CardTitle>Danh sách hóa đơn</CardTitle>
              <CardDescription>
                Lọc và quản lý hóa đơn theo tòa nhà và tháng
                {invoices.length === INVOICE_LIST_LIMIT
                  ? ` · Đang hiển thị ${INVOICE_LIST_LIMIT} bản ghi đầu tiên.`
                  : ""}
              </CardDescription>
            </div>
            <div className="flex gap-2">
              <Button
                variant="outline"
                size="sm"
                onClick={handleSendTelegram}
                disabled={isSending || sendableCount === 0}
              >
                {isSending ? (
                  <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                ) : (
                  <Send className="mr-2 h-4 w-4" />
                )}
                Gửi Telegram
              </Button>
              <Button
                variant="outline"
                size="sm"
                onClick={handleExportExcel}
                disabled={
                  invoices.length === 0 ||
                  filterBuilding === "all" ||
                  !filterMonth
                }
              >
                <Download className="mr-2 h-4 w-4" />
                Export Excel
              </Button>
              <Button
                variant="ghost"
                size="sm"
                onClick={fetchInvoices}
              >
                <RefreshCw className="h-4 w-4" />
              </Button>
            </div>
          </div>
        </CardHeader>
        <CardContent>
          {/* Filters */}
          <div className="mb-4 flex flex-col gap-3 sm:flex-row">
            <div className="w-full sm:w-48">
              <Select value={filterBuilding} onValueChange={setFilterBuilding}>
                <SelectTrigger>
                  <SelectValue placeholder="Tất cả tòa nhà" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="all">Tất cả tòa nhà</SelectItem>
                  {buildings.map((b) => (
                    <SelectItem key={b.id} value={b.id.toString()}>
                      {b.name}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="w-full sm:w-48">
              <Input
                type="month"
                value={filterMonth}
                onChange={(e) => setFilterMonth(e.target.value)}
              />
            </div>
          </div>

          {/* Invoice table */}
          {isLoading ? (
            <div className="flex items-center justify-center py-12">
              <Loader2 className="h-8 w-8 animate-spin text-primary" />
            </div>
          ) : invoices.length === 0 ? (
            <div className="flex flex-col items-center justify-center py-10 px-4 text-center rounded-xl bg-gradient-to-b from-muted/30 to-muted/10 border border-dashed">
              <FileText className="mb-3 h-14 w-14 text-primary/70" />
              <h3 className="text-xl font-bold">Chưa có hóa đơn cho tháng {filterMonth}</h3>
              <p className="mt-1 text-sm text-muted-foreground max-w-lg">
                Sau khi AI đã nhận diện và chốt chỉ số điện ở màn <strong>Upload ảnh</strong>, bạn chỉ cần bấm nút bên dưới để hệ thống tự động tính tiền (theo lũy tiến EVN hoặc giá cố định) và lập hóa đơn cho tất cả các phòng!
              </p>
              
              <div className="my-6 grid grid-cols-1 sm:grid-cols-3 gap-3 w-full max-w-2xl text-left">
                <div className="p-3 bg-background rounded-lg border text-xs">
                  <div className="font-semibold text-primary mb-1">1️⃣ Chốt chỉ số</div>
                  <div className="text-muted-foreground">AI đọc ảnh công tơ điện & chốt chỉ số phòng</div>
                </div>
                <div className="p-3 bg-background rounded-lg border text-xs">
                  <div className="font-semibold text-primary mb-1">2️⃣ Lập hóa đơn</div>
                  <div className="text-muted-foreground">Tự động tính tiền điện theo bậc thang EVN</div>
                </div>
                <div className="p-3 bg-background rounded-lg border text-xs">
                  <div className="font-semibold text-primary mb-1">3️⃣ Gửi Telegram</div>
                  <div className="text-muted-foreground">Gửi thông báo kèm ảnh đến cư dân 1-click</div>
                </div>
              </div>

              <Button
                onClick={() => setShowGenerateDialog(true)}
                size="lg"
                className="bg-primary hover:bg-primary/90 text-primary-foreground font-semibold px-6 shadow-md"
              >
                ⚡ Tạo Hóa Đơn Ngay Cho Tháng {filterMonth}
              </Button>
            </div>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b bg-muted/50">
                    <th className="px-3 py-3 text-left font-medium">Phòng</th>
                    <th className="px-3 py-3 text-left font-medium">
                      Tên cư dân
                    </th>
                    <th className="px-3 py-3 text-left font-medium hidden sm:table-cell">
                      Tòa nhà
                    </th>
                    <th className="px-3 py-3 text-right font-medium hidden md:table-cell">
                      Chỉ số cũ
                    </th>
                    <th className="px-3 py-3 text-right font-medium hidden md:table-cell">
                      Chỉ số mới
                    </th>
                    <th className="px-3 py-3 text-right font-medium">
                      Tiêu thụ
                    </th>
                    <th className="px-3 py-3 text-right font-medium">
                      Tổng tiền
                    </th>
                    <th className="px-3 py-3 text-center font-medium">
                      Trạng thái
                    </th>
                    <th className="px-3 py-3 text-center font-medium">
                      Thao tác
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {invoices.map((invoice) => (
                    <tr
                      key={invoice.id}
                      className="border-b transition-colors hover:bg-muted/50 cursor-pointer"
                      onClick={() => setSelectedInvoice(invoice)}
                    >
                      <td className="px-3 py-3 font-bold text-primary">
                        Phòng {invoice.room_number || "N/A"}
                      </td>
                      <td className="px-3 py-3 font-medium">{invoice.resident_name || "N/A"}</td>
                      <td className="px-3 py-3 hidden sm:table-cell">
                        {filteredBuildingName || "—"}
                      </td>
                      <td className="px-3 py-3 text-right font-mono hidden md:table-cell">
                        {invoice.previous_reading}
                      </td>
                      <td className="px-3 py-3 text-right font-mono hidden md:table-cell">
                        {invoice.current_reading}
                      </td>
                      <td className="px-3 py-3 text-right font-mono font-semibold">
                        {invoice.consumption} kWh
                      </td>
                      <td className="px-3 py-3 text-right font-semibold text-green-700 dark:text-green-400 font-mono">
                        {formatCurrency(invoice.total_amount)}
                      </td>
                      <td className="px-3 py-3 text-center">
                        {getStatusBadge(invoice.sent_status)}
                      </td>
                      <td className="px-3 py-3 text-center" onClick={(e) => e.stopPropagation()}>
                        <Button
                          variant="outline"
                          size="sm"
                          className="h-8 text-xs gap-1 border-primary/30 text-primary hover:bg-primary/10"
                          onClick={() => setSelectedInvoice(invoice)}
                        >
                          <Eye className="h-3.5 w-3.5" />
                          Xem chi tiết
                        </Button>
                      </td>
                    </tr>
                  ))}
                </tbody>
                <tfoot>
                  <tr className="border-t-2 bg-muted/50 font-medium">
                    <td colSpan={5} className="px-3 py-3 text-right hidden md:table-cell">
                      Tổng cộng:
                    </td>
                    <td colSpan={5} className="px-3 py-3 text-right md:hidden">
                      Tổng cộng:
                    </td>
                    <td className="px-3 py-3 text-right hidden md:table-cell font-mono font-bold">
                      {invoices.reduce((sum, inv) => sum + inv.consumption, 0)}{" "}
                      kWh
                    </td>
                    <td className="px-3 py-3 text-right font-mono font-bold text-green-700 dark:text-green-400">
                      {formatCurrency(totalAmount)}
                    </td>
                    <td colSpan={2}></td>
                  </tr>
                </tfoot>
              </table>
            </div>
          )}
        </CardContent>
      </Card>

      {/* Generate dialog */}
      <Dialog open={showGenerateDialog} onOpenChange={setShowGenerateDialog}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>Tạo hóa đơn</DialogTitle>
            <DialogDescription>
              Tạo hóa đơn cho tất cả phòng trong tòa nhà
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-4 py-4">
            <div className="space-y-2">
              <Label>Tòa nhà</Label>
              <Select
                value={selectedBuilding}
                onValueChange={setSelectedBuilding}
              >
                <SelectTrigger>
                  <SelectValue placeholder="Chọn tòa nhà" />
                </SelectTrigger>
                <SelectContent>
                  {buildings.map((b) => (
                    <SelectItem key={b.id} value={b.id.toString()}>
                      {b.name}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-2">
              <Label>Tháng</Label>
              <Input
                type="month"
                value={selectedMonth}
                onChange={(e) => setSelectedMonth(e.target.value)}
              />
            </div>
            <div className="space-y-2">
              <Label>Bảng giá</Label>
              <Select
                value={selectedPriceConfig}
                onValueChange={setSelectedPriceConfig}
              >
                <SelectTrigger>
                  <SelectValue placeholder="Chọn bảng giá" />
                </SelectTrigger>
                <SelectContent>
                  {priceConfigs.map((pc) => (
                    <SelectItem key={pc.id} value={pc.id.toString()}>
                      {pc.config_name} ({pc.pricing_type === "tiered" ? "bậc thang" : "cố định"})
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-2">
              <Label>Phụ phí (VND)</Label>
              <Input
                type="number"
                value={surcharge}
                onChange={(e) => setSurcharge(e.target.value)}
                placeholder="0"
              />
              <p className="text-xs text-muted-foreground">
                Phụ phí cộng thêm cho mỗi phòng (phí dịch vụ, vệ sinh, v.v.)
              </p>
            </div>
          </div>
          <DialogFooter>
            <Button
              variant="outline"
              onClick={() => setShowGenerateDialog(false)}
            >
              Hủy
            </Button>
            <Button onClick={handleGenerate} disabled={isGenerating}>
              {isGenerating ? (
                <div className="flex items-center gap-2">
                  <Loader2 className="h-4 w-4 animate-spin" />
                  Đang tạo...
                </div>
              ) : (
                "Tạo hóa đơn"
              )}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Single Room Detailed Invoice Modal */}
      <Dialog open={!!selectedInvoice} onOpenChange={(open) => !open && setSelectedInvoice(null)}>
        {selectedInvoice && (
          <DialogContent className="sm:max-w-lg max-h-[90vh] overflow-y-auto">
            <DialogHeader className="border-b pb-3">
              <div className="flex items-center justify-between">
                <div>
                  <DialogTitle className="text-xl font-bold text-primary flex items-center gap-2">
                    <FileText className="h-5 w-5" />
                    HÓA ĐƠN PHÒNG {selectedInvoice.room_number || "N/A"}
                  </DialogTitle>
                  <DialogDescription className="text-xs">
                    Kỳ tính tiền: Tháng {selectedInvoice.invoice_month}
                  </DialogDescription>
                </div>
                <div>
                  {getStatusBadge(selectedInvoice.sent_status)}
                </div>
              </div>
            </DialogHeader>

            <div className="space-y-4 py-2 text-sm">
              {/* Tenant info */}
              <div className="grid grid-cols-2 gap-3 bg-muted/40 p-3 rounded-lg border text-xs">
                <div>
                  <span className="text-muted-foreground block">Tên cư dân:</span>
                  <span className="font-semibold text-sm text-foreground">{selectedInvoice.resident_name || "N/A"}</span>
                </div>
                <div>
                  <span className="text-muted-foreground block">Tòa nhà:</span>
                  <span className="font-medium text-foreground">{filteredBuildingName || "—"}</span>
                </div>
              </div>

              {/* Meter details */}
              <div className="grid grid-cols-3 gap-2 bg-primary/5 p-3 rounded-lg border border-primary/20 text-center">
                <div>
                  <span className="text-xs text-muted-foreground block">Chỉ số cũ</span>
                  <span className="font-mono text-base font-semibold">{selectedInvoice.previous_reading} kWh</span>
                </div>
                <div>
                  <span className="text-xs text-muted-foreground block">Chỉ số mới</span>
                  <span className="font-mono text-base font-semibold">{selectedInvoice.current_reading} kWh</span>
                </div>
                <div className="bg-primary/10 rounded-md py-1">
                  <span className="text-xs text-primary font-semibold block">Tiêu thụ</span>
                  <span className="font-mono text-base font-bold text-primary">{selectedInvoice.consumption} kWh</span>
                </div>
              </div>

              {/* Price calculation breakdown */}
              <div className="border rounded-lg overflow-hidden text-xs">
                <div className="bg-muted px-3 py-2 font-bold uppercase tracking-wider text-muted-foreground border-b">
                  Chi tiết diễn giải tính tiền điện (Bậc thang EVN)
                </div>
                <div className="p-3 space-y-1.5">
                  {(() => {
                    try {
                      if (selectedInvoice.price_breakdown) {
                        const bd = JSON.parse(selectedInvoice.price_breakdown) as PriceBreakdown
                        return (
                          <div className="space-y-1">
                            {bd.tiers && bd.tiers.map((t, idx) => (
                              <div key={idx} className="flex justify-between py-1 border-b border-dashed">
                                <span>{t.name} ({t.kwh} kWh x {t.price?.toLocaleString()}đ)</span>
                                <span className="font-mono font-medium">{t.amount?.toLocaleString()} VNĐ</span>
                              </div>
                            ))}
                            {bd.subtotal && (
                              <div className="flex justify-between font-semibold pt-1 text-sm">
                                <span>Cộng tiền điện:</span>
                                <span className="font-mono">{bd.subtotal?.toLocaleString()} VNĐ</span>
                              </div>
                            )}
                            {bd.vat_amount && (
                              <div className="flex justify-between text-muted-foreground">
                                <span>Thuế VAT ({((bd.vat_rate || 0.08) * 100)}%):</span>
                                <span className="font-mono">{bd.vat_amount?.toLocaleString()} VNĐ</span>
                              </div>
                            )}
                          </div>
                        )
                      }
                    } catch {}
                    return (
                      <div className="flex justify-between font-medium">
                        <span>Tiền điện ({selectedInvoice.consumption} kWh):</span>
                        <span className="font-mono">{formatCurrency(selectedInvoice.electricity_amount || selectedInvoice.total_amount)}</span>
                      </div>
                    )
                  })()}
                </div>
              </div>

              {/* Additional fees */}
              {selectedInvoice.additional_fees && (
                <div className="border rounded-lg overflow-hidden text-xs">
                  <div className="bg-muted px-3 py-2 font-bold uppercase tracking-wider text-muted-foreground border-b">
                    Phụ phí & Dịch vụ khác
                  </div>
                  <div className="p-3 space-y-1">
                    {(() => {
                      try {
                        const fees = JSON.parse(selectedInvoice.additional_fees)
                        return Object.entries(fees).map(([k, v]) => (
                          <div key={k} className="flex justify-between">
                            <span>{k}:</span>
                            <span className="font-mono font-medium">{Number(v).toLocaleString()} VNĐ</span>
                          </div>
                        ))
                      } catch {
                        return <div>{selectedInvoice.additional_fees}</div>
                      }
                    })()}
                  </div>
                </div>
              )}

              {/* Total Box */}
              <div className="flex items-center justify-between p-4 bg-green-500/10 border border-green-500/30 rounded-xl">
                <span className="font-bold text-sm text-green-800 dark:text-green-300">TỔNG THÀNH TIỀN:</span>
                <span className="text-xl font-black text-green-600 dark:text-green-400 font-mono">
                  {formatCurrency(selectedInvoice.total_amount)}
                </span>
              </div>
            </div>

            <DialogFooter className="gap-2 sm:gap-0">
              <Button
                variant="outline"
                className="gap-1 text-xs"
                onClick={async () => {
                  try {
                    const blob = await apiDownload(`/invoices/${selectedInvoice.id}/pdf`)
                    const url = window.URL.createObjectURL(blob)
                    const a = document.createElement("a")
                    a.href = url
                    const month = selectedInvoice.invoice_month.replace("-", "")
                    const room = (selectedInvoice.room_number || "phong").replace(/\s/g, "_")
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
                <Printer className="h-3.5 w-3.5" />
                Xuất PDF
              </Button>
              <Button onClick={() => setSelectedInvoice(null)} className="text-xs">
                Đóng
              </Button>
            </DialogFooter>
          </DialogContent>
        )}
      </Dialog>
    </div>
  )
}
