"use client"

import React, { useCallback, useEffect, useState } from "react"
import Link from "next/link"
import {
  Building2,
  CheckCircle2,
  AlertCircle,
  Clock,
  Upload,
  FileText,
  Activity,
  TrendingUp,
} from "lucide-react"
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"
import { apiGet } from "@/lib/api"
import { toast } from "@/components/ui/use-toast"

interface DashboardStats {
  total_buildings: number
  total_rooms: number
  readings_done: number
  readings_pending: number
  readings_error: number
  total_invoices: number
  total_revenue: number
  current_month: string
}

interface ActivityItem {
  id: number
  type: string
  description: string
  status: string
  created_at: string
}

export default function DashboardPage() {
  const [stats, setStats] = useState<DashboardStats | null>(null)
  const [activities, setActivities] = useState<ActivityItem[]>([])
  const [isLoading, setIsLoading] = useState(true)

  const fetchDashboardData = useCallback(async () => {
    setIsLoading(true)
    try {
      const [statsData, activityData] = await Promise.all([
        apiGet<DashboardStats>("/dashboard/stats"),
        apiGet<ActivityItem[]>("/dashboard/activity"),
      ])
      setStats(statsData)
      setActivities(activityData)
    } catch {
      setStats(null)
      setActivities([])
      toast({
        title: "Không tải được dashboard",
        description: "Kiểm tra kết nối rồi thử lại.",
        variant: "destructive",
      })
    } finally {
      setIsLoading(false)
    }
  }, [])

  useEffect(() => {
    void fetchDashboardData()
  }, [fetchDashboardData])

  const statCards = [
    {
      title: "Tổng phòng",
      value: stats?.total_rooms ?? 0,
      icon: Building2,
      color: "text-blue-600",
      bgColor: "bg-blue-100 dark:bg-blue-900/30",
      description: `${stats?.total_buildings ?? 0} tòa nhà`,
    },
    {
      title: "Đã ghi",
      value: stats?.readings_done ?? 0,
      icon: CheckCircle2,
      color: "text-green-600",
      bgColor: "bg-green-100 dark:bg-green-900/30",
      description: "Chỉ số đã xác nhận",
    },
    {
      title: "Chưa ghi",
      value: stats?.readings_pending ?? 0,
      icon: Clock,
      color: "text-yellow-600",
      bgColor: "bg-yellow-100 dark:bg-yellow-900/30",
      description: "Đang chờ xử lý",
    },
    {
      title: "Lỗi",
      value: stats?.readings_error ?? 0,
      icon: AlertCircle,
      color: "text-red-600",
      bgColor: "bg-red-100 dark:bg-red-900/30",
      description: "Cần kiểm tra lại",
    },
  ]

  const getActivityBadgeVariant = (
    status: string
  ): "success" | "destructive" | "default" | "warning" => {
    switch (status) {
      case "approved":
        return "success"
      case "rejected":
        return "destructive"
      case "pending":
      case "needs_review":
        return "warning"
      default:
        return "default"
    }
  }

  const getActivityIcon = (status: string) => {
    switch (status) {
      case "approved":
        return <CheckCircle2 className="h-4 w-4 text-green-500" />
      case "rejected":
        return <AlertCircle className="h-4 w-4 text-red-500" />
      case "pending":
      case "needs_review":
        return <Clock className="h-4 w-4 text-yellow-500" />
      default:
        return <Activity className="h-4 w-4 text-blue-500" />
    }
  }

  const getActivityStatus = (status: string) => {
    switch (status) {
      case "approved":
        return "Đã xác nhận"
      case "rejected":
        return "Đã từ chối"
      case "needs_review":
        return "Cần xem lại"
      case "pending":
        return "Đang xử lý"
      default:
        return status
    }
  }

  if (isLoading) {
    return (
      <div className="space-y-6">
        <div>
          <h1 className="text-3xl font-bold tracking-tight">Dashboard</h1>
          <p className="text-muted-foreground">
            Tổng quan hệ thống báo điện cư dân
          </p>
        </div>
        <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-4">
          {[1, 2, 3, 4].map((i) => (
            <Card key={i}>
              <CardContent className="p-6">
                <div className="h-20 animate-pulse rounded bg-muted" />
              </CardContent>
            </Card>
          ))}
        </div>
      </div>
    )
  }

  return (
    <div className="space-y-6">
      {/* Page header */}
      <div>
        <h1 className="text-3xl font-bold tracking-tight">Dashboard</h1>
        <p className="text-muted-foreground">
          Tổng quan hệ thống báo điện cư dân
        </p>
      </div>

      {/* Stats cards */}
      <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-4">
        {statCards.map((stat) => (
          <Card key={stat.title}>
            <CardContent className="p-6">
              <div className="flex items-center justify-between">
                <div>
                  <p className="text-sm font-medium text-muted-foreground">
                    {stat.title}
                  </p>
                  <p className="text-3xl font-bold">{stat.value}</p>
                  <p className="mt-1 text-xs text-muted-foreground">
                    {stat.description}
                  </p>
                </div>
                <div
                  className={`flex h-12 w-12 items-center justify-center rounded-lg ${stat.bgColor}`}
                >
                  <stat.icon className={`h-6 w-6 ${stat.color}`} />
                </div>
              </div>
            </CardContent>
          </Card>
        ))}
      </div>

      <div className="grid gap-4 md:grid-cols-2">
        <Card>
          <CardContent className="p-4">
            <p className="text-sm text-muted-foreground">Hóa đơn tháng {stats?.current_month ?? "-"}</p>
            <p className="text-2xl font-bold">{stats?.total_invoices ?? 0}</p>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="p-4">
            <p className="text-sm text-muted-foreground">Doanh thu tháng</p>
            <p className="text-2xl font-bold">
              {(stats?.total_revenue ?? 0).toLocaleString("vi-VN")} đ
            </p>
          </CardContent>
        </Card>
      </div>

      {/* Quick actions & Recent activity */}
      <div className="grid gap-6 lg:grid-cols-2">
        {/* Quick actions */}
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <TrendingUp className="h-5 w-5" />
              Thao tác nhanh
            </CardTitle>
            <CardDescription>
              Các chức năng thường dùng
            </CardDescription>
          </CardHeader>
          <CardContent className="grid gap-3 sm:grid-cols-2">
            <Link href="/upload">
              <Button
                variant="outline"
                className="h-auto w-full justify-start gap-3 p-4"
              >
                <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-blue-100 dark:bg-blue-900/30">
                  <Upload className="h-5 w-5 text-blue-600" />
                </div>
                <div className="text-left">
                  <p className="font-medium">Upload ảnh</p>
                  <p className="text-xs text-muted-foreground">
                    Tải lên ảnh đồng hồ điện
                  </p>
                </div>
              </Button>
            </Link>
            <Link href="/invoices">
              <Button
                variant="outline"
                className="h-auto w-full justify-start gap-3 p-4"
              >
                <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-green-100 dark:bg-green-900/30">
                  <FileText className="h-5 w-5 text-green-600" />
                </div>
                <div className="text-left">
                  <p className="font-medium">Tạo hóa đơn</p>
                  <p className="text-xs text-muted-foreground">
                    Xuất hóa đơn điện tháng này
                  </p>
                </div>
              </Button>
            </Link>
            <Link href="/buildings">
              <Button
                variant="outline"
                className="h-auto w-full justify-start gap-3 p-4"
              >
                <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-purple-100 dark:bg-purple-900/30">
                  <Building2 className="h-5 w-5 text-purple-600" />
                </div>
                <div className="text-left">
                  <p className="font-medium">Quản lý tòa nhà</p>
                  <p className="text-xs text-muted-foreground">
                    Thêm/sửa tòa nhà và phòng
                  </p>
                </div>
              </Button>
            </Link>
            <Link href="/readings">
              <Button
                variant="outline"
                className="h-auto w-full justify-start gap-3 p-4"
              >
                <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-orange-100 dark:bg-orange-900/30">
                  <Activity className="h-5 w-5 text-orange-600" />
                </div>
                <div className="text-left">
                  <p className="font-medium">Xem chỉ số</p>
                  <p className="text-xs text-muted-foreground">
                    Kiểm tra chỉ số đã ghi
                  </p>
                </div>
              </Button>
            </Link>
          </CardContent>
        </Card>

        {/* Recent activity */}
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <Activity className="h-5 w-5" />
              Hoạt động gần đây
            </CardTitle>
            <CardDescription>
              Các thao tác mới nhất trong hệ thống
            </CardDescription>
          </CardHeader>
          <CardContent>
            {activities.length === 0 ? (
              <div className="flex flex-col items-center justify-center py-8 text-center">
                <Activity className="mb-3 h-10 w-10 text-muted-foreground/50" />
                <p className="text-sm text-muted-foreground">
                  Chưa có hoạt động nào
                </p>
              </div>
            ) : (
              <div className="space-y-4">
                {activities.slice(0, 8).map((activity) => (
                  <div
                    key={activity.id}
                    className="flex items-start gap-3 rounded-lg border p-3"
                  >
                    <div className="mt-0.5">
                      {getActivityIcon(activity.status)}
                    </div>
                    <div className="flex-1 space-y-1">
                      <div className="flex items-center gap-2">
                        <p className="text-sm font-medium">Ghi chỉ số</p>
                        <Badge variant={getActivityBadgeVariant(activity.status)}>
                          {getActivityStatus(activity.status)}
                        </Badge>
                      </div>
                      <p className="text-xs text-muted-foreground">
                        {activity.description}
                      </p>
                      <p className="text-xs text-muted-foreground">
                        {new Date(activity.created_at).toLocaleString("vi-VN")}
                      </p>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </CardContent>
        </Card>
      </div>
    </div>
  )
}
