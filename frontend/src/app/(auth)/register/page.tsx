"use client"

import React, { useState } from "react"
import { useRouter } from "next/navigation"
import Link from "next/link"
import { Zap, Eye, EyeOff } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import {
  Card,
  CardContent,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import { toast } from "@/components/ui/use-toast"
import { apiPost } from "@/lib/api"
import { useAuthStore } from "@/stores/auth-store"

interface RegisterResponse {
  access_token: string
  user: {
    id: number
    email: string
    full_name: string
    phone: string | null
    role: string
    is_active: boolean
    created_at: string
  }
}

export default function RegisterPage() {
  const router = useRouter()
  const { setAuth } = useAuthStore()
  const [isLoading, setIsLoading] = useState(false)
  const [showPassword, setShowPassword] = useState(false)
  const [form, setForm] = useState({
    full_name: "",
    email: "",
    phone: "",
    password: "",
    confirm_password: "",
  })

  const handleChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    setForm((prev) => ({ ...prev, [e.target.name]: e.target.value }))
  }

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()

    if (!form.full_name || !form.email || !form.password) {
      toast({ title: "Lỗi", description: "Vui lòng điền đầy đủ thông tin bắt buộc", variant: "destructive" })
      return
    }

    if (form.password.length < 8) {
      toast({ title: "Lỗi", description: "Mật khẩu phải có ít nhất 8 ký tự", variant: "destructive" })
      return
    }

    if (form.password !== form.confirm_password) {
      toast({ title: "Lỗi", description: "Mật khẩu xác nhận không khớp", variant: "destructive" })
      return
    }

    setIsLoading(true)
    try {
      const res = await apiPost<RegisterResponse>("/auth/register", {
        email: form.email,
        password: form.password,
        full_name: form.full_name,
        phone: form.phone || null,
      })

      // Auto login after register
      if (typeof window !== "undefined") {
        localStorage.setItem("token", res.access_token)
        localStorage.setItem("user", JSON.stringify(res.user))
      }
      setAuth(res.access_token, res.user)

      toast({ title: "Đăng ký thành công", description: `Chào mừng ${res.user.full_name}!`, variant: "success" })
      router.push("/dashboard")
    } catch (error) {
      toast({
        title: "Đăng ký thất bại",
        description: error instanceof Error ? error.message : "Có lỗi xảy ra",
        variant: "destructive",
      })
    } finally {
      setIsLoading(false)
    }
  }

  return (
    <Card className="w-full">
      <CardHeader className="space-y-1 text-center">
        <div className="mx-auto mb-4 flex h-12 w-12 items-center justify-center rounded-xl bg-primary">
          <Zap className="h-7 w-7 text-primary-foreground" />
        </div>
        <CardTitle className="text-2xl font-bold">Tạo tài khoản</CardTitle>
        <CardDescription>Đăng ký để quản lý điện năng thông minh</CardDescription>
      </CardHeader>
      <form onSubmit={handleSubmit}>
        <CardContent className="space-y-4">
          <div className="space-y-2">
            <Label htmlFor="full_name">Họ và tên <span className="text-destructive">*</span></Label>
            <Input
              id="full_name"
              name="full_name"
              placeholder="Nguyễn Văn A"
              value={form.full_name}
              onChange={handleChange}
              disabled={isLoading}
            />
          </div>
          <div className="space-y-2">
            <Label htmlFor="email">Email <span className="text-destructive">*</span></Label>
            <Input
              id="email"
              name="email"
              type="email"
              placeholder="owner@example.com"
              value={form.email}
              onChange={handleChange}
              autoComplete="email"
              disabled={isLoading}
            />
          </div>
          <div className="space-y-2">
            <Label htmlFor="phone">Số điện thoại</Label>
            <Input
              id="phone"
              name="phone"
              type="tel"
              placeholder="0901234567"
              value={form.phone}
              onChange={handleChange}
              disabled={isLoading}
            />
          </div>
          <div className="space-y-2">
            <Label htmlFor="password">Mật khẩu <span className="text-destructive">*</span></Label>
            <div className="relative">
              <Input
                id="password"
                name="password"
                type={showPassword ? "text" : "password"}
                placeholder="Ít nhất 8 ký tự"
                value={form.password}
                onChange={handleChange}
                autoComplete="new-password"
                disabled={isLoading}
              />
              <button
                type="button"
                className="absolute right-3 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground"
                onClick={() => setShowPassword(!showPassword)}
              >
                {showPassword ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
              </button>
            </div>
          </div>
          <div className="space-y-2">
            <Label htmlFor="confirm_password">Xác nhận mật khẩu <span className="text-destructive">*</span></Label>
            <Input
              id="confirm_password"
              name="confirm_password"
              type="password"
              placeholder="Nhập lại mật khẩu"
              value={form.confirm_password}
              onChange={handleChange}
              autoComplete="new-password"
              disabled={isLoading}
            />
          </div>
        </CardContent>
        <CardFooter className="flex flex-col gap-3">
          <Button type="submit" className="w-full" disabled={isLoading}>
            {isLoading ? (
              <div className="flex items-center gap-2">
                <div className="h-4 w-4 animate-spin rounded-full border-2 border-primary-foreground border-t-transparent" />
                Đang tạo tài khoản...
              </div>
            ) : (
              "Tạo tài khoản"
            )}
          </Button>
          <p className="text-center text-sm text-muted-foreground">
            Đã có tài khoản?{" "}
            <Link href="/login" className="font-medium text-primary hover:underline">
              Đăng nhập
            </Link>
          </p>
        </CardFooter>
      </form>
    </Card>
  )
}
