"use client"

import React, { useState, useCallback, useEffect } from "react"
import { useRouter } from "next/navigation"
import { useDropzone } from "react-dropzone"
import {
  Upload,
  X,
  ImageIcon,
  CheckCircle2,
  AlertCircle,
  Loader2,
  Pencil,
  Check,
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
import { Progress } from "@/components/ui/progress"
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
  DialogFooter,
} from "@/components/ui/dialog"
import { apiGet, apiUpload, apiPatch } from "@/lib/api"
import { toast } from "@/components/ui/use-toast"

interface Building {
  id: number
  name: string
  address: string
}

interface Room {
  id: number
  room_number: string
  resident_name?: string | null
}

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

const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8001/api/v1"

function ProtectedReadingImage({
  imagePath,
  alt,
}: {
  imagePath: string | null
  alt: string
}) {
  const [objectUrl, setObjectUrl] = useState<string | null>(null)

  useEffect(() => {
    let active = true
    let loadedUrl: string | null = null

    if (!imagePath || !imagePath.startsWith("/readings/")) {
      setObjectUrl(null)
      return
    }

    setObjectUrl(null)
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
    return (
      <div className="flex h-full items-center justify-center">
        <ImageIcon className="h-8 w-8 text-muted-foreground/50" />
      </div>
    )
  }

  return <img src={objectUrl} alt={alt} className="h-full w-full object-cover" />
}

export default function UploadPage() {
  const router = useRouter()
  const [buildings, setBuildings] = useState<Building[]>([])
  const [rooms, setRooms] = useState<Room[]>([])
  const [selectedBuilding, setSelectedBuilding] = useState<string>("")
  const [readingDate, setReadingDate] = useState<string>(
    new Date().toISOString().split("T")[0]
  )
  const [files, setFiles] = useState<PreviewFile[]>([])
  const [isUploading, setIsUploading] = useState(false)
  const [batchStatus, setBatchStatus] = useState<BatchStatus | null>(null)
  const [editingResult, setEditingResult] = useState<ReadingResult | null>(null)
  const [editValue, setEditValue] = useState<string>("")
  const [editRoomId, setEditRoomId] = useState<string>("")
  const [showEditDialog, setShowEditDialog] = useState(false)
  const [selectedResultIds, setSelectedResultIds] = useState<Set<number | string>>(new Set())
  const [isBatchApproving, setIsBatchApproving] = useState(false)

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

  const unapprovedResults = batchStatus?.results.filter((r) => r.status !== "approved") || []
  const isAllSelected = unapprovedResults.length > 0 && unapprovedResults.every((r) => selectedResultIds.has(r.id ?? r.staged_id ?? ""))

  const handleSelectAllToggle = () => {
    if (isAllSelected) {
      setSelectedResultIds(new Set())
    } else {
      const allIds = unapprovedResults.map((r) => r.id ?? r.staged_id).filter(Boolean) as (number | string)[]
      setSelectedResultIds(new Set(allIds))
    }
  }

  const handleApproveSelected = async () => {
    if (!batchStatus || selectedResultIds.size === 0) return
    setIsBatchApproving(true)
    try {
      const toApprove = batchStatus.results.filter(
        (r) => r.status !== "approved" && selectedResultIds.has(r.id ?? r.staged_id ?? "")
      )
      let count = 0
      for (const item of toApprove) {
        if (item.id) {
          await apiPatch(`/readings/${item.id}`, { status: "approved" })
          count++
        } else if (item.staged_id && item.room_id && item.meter_value !== null) {
          await apiPatch(`/readings/staged/${item.staged_id}`, {
            room_id: item.room_id,
            meter_value: item.meter_value,
            status: "approved",
          })
          count++
        }
      }
      toast({
        title: "Xác nhận hàng loạt thành công",
        description: `Đã xác nhận ${count} phòng được chọn!`,
        variant: "success",
      })
      setSelectedResultIds(new Set())
      if (batchStatus.job_id) {
        const updatedStatus = await apiGet<BatchStatus>(`/readings/batch-status/${batchStatus.job_id}`)
        setBatchStatus(updatedStatus)
      }
    } catch {
      toast({ title: "Lỗi", description: "Không thể xác nhận một số phòng", variant: "destructive" })
    } finally {
      setIsBatchApproving(false)
    }
  }

  const handleApproveAll = async () => {
    if (!batchStatus) return
    const unapproved = batchStatus.results.filter((r) => r.status !== "approved")
    if (unapproved.length === 0) {
      toast({ title: "Thông báo", description: "Tất cả các phòng đã được xác nhận!", variant: "default" })
      return
    }
    setIsBatchApproving(true)
    try {
      let count = 0
      for (const item of unapproved) {
        if (item.id) {
          await apiPatch(`/readings/${item.id}`, { status: "approved" })
          count++
        } else if (item.staged_id && item.room_id && item.meter_value !== null) {
          await apiPatch(`/readings/staged/${item.staged_id}`, {
            room_id: item.room_id,
            meter_value: item.meter_value,
            status: "approved",
          })
          count++
        }
      }
      toast({
        title: "Xác nhận tất cả thành công",
        description: `Đã tự động xác nhận toàn bộ ${count} phòng!`,
        variant: "success",
      })
      setSelectedResultIds(new Set())
      if (batchStatus.job_id) {
        const updatedStatus = await apiGet<BatchStatus>(`/readings/batch-status/${batchStatus.job_id}`)
        setBatchStatus(updatedStatus)
      }
    } catch {
      toast({ title: "Lỗi", description: "Không thể xác nhận một số phòng", variant: "destructive" })
    } finally {
      setIsBatchApproving(false)
    }
  }

  useEffect(() => {
    fetchBuildings()
  }, [])

  useEffect(() => {
    if (!selectedBuilding) {
      setRooms([])
      return
    }
    apiGet<Room[]>(`/buildings/${selectedBuilding}/rooms`)
      .then(setRooms)
      .catch(() => setRooms([]))
  }, [selectedBuilding])

  const fetchBuildings = async () => {
    try {
      const data = await apiGet<Building[]>("/buildings")
      setBuildings(data)
    } catch (error) {
      toast({
        title: "Lỗi",
        description: "Không thể tải danh sách tòa nhà",
        variant: "destructive",
      })
    }
  }

  const onDrop = useCallback(
    (acceptedFiles: File[]) => {
      const newFiles: PreviewFile[] = acceptedFiles.map((file) => ({
        file,
        preview: URL.createObjectURL(file),
      }))
      setFiles((prev) => [...prev, ...newFiles])
    },
    []
  )

  const { getRootProps, getInputProps, isDragActive } = useDropzone({
    onDrop,
    accept: {
      "image/*": [".jpeg", ".jpg", ".png", ".webp"],
    },
    multiple: true,
  })

  const removeFile = (index: number) => {
    setFiles((prev) => {
      const updated = [...prev]
      URL.revokeObjectURL(updated[index].preview)
      updated.splice(index, 1)
      return updated
    })
  }

  const clearFiles = () => {
    files.forEach((f) => URL.revokeObjectURL(f.preview))
    setFiles([])
  }

  const handleUpload = async () => {
    if (!selectedBuilding) {
      toast({
        title: "Thiếu thông tin",
        description: "Vui lòng chọn tòa nhà",
        variant: "destructive",
      })
      return
    }

    if (files.length === 0) {
      toast({
        title: "Thiếu ảnh",
        description: "Vui lòng chọn ít nhất một ảnh",
        variant: "destructive",
      })
      return
    }

    setIsUploading(true)
    setBatchStatus(null)

    try {
      const formData = new FormData()
      formData.append("building_id", selectedBuilding)
      formData.append("reading_date", readingDate)
      files.forEach((f) => {
        formData.append("files", f.file)
      })

      const response = await apiUpload<{ job_id: string }>(
        "/readings/batch-upload",
        formData
      )

      toast({
        title: "Upload thành công",
        description: "Đang xử lý ảnh bằng AI...",
        variant: "success",
      })

      // Start polling for batch status
      pollBatchStatus(response.job_id)
    } catch (error) {
      setIsUploading(false)
      toast({
        title: "Upload thất bại",
        description:
          error instanceof Error ? error.message : "Không thể upload ảnh",
        variant: "destructive",
      })
    }
  }

  const pollBatchStatus = async (jobId: string) => {
    const pollInterval = setInterval(async () => {
      try {
        const status = await apiGet<BatchStatus>(
          `/readings/batch-status/${jobId}`
        )
        setBatchStatus(status)

        if (status.status === "completed" || status.status === "failed") {
          clearInterval(pollInterval)
          setIsUploading(false)

          if (status.status === "completed") {
            toast({
              title: "Xử lý hoàn tất",
              description: `Đã xử lý ${status.processed}/${status.total} ảnh`,
              variant: "success",
            })
          } else {
            toast({
              title: "Xử lý thất bại",
              description: "Có lỗi xảy ra khi xử lý ảnh",
              variant: "destructive",
            })
          }
        }
      } catch (error) {
        clearInterval(pollInterval)
        setIsUploading(false)
        toast({
          title: "Lỗi",
          description: "Không thể kiểm tra trạng thái xử lý",
          variant: "destructive",
        })
      }
    }, 2000)
  }

  const handleApprove = async (resultId: number) => {
    try {
      const updated = await apiPatch<ReadingResult>(`/readings/${resultId}`, {
        status: "approved",
      })
      setBatchStatus((prev) => {
        if (!prev) return prev
        return {
          ...prev,
          results: prev.results.map((r) =>
            r.id === resultId ? updated : r
          ),
        }
      })
      toast({
        title: "Đã xác nhận",
        description: "Chỉ số đã được xác nhận",
        variant: "success",
      })
    } catch (error) {
      toast({
        title: "Lỗi",
        description: "Không thể xác nhận chỉ số",
        variant: "destructive",
      })
    }
  }

  const openEditDialog = (result: ReadingResult) => {
    setEditingResult(result)
    setEditValue(result.meter_value?.toString() || "")
    setEditRoomId(result.room_id?.toString() || "")
    setShowEditDialog(true)
  }

  const handleEditSave = async () => {
    if (!editingResult) return

    const meterValue = Number(editValue)
    if (!editRoomId || !Number.isInteger(meterValue) || meterValue < 0) {
      toast({
        title: "Thiếu thông tin",
        description: "Vui lòng chọn phòng và nhập chỉ số điện hợp lệ",
        variant: "destructive",
      })
      return
    }

    try {
      const endpoint = editingResult.staged_id
        ? `/readings/staged/${editingResult.staged_id}`
        : `/readings/${editingResult.id}`
      const updated = await apiPatch<ReadingResult>(endpoint, {
        room_id: Number(editRoomId),
        meter_value: meterValue,
        meter_type: "electric",
        status: "approved",
      })
      setBatchStatus((prev) => {
        if (!prev) return prev
        return {
          ...prev,
          results: prev.results.map((r) =>
            (editingResult.staged_id && r.staged_id === editingResult.staged_id) ||
            (!editingResult.staged_id && r.id === editingResult.id)
              ? updated
              : r
          ),
        }
      })
      setShowEditDialog(false)
      toast({
        title: "Đã cập nhật",
        description: "Chỉ số đã được cập nhật thành công",
        variant: "success",
      })
    } catch (error) {
      toast({
        title: "Lỗi",
        description: "Không thể cập nhật chỉ số",
        variant: "destructive",
      })
    }
  }

  const getStatusBadge = (status: string) => {
    switch (status) {
      case "success":
        return <Badge variant="success">Nhận dạng OK</Badge>
      case "approved":
        return <Badge variant="success">Đã xác nhận</Badge>
      case "error":
        return <Badge variant="destructive">Lỗi</Badge>
      case "pending":
        return <Badge variant="warning">Đang xử lý</Badge>
      case "needs_review":
        return <Badge variant="outline" className="text-amber-600 border-amber-200">Cần xem lại</Badge>
      default:
        return <Badge variant="outline">{status}</Badge>
    }
  }

  const progressPercent = batchStatus
    ? Math.round((batchStatus.processed / batchStatus.total) * 100)
    : 0

  return (
    <div className="space-y-6">
      {/* Page header */}
      <div>
        <h1 className="text-3xl font-bold tracking-tight">Upload ảnh</h1>
        <p className="text-muted-foreground">
          Tải lên ảnh đồng hồ điện để AI nhận dạng chỉ số tự động
        </p>
      </div>

      {/* Upload form */}
      <div className="grid gap-6 lg:grid-cols-3">
        {/* Settings */}
        <Card className="lg:col-span-1">
          <CardHeader>
            <CardTitle>Cài đặt</CardTitle>
            <CardDescription>Chọn tòa nhà và ngày ghi</CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
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
                  {buildings.map((building) => (
                    <SelectItem
                      key={building.id}
                      value={building.id.toString()}
                    >
                      {building.name}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-2">
              <Label>Ngày ghi chỉ số</Label>
              <Input
                type="date"
                value={readingDate}
                onChange={(e) => setReadingDate(e.target.value)}
              />
            </div>
            <div className="pt-2">
              <p className="text-sm text-muted-foreground">
                Số ảnh đã chọn: <strong>{files.length}</strong>
              </p>
            </div>
          </CardContent>
        </Card>

        {/* Dropzone */}
        <Card className="lg:col-span-2">
          <CardHeader>
            <div className="flex items-center justify-between">
              <div>
                <CardTitle>Ảnh đồng hồ điện</CardTitle>
                <CardDescription>
                  Kéo thả hoặc click để chọn ảnh (JPEG, PNG, WebP)
                </CardDescription>
              </div>
              {files.length > 0 && (
                <Button variant="outline" size="sm" onClick={clearFiles}>
                  Xóa tất cả
                </Button>
              )}
            </div>
          </CardHeader>
          <CardContent>
            {/* Dropzone area */}
            <div
              {...getRootProps()}
              className={`cursor-pointer rounded-lg border-2 border-dashed p-8 text-center transition-colors ${isDragActive
                ? "border-primary bg-primary/5"
                : "border-muted-foreground/25 hover:border-primary/50"
                }`}
            >
              <input {...getInputProps()} />
              <Upload className="mx-auto h-10 w-10 text-muted-foreground/50" />
              <p className="mt-3 text-sm font-medium">
                {isDragActive
                  ? "Thả ảnh tại đây..."
                  : "Kéo thả ảnh hoặc click để chọn"}
              </p>
              <p className="mt-1 text-xs text-muted-foreground">
                Hỗ trợ: JPEG, PNG, WebP - Có thể chọn nhiều ảnh
              </p>
            </div>

            {/* Preview grid */}
            {files.length > 0 && (
              <div className="mt-4 grid grid-cols-2 gap-3 sm:grid-cols-3 md:grid-cols-4">
                {files.map((f, index) => (
                  <div
                    key={index}
                    className="group relative aspect-square overflow-hidden rounded-lg border bg-muted"
                  >
                    <img
                      src={f.preview}
                      alt={`Preview ${index + 1}`}
                      className="h-full w-full object-cover"
                    />
                    <button
                      onClick={(e) => {
                        e.stopPropagation()
                        removeFile(index)
                      }}
                      className="absolute right-1 top-1 rounded-full bg-black/60 p-1 text-white opacity-0 transition-opacity group-hover:opacity-100"
                    >
                      <X className="h-3 w-3" />
                    </button>
                    <div className="absolute bottom-0 left-0 right-0 bg-black/60 px-2 py-1">
                      <p className="truncate text-xs text-white">
                        {f.file.name}
                      </p>
                    </div>
                  </div>
                ))}
              </div>
            )}

            {/* Upload button */}
            {files.length > 0 && (
              <div className="mt-4">
                <Button
                  onClick={handleUpload}
                  disabled={isUploading || !selectedBuilding}
                  className="w-full"
                  size="lg"
                >
                  {isUploading ? (
                    <div className="flex items-center gap-2">
                      <Loader2 className="h-4 w-4 animate-spin" />
                      Đang xử lý...
                    </div>
                  ) : (
                    <div className="flex items-center gap-2">
                      <Upload className="h-4 w-4" />
                      Bắt đầu xử lý ({files.length} ảnh)
                    </div>
                  )}
                </Button>
              </div>
            )}
          </CardContent>
        </Card>
      </div>

      {/* Processing status */}
      {batchStatus && (
        <Card>
          <CardHeader>
            <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
              <div>
                <CardTitle className="flex items-center gap-2">
                  {batchStatus.status === "processing" ? (
                    <Loader2 className="h-5 w-5 animate-spin text-primary" />
                  ) : batchStatus.status === "completed" ? (
                    <CheckCircle2 className="h-5 w-5 text-green-500" />
                  ) : (
                    <AlertCircle className="h-5 w-5 text-red-500" />
                  )}
                  Kết quả xử lý
                </CardTitle>
                <CardDescription>
                  {batchStatus.status === "processing"
                    ? `Đang xử lý ${batchStatus.processed}/${batchStatus.total} ảnh...`
                    : batchStatus.status === "completed"
                      ? `Hoàn tất - Đã chốt chỉ số cho ${batchStatus.total} phòng`
                      : "Xử lý thất bại"}
                </CardDescription>
              </div>
              {batchStatus.status === "completed" && (
                <Button
                  onClick={() => router.push("/invoices")}
                  size="lg"
                  className="bg-green-600 hover:bg-green-700 text-white font-semibold shadow-md"
                >
                  🧾 Lập Hóa Đơn Cho Các Phòng Này ➔
                </Button>
              )}
            </div>
          </CardHeader>
          <CardContent>
            {/* Progress bar */}
            {batchStatus.status === "processing" && (
              <div className="mb-6 space-y-2">
                <Progress value={progressPercent} />
                <p className="text-sm text-muted-foreground text-center">
                  {progressPercent}%
                </p>
              </div>
            )}

            {/* Batch Action Bar */}
            {batchStatus.results && unapprovedResults.length > 0 && (
              <div className="mb-4 flex flex-wrap items-center justify-between gap-3 p-3 bg-muted/40 rounded-xl border border-primary/20">
                <div className="flex items-center gap-3">
                  <label className="flex items-center gap-2 text-sm font-semibold cursor-pointer select-none">
                    <input
                      type="checkbox"
                      checked={isAllSelected}
                      onChange={handleSelectAllToggle}
                      className="h-4 w-4 rounded border-gray-300 text-primary focus:ring-primary"
                    />
                    Chọn tất cả ({unapprovedResults.length} phòng chờ xác nhận)
                  </label>
                </div>

                <div className="flex items-center gap-2">
                  {selectedResultIds.size > 0 && (
                    <Button
                      onClick={handleApproveSelected}
                      disabled={isBatchApproving}
                      size="sm"
                      className="bg-blue-600 hover:bg-blue-700 text-white font-semibold gap-1 shadow-xs"
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

            {/* Results grid */}
            {batchStatus.results && batchStatus.results.length > 0 ? (
              <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
                {batchStatus.results.map((result) => {
                  const idKey = result.id ?? result.staged_id ?? ""
                  const isSelected = selectedResultIds.has(idKey)
                  return (
                    <div
                      key={idKey}
                      className={`overflow-hidden rounded-xl border transition-all ${
                        isSelected ? "ring-2 ring-primary border-primary bg-primary/5" : "hover:border-primary/40"
                      }`}
                    >
                      {/* Image */}
                      <div className="relative aspect-video bg-muted">
                        <ProtectedReadingImage
                          imagePath={result.image_path}
                          alt={result.room_number ? `Phòng ${result.room_number}` : "Ảnh chỉ số chưa gán phòng"}
                        />
                      </div>

                      {/* Info */}
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
                            <span className="font-bold text-base text-primary">
                              {result.room_number ? `Phòng ${result.room_number}` : "Chưa gán phòng"}
                            </span>
                          </div>
                          {getStatusBadge(result.status)}
                        </div>

                      {result.meter_value !== null && result.meter_value !== undefined && (
                        <div className="flex items-center gap-2">
                          <span className="text-sm text-muted-foreground">
                            Chỉ số:
                          </span>
                          <span className="text-lg font-bold">
                            {result.meter_value} kWh
                          </span>
                        </div>
                      )}

                      {result.confidence_score !== null && result.confidence_score !== undefined && (
                        <div className="flex items-center gap-2">
                          <span className="text-sm text-muted-foreground">
                            Độ tin cậy:
                          </span>
                          <span
                            className={`text-sm font-medium ${result.confidence_score >= 0.9
                              ? "text-green-600"
                              : result.confidence_score >= 0.7
                                ? "text-yellow-600"
                                : "text-red-600"
                              }`}
                          >
                            {Math.round(result.confidence_score * 100)}%
                          </span>
                        </div>
                      )}

                      {result.notes && (
                        <p className={`text-xs ${result.status === 'error' || result.status === 'needs_review' ? 'text-red-500' : 'text-muted-foreground'}`}>
                          {result.notes}
                        </p>
                      )}

                      {/* Action buttons */}
                      {result.status !== "approved" && (
                        <div className="flex gap-2 pt-1">
                          {result.id !== null && (
                            <Button
                              size="sm"
                              onClick={() => handleApprove(result.id as number)}
                              className="flex-1"
                            >
                              <Check className="mr-1 h-3 w-3" />
                              Xác nhận
                            </Button>
                          )}
                          <Button
                            size="sm"
                            variant="outline"
                            onClick={() => openEditDialog(result)}
                            className="flex-1"
                          >
                            <Pencil className="mr-1 h-3 w-3" />
                            Sửa
                          </Button>
                        </div>
                      )}
                    </div>
                  </div>
                )
              })}
              </div>
            ) : batchStatus.status === "completed" ? (
              <div className="py-8 text-center bg-destructive/10 rounded-lg text-destructive">
                Tất cả các ảnh tải lên đều bị lỗi hoặc <strong>không tìm thấy phòng trọ tương ứng</strong>. Vui lòng đảm bảo các phòng trọ đã được tạo trên hệ thống hoặc tên file ảnh có chứa đúng số của phòng trọ.
              </div>
            ) : null}
          </CardContent>
        </Card>
      )}

      {/* Edit dialog */}
      <Dialog open={showEditDialog} onOpenChange={setShowEditDialog}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>
              {editingResult?.room_number
                ? `Sửa chỉ số - Phòng ${editingResult.room_number}`
                : "Gán phòng và duyệt chỉ số"}
            </DialogTitle>
          </DialogHeader>
          <div className="space-y-4 py-4">
            <div className="space-y-2">
              <Label>Phòng</Label>
              <Select value={editRoomId} onValueChange={setEditRoomId}>
                <SelectTrigger>
                  <SelectValue placeholder="Chọn phòng" />
                </SelectTrigger>
                <SelectContent>
                  {rooms.map((room) => (
                    <SelectItem key={room.id} value={room.id.toString()}>
                      Phòng {room.room_number}
                      {room.resident_name ? ` — ${room.resident_name}` : ""}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-2">
              <Label>Chỉ số (kWh)</Label>
              <Input
                type="number"
                step="0.1"
                value={editValue}
                onChange={(e) => setEditValue(e.target.value)}
                placeholder="Nhập chỉ số"
              />
            </div>
          </div>
          <DialogFooter>
            <Button
              variant="outline"
              onClick={() => setShowEditDialog(false)}
            >
              Hủy
            </Button>
            <Button onClick={handleEditSave}>Lưu & Duyệt</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div >
  )
}
