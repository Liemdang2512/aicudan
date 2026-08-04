"use client"

import React, { useCallback, useEffect, useState } from "react"
import { useSearchParams } from "next/navigation"
import {
  Gauge,
  Loader2,
  CheckCircle2,
  AlertCircle,
  Clock,
  Search,
  RefreshCw,
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
import { Badge } from "@/components/ui/badge"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import { apiGet } from "@/lib/api"

interface Building {
  id: number
  name: string
}

interface Reading {
  id: number
  room_id: number
  room_number: string
  building_name: string
  reading_date: string
  meter_value: number | null
  image_path: string | null
  confidence_score: number | null
  status: string
  created_at: string
  previous_reading: number
  current_reading: number
  consumption: number
}

function getCurrentMonth() {
  const today = new Date()
  return `${today.getFullYear()}-${String(today.getMonth() + 1).padStart(2, "0")}`
}

export default function ReadingsPage() {
  const searchParams = useSearchParams()
  const [buildings, setBuildings] = useState<Building[]>([])
  const [readings, setReadings] = useState<Reading[]>([])
  const [isLoading, setIsLoading] = useState(true)
  const [filterBuilding, setFilterBuilding] = useState<string>("all")
  const [filterStatus, setFilterStatus] = useState<string>(
    searchParams.get("status") ?? "all"
  )
  const [filterMonth, setFilterMonth] = useState(getCurrentMonth)
  const [searchQuery, setSearchQuery] = useState("")

  const fetchBuildings = useCallback(async () => {
    try {
      const data = await apiGet<Building[]>("/buildings")
      setBuildings(data)
    } catch {
      // Silently handle
    }
  }, [])

  const fetchReadings = useCallback(async () => {
    setIsLoading(true)
    try {
      const params: Record<string, string> = {}
      if (filterBuilding && filterBuilding !== "all") {
        params.building_id = filterBuilding
      }
      if (filterMonth) {
        params.month = filterMonth
      }
      const data = await apiGet<Reading[]>("/readings", params)
      setReadings(data)
    } catch {
      setReadings([])
    } finally {
      setIsLoading(false)
    }
  }, [filterBuilding, filterMonth])

  useEffect(() => {
    void fetchBuildings()
  }, [fetchBuildings])

  useEffect(() => {
    void fetchReadings()
  }, [fetchReadings])

  const getStatusBadge = (status: string) => {
    switch (status) {
      case "approved":
        return (
          <Badge variant="success">
            <CheckCircle2 className="mr-1 h-3 w-3" />
            Đã xác nhận
          </Badge>
        )
      case "rejected":
        return (
          <Badge variant="destructive">
            <AlertCircle className="mr-1 h-3 w-3" />
            Đã từ chối
          </Badge>
        )
      case "pending":
        return (
          <Badge variant="warning">
            <Clock className="mr-1 h-3 w-3" />
            Đang xử lý
          </Badge>
        )
      case "needs_review":
        return (
          <Badge variant="outline" className="text-amber-600 border-amber-200">
            <AlertCircle className="mr-1 h-3 w-3" />
            Cần xem lại
          </Badge>
        )
      default:
        return <Badge variant="outline">{status}</Badge>
    }
  }

  const filteredReadings = readings.filter((r) => {
    if (filterStatus === "approved" && r.status !== "approved") return false
    if (filterStatus === "pending" && r.status !== "pending" && r.status !== "needs_review") return false
    if (filterStatus === "needs_review" && r.status !== "needs_review") return false
    if (filterStatus === "rejected" && r.status !== "rejected" && r.status !== "error") return false

    if (!searchQuery) return true
    const q = searchQuery.toLowerCase()
    return (
      r.room_number?.toLowerCase().includes(q) ||
      r.building_name?.toLowerCase().includes(q)
    )
  })

  const approvedCount = readings.filter((r) => r.status === "approved").length
  const errorCount = readings.filter((r) => r.status === "rejected" || r.status === "error").length
  const pendingCount = readings.filter(
    (r) => r.status === "pending" || r.status === "needs_review"
  ).length

  return (
    <div className="space-y-6">
      {/* Page header */}
      <div>
        <h1 className="text-3xl font-bold tracking-tight">Chỉ số điện</h1>
        <p className="text-muted-foreground">
          Xem và quản lý chỉ số đồng hồ điện đã ghi
        </p>
      </div>

      {/* Summary Cards (Interactive Tabs) */}
      <div className="grid gap-4 sm:grid-cols-4">
        <Card
          onClick={() => setFilterStatus("all")}
          className={`cursor-pointer transition-all duration-200 hover:shadow-md select-none ${
            filterStatus === "all"
              ? "ring-2 ring-primary bg-primary/5 border-primary shadow-sm"
              : "hover:border-primary/40"
          }`}
        >
          <CardContent className="p-4">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-sm font-medium text-muted-foreground">Tổng số ghi</p>
                <p className="text-2xl font-bold">{readings.length}</p>
              </div>
              <Gauge className={`h-8 w-8 transition-colors ${filterStatus === "all" ? "text-primary" : "text-muted-foreground/50"}`} />
            </div>
          </CardContent>
        </Card>

        <Card
          onClick={() => setFilterStatus("approved")}
          className={`cursor-pointer transition-all duration-200 hover:shadow-md select-none ${
            filterStatus === "approved"
              ? "ring-2 ring-green-500 bg-green-500/10 border-green-500 shadow-sm"
              : "hover:border-green-500/40"
          }`}
        >
          <CardContent className="p-4">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-sm font-medium text-muted-foreground">Đã xác nhận</p>
                <p className="text-2xl font-bold text-green-600 dark:text-green-400">
                  {approvedCount}
                </p>
              </div>
              <CheckCircle2 className={`h-8 w-8 transition-colors ${filterStatus === "approved" ? "text-green-500" : "text-green-500/50"}`} />
            </div>
          </CardContent>
        </Card>

        <Card
          onClick={() => setFilterStatus("pending")}
          className={`cursor-pointer transition-all duration-200 hover:shadow-md select-none ${
            filterStatus === "pending" || filterStatus === "needs_review"
              ? "ring-2 ring-yellow-500 bg-yellow-500/10 border-yellow-500 shadow-sm"
              : "hover:border-yellow-500/40"
          }`}
        >
          <CardContent className="p-4">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-sm font-medium text-muted-foreground">Đang xử lý</p>
                <p className="text-2xl font-bold text-yellow-600 dark:text-yellow-400">
                  {pendingCount}
                </p>
              </div>
              <Clock className={`h-8 w-8 transition-colors ${filterStatus === "pending" || filterStatus === "needs_review" ? "text-yellow-500" : "text-yellow-500/50"}`} />
            </div>
          </CardContent>
        </Card>

        <Card
          onClick={() => setFilterStatus("rejected")}
          className={`cursor-pointer transition-all duration-200 hover:shadow-md select-none ${
            filterStatus === "rejected"
              ? "ring-2 ring-red-500 bg-red-500/10 border-red-500 shadow-sm"
              : "hover:border-red-500/40"
          }`}
        >
          <CardContent className="p-4">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-sm font-medium text-muted-foreground">Lỗi</p>
                <p className="text-2xl font-bold text-red-600 dark:text-red-400">{errorCount}</p>
              </div>
              <AlertCircle className={`h-8 w-8 transition-colors ${filterStatus === "rejected" ? "text-red-500" : "text-red-500/50"}`} />
            </div>
          </CardContent>
        </Card>
      </div>

      {/* Table */}
      <Card>
        <CardHeader>
          <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
            <div>
              <CardTitle>Danh sách chỉ số</CardTitle>
              <CardDescription>
                Tất cả chỉ số đã được ghi nhận qua AI
              </CardDescription>
            </div>
            <Button variant="ghost" size="sm" onClick={fetchReadings}>
              <RefreshCw className="h-4 w-4" />
            </Button>
          </div>
        </CardHeader>
        <CardContent>
          {/* Filters */}
          <div className="mb-4 flex flex-col gap-3 sm:flex-row">
            <div className="relative flex-1">
              <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
              <Input
                placeholder="Tìm phòng..."
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                className="pl-9"
              />
            </div>
            <div className="w-full sm:w-48">
              <Select
                value={filterBuilding}
                onValueChange={setFilterBuilding}
              >
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
            <Input
              type="month"
              aria-label="Tháng ghi chỉ số"
              value={filterMonth}
              onChange={(event) => setFilterMonth(event.target.value)}
              className="w-full sm:w-44"
            />
            <div className="w-full sm:w-40">
              <Select value={filterStatus} onValueChange={setFilterStatus}>
                <SelectTrigger>
                  <SelectValue placeholder="Tất cả" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="all">Tất cả</SelectItem>
                  <SelectItem value="approved">Đã xác nhận</SelectItem>
                  <SelectItem value="pending">Đang xử lý</SelectItem>
                  <SelectItem value="needs_review">Cần xem lại</SelectItem>
                  <SelectItem value="rejected">Đã từ chối</SelectItem>
                </SelectContent>
              </Select>
            </div>
          </div>

          {/* Table */}
          {isLoading ? (
            <div className="flex items-center justify-center py-12">
              <Loader2 className="h-8 w-8 animate-spin text-primary" />
            </div>
          ) : filteredReadings.length === 0 ? (
            <div className="flex flex-col items-center justify-center py-12 text-center">
              <Gauge className="mb-3 h-12 w-12 text-muted-foreground/50" />
              <p className="text-lg font-medium">Chưa có chỉ số nào</p>
              <p className="text-sm text-muted-foreground">
                Upload ảnh đồng hồ điện để bắt đầu ghi chỉ số
              </p>
            </div>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b bg-muted/50">
                    <th className="px-3 py-3 text-left font-medium">Phòng</th>
                    <th className="px-3 py-3 text-left font-medium hidden sm:table-cell">
                      Tòa nhà
                    </th>
                    <th className="px-3 py-3 text-right font-medium hidden lg:table-cell">
                      Chỉ số cũ
                    </th>
                    <th className="px-3 py-3 text-right font-medium">
                      Chỉ số mới
                    </th>
                    <th className="px-3 py-3 text-right font-medium">
                      Tiêu thụ
                    </th>
                    <th className="px-3 py-3 text-center font-medium hidden md:table-cell">
                      Độ tin cậy
                    </th>
                    <th className="px-3 py-3 text-left font-medium hidden md:table-cell">
                      Ngày ghi
                    </th>
                    <th className="px-3 py-3 text-center font-medium">
                      Trạng thái
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {filteredReadings.map((reading) => (
                    <tr
                      key={reading.id}
                      className="border-b transition-colors hover:bg-muted/50"
                    >
                      <td className="px-3 py-3 font-medium">
                        {reading.room_number}
                      </td>
                      <td className="px-3 py-3 hidden sm:table-cell">
                        {reading.building_name}
                      </td>
                      <td className="px-3 py-3 text-right font-mono hidden lg:table-cell">
                        {reading.previous_reading.toLocaleString("vi-VN")}
                      </td>
                      <td className="px-3 py-3 text-right font-mono">
                        {reading.current_reading.toLocaleString("vi-VN")}
                      </td>
                      <td className="px-3 py-3 text-right font-mono">
                        {reading.consumption.toLocaleString("vi-VN")} kWh
                      </td>
                      <td className="px-3 py-3 text-center hidden md:table-cell">
                        {reading.confidence_score != null ? (
                          <span
                            className={`font-medium ${reading.confidence_score >= 0.9
                                ? "text-green-600"
                                : reading.confidence_score >= 0.7
                                  ? "text-yellow-600"
                                  : "text-red-600"
                              }`}
                          >
                            {Math.round(reading.confidence_score * 100)}%
                          </span>
                        ) : (
                          "-"
                        )}
                      </td>
                      <td className="px-3 py-3 hidden md:table-cell">
                        {reading.reading_date
                          ? new Date(reading.reading_date).toLocaleDateString(
                            "vi-VN"
                          )
                          : "-"}
                      </td>
                      <td className="px-3 py-3 text-center">
                        {getStatusBadge(reading.status)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  )
}
