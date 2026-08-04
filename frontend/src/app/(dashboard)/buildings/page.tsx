"use client"

import React, { useState, useEffect } from "react"
import {
  Building2,
  Plus,
  Pencil,
  Trash2,
  DoorOpen,
  ChevronLeft,
  ChevronDown,
  ChevronRight,
  Loader2,
  Search,
  Users,
  Upload,
  FileSpreadsheet,
  AlertCircle,
  Download,
} from "lucide-react"
import * as XLSX from "xlsx"
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
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogFooter,
} from "@/components/ui/dialog"
import { apiGet, apiPost, apiPatch, apiDelete, apiUpload } from "@/lib/api"
import { toast } from "@/components/ui/use-toast"

interface Building {
  id: number
  name: string
  address: string | null
  room_count: number
  created_at: string
}

type ExcelCell = string | number | boolean | null | undefined
type ExcelPreviewRow = ExcelCell[]

interface ImportRoomsResponse {
  message: string
  created: number
  updated: number
  errors: string[]
}

interface Room {
  id: number
  room_number: string
  resident_name: string
  resident_phone: string
  resident_email: string
  telegram_id: string
  initial_reading: number
  previous_reading: number | null
  current_reading: number | null
  consumption: number | null
  readings_history: {
    id: number
    reading_date: string
    meter_value: number
    confidence_score: number | null
    status: string
  }[]
  building_id: number
  is_active: boolean
}

export default function BuildingsPage() {
  const [buildings, setBuildings] = useState<Building[]>([])
  const [rooms, setRooms] = useState<Room[]>([])
  const [isLoading, setIsLoading] = useState(true)
  const [selectedBuilding, setSelectedBuilding] = useState<Building | null>(
    null
  )
  const [searchQuery, setSearchQuery] = useState("")

  // Expanded rooms state
  const [expandedRows, setExpandedRows] = useState<Set<number>>(new Set())

  const toggleRow = (id: number) => {
    const newExpandedRows = new Set(expandedRows)
    if (newExpandedRows.has(id)) {
      newExpandedRows.delete(id)
    } else {
      newExpandedRows.add(id)
    }
    setExpandedRows(newExpandedRows)
  }

  // Building dialog
  const [showBuildingDialog, setShowBuildingDialog] = useState(false)
  const [editingBuilding, setEditingBuilding] = useState<Building | null>(null)
  const [buildingForm, setBuildingForm] = useState({
    name: "",
    address: "",
  })

  // Room dialog
  const [showRoomDialog, setShowRoomDialog] = useState(false)
  const [editingRoom, setEditingRoom] = useState<Room | null>(null)
  const [roomForm, setRoomForm] = useState({
    room_number: "",
    resident_name: "",
    resident_phone: "",
    resident_email: "",
    telegram_id: "",
    initial_reading: 0,
  })

  // Import dialog
  const [showImportDialog, setShowImportDialog] = useState(false)
  const [importFile, setImportFile] = useState<File | null>(null)
  const [importPreviewData, setImportPreviewData] = useState<ExcelPreviewRow[]>([])
  const [isImporting, setIsImporting] = useState(false)

  // Delete confirmation
  const [showDeleteDialog, setShowDeleteDialog] = useState(false)
  const [deleteTarget, setDeleteTarget] = useState<{
    type: "building" | "room"
    id: number
    name: string
  } | null>(null)

  useEffect(() => {
    fetchBuildings()
  }, [])

  useEffect(() => {
    if (selectedBuilding) {
      fetchRooms(selectedBuilding.id)
    }
  }, [selectedBuilding])

  const fetchBuildings = async () => {
    setIsLoading(true)
    try {
      const data = await apiGet<Building[]>("/buildings")
      setBuildings(data)
    } catch (error) {
      toast({
        title: "Lỗi",
        description: "Không thể tải danh sách tòa nhà",
        variant: "destructive",
      })
    } finally {
      setIsLoading(false)
    }
  }

  const fetchRooms = async (buildingId: number) => {
    try {
      const data = await apiGet<Room[]>(`/buildings/${buildingId}/rooms`)
      setRooms(data)
    } catch (error) {
      toast({
        title: "Lỗi",
        description: "Không thể tải danh sách phòng",
        variant: "destructive",
      })
    }
  }

  // Building CRUD
  const openCreateBuilding = () => {
    setEditingBuilding(null)
    setBuildingForm({ name: "", address: "" })
    setShowBuildingDialog(true)
  }

  const openEditBuilding = (building: Building) => {
    setEditingBuilding(building)
    setBuildingForm({ name: building.name, address: building.address ?? "" })
    setShowBuildingDialog(true)
  }

  const handleSaveBuilding = async () => {
    if (!buildingForm.name) {
      toast({
        title: "Lỗi",
        description: "Vui lòng nhập tên tòa nhà",
        variant: "destructive",
      })
      return
    }

    try {
      if (editingBuilding) {
        await apiPatch(`/buildings/${editingBuilding.id}`, buildingForm)
        toast({
          title: "Cập nhật thành công",
          description: "Tòa nhà đã được cập nhật",
          variant: "success",
        })
      } else {
        await apiPost("/buildings", buildingForm)
        toast({
          title: "Tạo thành công",
          description: "Tòa nhà mới đã được tạo",
          variant: "success",
        })
      }
      setShowBuildingDialog(false)
      fetchBuildings()
    } catch (error) {
      toast({
        title: "Lỗi",
        description:
          error instanceof Error ? error.message : "Không thể lưu tòa nhà",
        variant: "destructive",
      })
    }
  }

  // Room CRUD
  const openCreateRoom = () => {
    setEditingRoom(null)
    setRoomForm({
      room_number: "",
      resident_name: "",
      resident_phone: "",
      resident_email: "",
      telegram_id: "",
      initial_reading: 0,
    })
    setShowRoomDialog(true)
  }

  const openEditRoom = (room: Room) => {
    setEditingRoom(room)
    setRoomForm({
      room_number: room.room_number,
      resident_name: room.resident_name || "",
      resident_phone: room.resident_phone || "",
      resident_email: room.resident_email || "",
      telegram_id: room.telegram_id || "",
      initial_reading: room.initial_reading || 0,
    })
    setShowRoomDialog(true)
  }

  const handleSaveRoom = async () => {
    if (!roomForm.room_number || !selectedBuilding) {
      toast({
        title: "Lỗi",
        description: "Vui lòng nhập số phòng",
        variant: "destructive",
      })
      return
    }

    try {
      if (editingRoom) {
        await apiPatch(`/rooms/${editingRoom.id}`, roomForm)
        toast({
          title: "Cập nhật thành công",
          description: "Phòng đã được cập nhật",
          variant: "success",
        })
      } else {
        await apiPost(`/buildings/${selectedBuilding.id}/rooms`, roomForm)
        toast({
          title: "Tạo thành công",
          description: "Phòng mới đã được tạo",
          variant: "success",
        })
      }
      setShowRoomDialog(false)
      fetchRooms(selectedBuilding.id)
      fetchBuildings() // Refresh building counts
    } catch (error) {
      toast({
        title: "Lỗi",
        description:
          error instanceof Error ? error.message : "Không thể lưu phòng",
        variant: "destructive",
      })
    }
  }

  // Download Excel template
  const downloadTemplate = () => {
    const headers = ["STT", "ID Phòng", "Tên Phòng", "Tên Đại Diện", "Chỉ Số Cũ", "Chỉ Số Mới", "", "", "", "", "Số Điện Thoại", "Email"]
    const rows = [
      [1, "B 101", "B 101", "Nguyễn Văn A", 1000, 1100, "", "", "", "", "0901234567", "example@email.com"],
      [2, "B 102", "B 102", "Trần Thị B", 500, 650, "", "", "", "", "0912345678", ""],
      [3, "B 103", "", "", 200, "", "", "", "", "", "", ""],
    ]
    const wb = XLSX.utils.book_new()
    const ws = XLSX.utils.aoa_to_sheet([headers, ...rows])
    ws["!cols"] = [8, 12, 12, 20, 12, 12, 8, 8, 8, 8, 14, 24].map(w => ({ wch: w }))
    XLSX.utils.book_append_sheet(wb, ws, "Danh sách phòng")
    XLSX.writeFile(wb, "mau-danh-sach-phong.xlsx")
  }

  // Import Excel
  const handleFileChange = async (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files && e.target.files[0]) {
      const file = e.target.files[0]
      setImportFile(file)

      try {
        const reader = new FileReader()
        reader.onload = (evt) => {
          const bstr = evt.target?.result
          const wb = XLSX.read(bstr, { type: "binary" })
          const wsname = wb.SheetNames[0]
          const ws = wb.Sheets[wsname]
          const data = XLSX.utils.sheet_to_json<ExcelPreviewRow>(ws, { header: 1 })

          // data[0] is header row, skip that for preview rows, 
          // filter empty rows
          const rows = data.slice(1).filter((row) => row.length > 0)

          // Giới hạn preview 50 dòng tránh lag DOM
          setImportPreviewData(rows.slice(0, 50))
        }
        reader.readAsBinaryString(file)
      } catch (err) {
        console.error("Lỗi đọc file:", err)
        toast({
          title: "Lỗi",
          description: "Không thể đọc nội dung file Excel",
          variant: "destructive"
        })
      }
    }
  }

  const handleImportExcel = async () => {
    if (!importFile || !selectedBuilding) {
      toast({
        title: "Lỗi",
        description: "Vui lòng chọn file Excel",
        variant: "destructive",
      })
      return
    }

    setIsImporting(true)
    const formData = new FormData()
    formData.append("file", importFile)

    try {
      const data = await apiUpload<ImportRoomsResponse>(
        `/buildings/${selectedBuilding.id}/rooms/import-excel`,
        formData
      )

      toast({
        title: "Import thành công",
        description: data.message || `Đã import ${data.created} phòng mới, cập nhật ${data.updated} phòng`,
        variant: "success",
      })

      if (data.errors && data.errors.length > 0) {
        console.warn("Lỗi import:", data.errors)
        toast({
          title: "Chú ý",
          description: `Có ${data.errors.length} dòng bị lỗi (Xem console)`,
          variant: "destructive",
        })
      }

      setShowImportDialog(false)
      setImportFile(null)
      setImportPreviewData([])
      fetchRooms(selectedBuilding.id)
      fetchBuildings()
    } catch (error) {
      toast({
        title: "Lỗi import",
        description: error instanceof Error ? error.message : "Đã xảy ra lỗi",
        variant: "destructive",
      })
    } finally {
      setIsImporting(false)
    }
  }

  // Delete
  const confirmDelete = (type: "building" | "room", id: number, name: string) => {
    setDeleteTarget({ type, id, name })
    setShowDeleteDialog(true)
  }

  const handleDelete = async () => {
    if (!deleteTarget) return

    try {
      if (deleteTarget.type === "building") {
        await apiDelete(`/buildings/${deleteTarget.id}`)
        toast({
          title: "Đã xóa",
          description: "Tòa nhà đã được xóa",
          variant: "success",
        })
        if (selectedBuilding?.id === deleteTarget.id) {
          setSelectedBuilding(null)
          setRooms([])
        }
        fetchBuildings()
      } else {
        await apiDelete(`/rooms/${deleteTarget.id}`)
        toast({
          title: "Đã xóa",
          description: "Phòng đã được xóa",
          variant: "success",
        })
        if (selectedBuilding) {
          fetchRooms(selectedBuilding.id)
          fetchBuildings()
        }
      }
    } catch (error) {
      toast({
        title: "Lỗi",
        description:
          error instanceof Error ? error.message : "Không thể xóa",
        variant: "destructive",
      })
    } finally {
      setShowDeleteDialog(false)
      setDeleteTarget(null)
    }
  }

  const filteredBuildings = buildings.filter(
    (b) =>
      b.name.toLowerCase().includes(searchQuery.toLowerCase()) ||
      (b.address ?? "").toLowerCase().includes(searchQuery.toLowerCase())
  )

  const filteredRooms = rooms.filter(
    (r) =>
      r.room_number.toLowerCase().includes(searchQuery.toLowerCase()) ||
      (r.resident_name &&
        r.resident_name.toLowerCase().includes(searchQuery.toLowerCase()))
  )

  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-20">
        <Loader2 className="h-8 w-8 animate-spin text-primary" />
      </div>
    )
  }

  return (
    <div className="space-y-6">
      {/* Page header */}
      <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
        <div>
          {selectedBuilding ? (
            <div className="flex items-center gap-3">
              <Button
                variant="ghost"
                size="icon"
                onClick={() => {
                  setSelectedBuilding(null)
                  setRooms([])
                  setSearchQuery("")
                }}
              >
                <ChevronLeft className="h-5 w-5" />
              </Button>
              <div>
                <h1 className="text-3xl font-bold tracking-tight">
                  {selectedBuilding.name}
                </h1>
                <p className="text-muted-foreground">
                  {selectedBuilding.address} - Quản lý phòng
                </p>
              </div>
            </div>
          ) : (
            <div>
              <h1 className="text-3xl font-bold tracking-tight">Tòa nhà</h1>
              <p className="text-muted-foreground">
                Quản lý tòa nhà và phòng trong hệ thống
              </p>
            </div>
          )}
        </div>
        <div className="flex gap-2">
          <div className="relative">
            <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
            <Input
              placeholder="Tìm kiếm..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              className="pl-9 w-64"
            />
          </div>
          {selectedBuilding ? (
            <>
              <Button variant="outline" onClick={() => setShowImportDialog(true)}>
                <Upload className="mr-2 h-4 w-4" />
                Nhập Excel
              </Button>
              <Button onClick={openCreateRoom}>
                <Plus className="mr-2 h-4 w-4" />
                Thêm phòng
              </Button>
            </>
          ) : (
            <Button onClick={openCreateBuilding}>
              <Plus className="mr-2 h-4 w-4" />
              Thêm tòa nhà
            </Button>
          )}
        </div>
      </div>

      {/* Building list */}
      {!selectedBuilding && (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {filteredBuildings.length === 0 ? (
            <div className="col-span-full flex flex-col items-center justify-center py-12 text-center">
              <Building2 className="mb-3 h-12 w-12 text-muted-foreground/50" />
              <p className="text-lg font-medium">Chưa có tòa nhà nào</p>
              <p className="text-sm text-muted-foreground">
                Thêm tòa nhà mới để bắt đầu
              </p>
            </div>
          ) : (
            filteredBuildings.map((building) => (
              <Card
                key={building.id}
                className="cursor-pointer transition-shadow hover:shadow-md"
              >
                <CardHeader className="pb-3">
                  <div className="flex items-start justify-between">
                    <div
                      className="flex-1 cursor-pointer"
                      onClick={() => {
                        setSelectedBuilding(building)
                        setSearchQuery("")
                      }}
                    >
                      <CardTitle className="flex items-center gap-2 text-lg">
                        <Building2 className="h-5 w-5 text-primary" />
                        {building.name}
                      </CardTitle>
                      <CardDescription>{building.address}</CardDescription>
                    </div>
                    <div className="flex gap-1">
                      <Button
                        variant="ghost"
                        size="icon"
                        className="h-8 w-8"
                        onClick={(e) => {
                          e.stopPropagation()
                          openEditBuilding(building)
                        }}
                      >
                        <Pencil className="h-3.5 w-3.5" />
                      </Button>
                      <Button
                        variant="ghost"
                        size="icon"
                        className="h-8 w-8 text-red-500 hover:text-red-600"
                        onClick={(e) => {
                          e.stopPropagation()
                          confirmDelete("building", building.id, building.name)
                        }}
                      >
                        <Trash2 className="h-3.5 w-3.5" />
                      </Button>
                    </div>
                  </div>
                </CardHeader>
                <CardContent
                  className="cursor-pointer"
                  onClick={() => {
                    setSelectedBuilding(building)
                    setSearchQuery("")
                  }}
                >
                  <div className="flex items-center gap-4">
                    <div className="flex items-center gap-2 text-sm text-muted-foreground">
                      <DoorOpen className="h-4 w-4" />
                      <span>{building.room_count} phòng</span>
                    </div>
                  </div>
                </CardContent>
              </Card>
            ))
          )}
        </div>
      )}

      {/* Room list */}
      {selectedBuilding && (
        <Card>
          <CardHeader>
            <CardTitle>
              Danh sách phòng ({filteredRooms.length})
            </CardTitle>
            <CardDescription>
              Quản lý các phòng trong {selectedBuilding.name}
            </CardDescription>
          </CardHeader>
          <CardContent>
            {filteredRooms.length === 0 ? (
              <div className="flex flex-col items-center justify-center py-12 text-center">
                <DoorOpen className="mb-3 h-12 w-12 text-muted-foreground/50" />
                <p className="text-lg font-medium">Chưa có phòng nào</p>
                <p className="text-sm text-muted-foreground">
                  Thêm phòng mới để bắt đầu
                </p>
              </div>
            ) : (
              <div className="rounded-md border overflow-hidden">
                <table className="w-full text-sm text-left">
                  <thead className="bg-muted text-muted-foreground text-xs uppercase">
                    <tr>
                      <th className="px-4 py-3 font-medium w-10"></th>
                      <th className="px-4 py-3 font-medium">STT</th>
                      <th className="px-4 py-3 font-medium">ID Phòng</th>
                      <th className="px-4 py-3 font-medium">Đại Diện</th>
                      <th className="px-4 py-3 font-medium">SĐT</th>
                      <th className="px-4 py-3 font-medium">Email</th>
                      <th className="px-4 py-3 font-medium">Telegram ID</th>
                      <th className="px-4 py-3 font-medium text-right">Chỉ Số Cũ</th>
                      <th className="px-4 py-3 font-medium text-right">Chỉ Số Mới</th>
                      <th className="px-4 py-3 font-medium text-right">Số Tiêu Thụ</th>
                      <th className="px-4 py-3 font-medium">Trạng Thái</th>
                      <th className="px-4 py-3 font-medium text-right">Thao Tác</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y text-sm">
                    {filteredRooms.map((room, index) => (
                      <React.Fragment key={room.id}>
                        <tr className="hover:bg-muted/30 transition-colors">
                          <td className="px-2 py-3">
                            <Button
                              variant="ghost"
                              size="icon"
                              className="h-6 w-6"
                              onClick={() => toggleRow(room.id)}
                            >
                              {expandedRows.has(room.id) ? (
                                <ChevronDown className="h-4 w-4" />
                              ) : (
                                <ChevronRight className="h-4 w-4" />
                              )}
                            </Button>
                          </td>
                          <td className="px-4 py-3 text-muted-foreground">{index + 1}</td>
                          <td className="px-4 py-3 font-semibold flex items-center gap-2">
                            <DoorOpen className="h-4 w-4 text-primary" />
                            {room.room_number}
                          </td>
                          <td className="px-4 py-3">
                            {room.resident_name ? (
                              <div className="flex items-center gap-2">
                                <Users className="h-4 w-4 text-muted-foreground" />
                                <span className="font-medium">{room.resident_name}</span>
                              </div>
                            ) : (
                              <span className="text-muted-foreground italic text-xs">Trống</span>
                            )}
                          </td>
                          <td className="px-4 py-3">
                            {room.resident_phone || <span className="text-muted-foreground italic text-xs">-</span>}
                          </td>
                          <td className="px-4 py-3 max-w-[150px] truncate" title={room.resident_email || undefined}>
                            {room.resident_email || <span className="text-muted-foreground italic text-xs">-</span>}
                          </td>
                          <td className="px-4 py-3">
                            {room.telegram_id || <span className="text-muted-foreground italic text-xs">-</span>}
                          </td>
                          <td className="px-4 py-3 text-right font-medium">
                            {room.previous_reading !== null ? room.previous_reading : (room.initial_reading || 0)}
                          </td>
                          <td className="px-4 py-3 text-right font-medium text-primary">
                            {room.current_reading !== null ? room.current_reading : <span className="text-muted-foreground italic font-normal text-xs">-</span>}
                          </td>
                          <td className="px-4 py-3 text-right font-medium text-amber-600">
                            {room.consumption !== null ? room.consumption : <span className="text-muted-foreground italic font-normal text-xs">-</span>}
                          </td>
                          <td className="px-4 py-3">
                            {room.is_active ? (
                              <Badge variant="success" className="font-normal">Đang ở</Badge>
                            ) : (
                              <Badge variant="outline" className="font-normal text-muted-foreground">Trống</Badge>
                            )}
                          </td>
                          <td className="px-4 py-3">
                            <div className="flex justify-end gap-1">
                              <Button
                                variant="ghost"
                                size="icon"
                                className="h-8 w-8 text-muted-foreground hover:text-primary"
                                onClick={() => openEditRoom(room)}
                                title="Chỉnh sửa phòng"
                              >
                                <Pencil className="h-4 w-4" />
                              </Button>
                              <Button
                                variant="ghost"
                                size="icon"
                                className="h-8 w-8 text-red-500 hover:text-red-700 hover:bg-red-50"
                                onClick={() =>
                                  confirmDelete(
                                    "room",
                                    room.id,
                                    `Phòng ${room.room_number}`
                                  )
                                }
                                title="Xóa phòng"
                              >
                                <Trash2 className="h-4 w-4" />
                              </Button>
                            </div>
                          </td>
                        </tr>
                        {expandedRows.has(room.id) && (
                          <tr className="bg-muted/10 border-b">
                            <td colSpan={12} className="px-10 py-4">
                              <div className="rounded-md border bg-background">
                                <table className="w-full text-sm text-left">
                                  <thead className="bg-muted text-muted-foreground text-xs uppercase">
                                    <tr>
                                      <th className="px-4 py-2 font-medium">Kỳ ghi hóa đơn</th>
                                      <th className="px-4 py-2 font-medium text-right">Chỉ số chốt</th>
                                      <th className="px-4 py-2 font-medium text-right">Mức độ tin cậy AI</th>
                                      <th className="px-4 py-2 font-medium">Trạng thái</th>
                                    </tr>
                                  </thead>
                                  <tbody className="divide-y text-sm">
                                    {(!room.readings_history || room.readings_history.length === 0) ? (
                                      <tr>
                                        <td colSpan={4} className="px-4 py-4 text-center text-muted-foreground">
                                          Chưa có lịch sử ghi điện nào cho phòng này ngoài chỉ số ban đầu.
                                        </td>
                                      </tr>
                                    ) : (
                                      room.readings_history.map((history) => (
                                        <tr key={history.id} className="hover:bg-muted/30">
                                          <td className="px-4 py-2 text-muted-foreground">
                                            {new Date(history.reading_date).toLocaleDateString("vi-VN", { month: '2-digit', year: 'numeric' })}
                                          </td>
                                          <td className="px-4 py-2 text-right font-medium">
                                            {history.meter_value}
                                          </td>
                                          <td className="px-4 py-2 text-right">
                                            {history.confidence_score ? `${(history.confidence_score * 100).toFixed(0)}%` : "-"}
                                          </td>
                                          <td className="px-4 py-2">
                                            {history.status === "approved" ? (
                                              <Badge variant="success" className="font-normal text-[10px]">Đã duyệt</Badge>
                                            ) : history.status === "pending" || history.status === "needs_review" ? (
                                              <Badge variant="outline" className="font-normal text-amber-600 border-amber-200 text-[10px]">Chờ duyệt</Badge>
                                            ) : (
                                              <Badge variant="outline" className="font-normal text-muted-foreground text-[10px]">{history.status}</Badge>
                                            )}
                                          </td>
                                        </tr>
                                      ))
                                    )}
                                  </tbody>
                                </table>
                              </div>
                            </td>
                          </tr>
                        )}
                      </React.Fragment>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </CardContent>
        </Card>
      )}

      {/* Building dialog */}
      <Dialog open={showBuildingDialog} onOpenChange={setShowBuildingDialog}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>
              {editingBuilding ? "Sửa tòa nhà" : "Thêm tòa nhà mới"}
            </DialogTitle>
            <DialogDescription>
              {editingBuilding
                ? "Cập nhật thông tin tòa nhà"
                : "Nhập thông tin tòa nhà mới"}
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-4 py-4">
            <div className="space-y-2">
              <Label>Tên tòa nhà *</Label>
              <Input
                value={buildingForm.name}
                onChange={(e) =>
                  setBuildingForm({ ...buildingForm, name: e.target.value })
                }
                placeholder="Ví dụ: Tòa A, Nhà trọ 123..."
              />
            </div>
            <div className="space-y-2">
              <Label>Địa chỉ</Label>
              <Input
                value={buildingForm.address}
                onChange={(e) =>
                  setBuildingForm({ ...buildingForm, address: e.target.value })
                }
                placeholder="Ví dụ: 123 Nguyễn Văn A, Q.1"
              />
            </div>
          </div>
          <DialogFooter>
            <Button
              variant="outline"
              onClick={() => setShowBuildingDialog(false)}
            >
              Hủy
            </Button>
            <Button onClick={handleSaveBuilding}>
              {editingBuilding ? "Cập nhật" : "Tạo mới"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Room dialog */}
      <Dialog open={showRoomDialog} onOpenChange={setShowRoomDialog}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>
              {editingRoom ? "Sửa phòng" : "Thêm phòng mới"}
            </DialogTitle>
            <DialogDescription>
              {editingRoom
                ? "Cập nhật thông tin phòng"
                : `Thêm phòng mới vào ${selectedBuilding?.name}`}
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-4 py-4">
            <div className="space-y-2">
              <Label>Số phòng *</Label>
              <Input
                value={roomForm.room_number}
                onChange={(e) =>
                  setRoomForm({ ...roomForm, room_number: e.target.value })
                }
                placeholder="Ví dụ: 101, A01..."
              />
            </div>
            <div className="space-y-2">
              <Label>Tên cư dân</Label>
              <Input
                value={roomForm.resident_name}
                onChange={(e) =>
                  setRoomForm({ ...roomForm, resident_name: e.target.value })
                }
                placeholder="Ví dụ: Nguyễn Văn A"
              />
            </div>
            <div className="space-y-2">
              <Label>Số điện thoại</Label>
              <Input
                value={roomForm.resident_phone}
                onChange={(e) =>
                  setRoomForm({ ...roomForm, resident_phone: e.target.value })
                }
                placeholder="Ví dụ: 0901234567"
              />
            </div>
            <div className="space-y-2">
              <Label>Email</Label>
              <Input
                type="email"
                value={roomForm.resident_email}
                onChange={(e) =>
                  setRoomForm({ ...roomForm, resident_email: e.target.value })
                }
                placeholder="Ví dụ: nguyenvan@example.com"
              />
            </div>
            <div className="space-y-2">
              <Label>Telegram Chat ID</Label>
              <Input
                value={roomForm.telegram_id}
                onChange={(e) =>
                  setRoomForm({
                    ...roomForm,
                    telegram_id: e.target.value,
                  })
                }
                placeholder="Ví dụ: 123456789"
              />
              <div className="text-xs text-muted-foreground space-y-1">
                <p>Chat ID dạng số để gửi thông báo hóa đơn tự động.</p>
                <p className="font-medium text-orange-600">Cách lấy Chat ID:</p>
                <ol className="list-decimal pl-4 space-y-0.5">
                  <li>Cư dân nhắn tin <span className="font-mono bg-muted px-1 rounded">/start</span> cho bot của bạn trước</li>
                  <li>Sau đó nhắn tin cho <span className="font-mono bg-muted px-1 rounded">@userinfobot</span> — nó sẽ trả về Chat ID</li>
                  <li>Nhập số ID đó vào đây (chỉ nhập số, không có @)</li>
                </ol>
              </div>
            </div>
            <div className="space-y-2">
              <Label>Chỉ số ban đầu (kWh)</Label>
              <Input
                type="number"
                value={roomForm.initial_reading}
                onChange={(e) =>
                  setRoomForm({
                    ...roomForm,
                    initial_reading: parseInt(e.target.value) || 0,
                  })
                }
                placeholder="Ví dụ: 100"
              />
            </div>
          </div>
          <DialogFooter>
            <Button
              variant="outline"
              onClick={() => setShowRoomDialog(false)}
            >
              Hủy
            </Button>
            <Button onClick={handleSaveRoom}>
              {editingRoom ? "Cập nhật" : "Tạo mới"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Import dialog */}
      <Dialog open={showImportDialog} onOpenChange={setShowImportDialog}>
        <DialogContent className="max-w-4xl max-h-[90vh] flex flex-col">
          <DialogHeader>
            <div className="flex items-start justify-between gap-4">
              <div>
                <DialogTitle>Nhập danh sách phòng từ Excel</DialogTitle>
                <DialogDescription className="mt-1">
                  Tải file Excel để tải lên danh sách phòng cho{" "}
                  <strong>{selectedBuilding?.name}</strong>. Dưới đây là bảng xem trước dữ liệu (tối đa 50 dòng).
                </DialogDescription>
              </div>
              <Button variant="outline" size="sm" onClick={downloadTemplate} className="shrink-0 text-xs gap-1.5">
                <Download className="h-3.5 w-3.5" />
                Tải file mẫu
              </Button>
            </div>
          </DialogHeader>

          <div className="flex-1 overflow-auto space-y-4 py-4 pr-1">
            <div className="flex flex-col items-center justify-center rounded-lg border border-dashed p-6 bg-muted/30 transition-colors hover:bg-muted/50">
              <FileSpreadsheet className="mb-2 h-10 w-10 text-muted-foreground" />
              <Label
                htmlFor="excel-upload"
                className="cursor-pointer text-sm font-medium text-primary hover:underline flex flex-col items-center gap-1"
              >
                <span>Nhấn để chọn hoặc đổi file Excel</span>
                <span className="text-xs text-muted-foreground font-normal">Hỗ trợ .xlsx, .xls</span>
                <Input
                  id="excel-upload"
                  type="file"
                  accept=".xlsx, .xls"
                  className="hidden"
                  onChange={handleFileChange}
                />
              </Label>
              {importFile && (
                <div className="mt-3 inline-flex items-center gap-2 bg-green-50 text-green-700 px-3 py-1.5 rounded-full text-sm font-medium border border-green-200">
                  <FileSpreadsheet className="h-4 w-4" />
                  {importFile.name}
                </div>
              )}
            </div>

            {importFile && importPreviewData.length > 0 && (
              <div className="rounded-md border overflow-hidden">
                <div className="bg-muted px-4 py-2 border-b flex items-center justify-between text-sm">
                  <span className="font-semibold flex items-center gap-2">
                    <FileSpreadsheet className="h-4 w-4" /> Bản xem trước
                  </span>
                  <span className="text-muted-foreground">
                    Đang hiển thị {importPreviewData.length} dòng Excel
                  </span>
                </div>
                <div className="max-h-[300px] overflow-auto">
                  <table className="w-full text-sm text-left">
                    <thead className="text-xs text-muted-foreground bg-muted/50 sticky top-0 uppercase">
                      <tr>
                        <th className="px-4 py-2 font-medium">STT</th>
                        <th className="px-4 py-2 font-medium">ID Phòng</th>
                        <th className="px-4 py-2 font-medium">Phòng</th>
                        <th className="px-4 py-2 font-medium">Đại Diện</th>
                        <th className="px-4 py-2 font-medium">Chỉ Số Cũ</th>
                        <th className="px-4 py-2 font-medium">Chỉ Số Mới</th>
                        <th className="px-4 py-2 font-medium">SĐT</th>
                        <th className="px-4 py-2 font-medium">Email</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y">
                      {importPreviewData.map((row, idx) => (
                        <tr key={idx} className="hover:bg-muted/30">
                          <td className="px-4 py-2">{row[0]}</td>
                          <td className="px-4 py-2 font-medium">{row[1] || <span className="text-red-500 text-xs">Trống</span>}</td>
                          <td className="px-4 py-2">{row[2]}</td>
                          <td className="px-4 py-2">{row[3]}</td>
                          <td className="px-4 py-2 text-right">{row[4]}</td>
                          <td className="px-4 py-2 text-right">{row[5]}</td>
                          <td className="px-4 py-2">{row[10]}</td>
                          <td className="px-4 py-2 max-w-[150px] truncate" title={String(row[11] ?? "")}>{row[11]}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            )}

            {!importFile && (
              <div className="text-sm border rounded-lg bg-orange-50/50 p-4">
                <div className="flex gap-2 items-start text-orange-800">
                  <AlertCircle className="h-5 w-5 shrink-0 mt-0.5" />
                  <div>
                    <p className="font-semibold mb-1">Cấu trúc file bắt buộc:</p>
                    <p className="mb-2text-muted-foreground">File excel của bạn phải có các cột theo đúng thứ tự (index) sau:</p>
                    <ul className="list-disc pl-5 space-y-1 mt-1 text-muted-foreground">
                      <li>Cột A (Index 0): STT</li>
                      <li>Cột B (Index 1): ID/Số Phòng bắt buộc (Ví dụ: B 1801)</li>
                      <li>Cột C (Index 2): Tên Phòng (tuỳ chọn)</li>
                      <li>Cột D (Index 3): Tên Đại Diện</li>
                      <li>Cột E (Index 4): Chỉ Số Cũ</li>
                      <li>Cột F (Index 5): Chỉ Số Mới</li>
                      <li>... (các cột giữa không quy định)</li>
                      <li>Cột K (Index 10): Số điện thoại</li>
                      <li>Cột L (Index 11): Email</li>
                    </ul>
                  </div>
                </div>
              </div>
            )}
          </div>

          <DialogFooter className="mt-2">
            <Button
              variant="outline"
              onClick={() => {
                setShowImportDialog(false)
                setImportFile(null)
                setImportPreviewData([])
              }}
              disabled={isImporting}
            >
              Hủy
            </Button>
            <Button
              onClick={handleImportExcel}
              disabled={!importFile || isImporting}
            >
              {isImporting && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
              {isImporting ? "Đang xử lý..." : "Bắt đầu Import"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Delete confirmation dialog */}
      <Dialog open={showDeleteDialog} onOpenChange={setShowDeleteDialog}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Xác nhận xóa</DialogTitle>
            <DialogDescription>
              Bạn có chắc muốn xóa{" "}
              <strong>{deleteTarget?.name}</strong>? Hành động này không thể
              hoàn tác.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button
              variant="outline"
              onClick={() => setShowDeleteDialog(false)}
            >
              Hủy
            </Button>
            <Button variant="destructive" onClick={handleDelete}>
              Xóa
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div >
  )
}
