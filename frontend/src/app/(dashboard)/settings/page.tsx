"use client"

import React, { useState, useEffect } from "react"
import {
  Settings,
  Plus,
  Pencil,
  Trash2,
  Loader2,
  DollarSign,
  MessageCircle,
  CheckCircle2,
  XCircle,
  Building2,
  Users,
  UserPlus,
  ShieldCheck,
  ShieldOff,
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
import { apiGet, apiPost, apiPatch, apiDelete } from "@/lib/api"
import { useAuthStore } from "@/stores/auth-store"
import type {
  FixedPriceConfig,
  PriceConfigContract,
  PriceTier,
  TieredPriceConfig,
} from "@/lib/types"
import { toast } from "@/components/ui/use-toast"

type PriceConfig = PriceConfigContract
type PricingType = PriceConfig["pricing_type"]
type TierConfig = PriceTier

export default function SettingsPage() {
  const [priceConfigs, setPriceConfigs] = useState<PriceConfig[]>([])
  const [isLoading, setIsLoading] = useState(true)
  const [showDialog, setShowDialog] = useState(false)
  const [editingConfig, setEditingConfig] = useState<PriceConfig | null>(null)
  const [showDeleteDialog, setShowDeleteDialog] = useState(false)
  const [deleteTarget, setDeleteTarget] = useState<PriceConfig | null>(null)

  // Form state
  const [formName, setFormName] = useState("")
  const [formType, setFormType] = useState<PricingType>("tiered")
  const [formFixedPrice, setFormFixedPrice] = useState("3500")
  const [formTiers, setFormTiers] = useState<TierConfig[]>([
    { min: 0, max: 50, price: 1984 },
    { min: 51, max: 100, price: 2050 },
    { min: 101, max: 200, price: 2417 },
    { min: 201, max: 300, price: 2953 },
    { min: 301, max: 400, price: 3351 },
    { min: 401, max: null, price: 3460 },
  ])
  const [formVat, setFormVat] = useState("8")

  // API config state
  const [telegramToken, setTelegramToken] = useState("")
  const [configSaving, setConfigSaving] = useState(false)
  const [telegramKeySet, setTelegramKeySet] = useState(false)
  const [telegramMasked, setTelegramMasked] = useState("")

  // Payment info state
  const [paymentUnit, setPaymentUnit] = useState("")
  const [paymentBankAccount, setPaymentBankAccount] = useState("")
  const [paymentBankName, setPaymentBankName] = useState("")
  const [paymentAccountHolder, setPaymentAccountHolder] = useState("")
  const [paymentSaving, setPaymentSaving] = useState(false)

  // Bot KTV settings state
  const [ktvBotToken, setKtvBotToken] = useState("")
  const [ktvPassword, setKtvPassword] = useState("")
  const [ktvBotTokenSet, setKtvBotTokenSet] = useState(false)
  const [ktvBotTokenMasked, setKtvBotTokenMasked] = useState("")
  const [ktvPasswordSet, setKtvPasswordSet] = useState(false)
  const [ktvSaving, setKtvSaving] = useState(false)

  // Manager chat ID state
  const [managerChatId, setManagerChatId] = useState("")
  const [managerChatIdSaving, setManagerChatIdSaving] = useState(false)

  // Account management state
  const { user: currentUser } = useAuthStore()
  const [accounts, setAccounts] = useState<Array<{ id: number; email: string; full_name: string; phone: string | null; role: string; is_active: boolean; created_at: string }>>([])
  const [accountsLoading, setAccountsLoading] = useState(false)
  const [showUserDialog, setShowUserDialog] = useState(false)
  const [userFormLoading, setUserFormLoading] = useState(false)
  const [userForm, setUserForm] = useState({ full_name: "", email: "", phone: "", password: "" })

  useEffect(() => {
    fetchPriceConfigs()
    fetchAppSettings()
    fetchAccounts()
  }, [])

  const fetchAccounts = async () => {
    setAccountsLoading(true)
    try {
      const data = await apiGet<typeof accounts>("/users")
      setAccounts(data)
    } catch {
      // ignore
    } finally {
      setAccountsLoading(false)
    }
  }

  const handleCreateUser = async () => {
    if (!userForm.full_name || !userForm.email || !userForm.password) {
      toast({ title: "Lỗi", description: "Vui lòng điền đầy đủ thông tin bắt buộc", variant: "destructive" })
      return
    }
    if (userForm.password.length < 8) {
      toast({ title: "Lỗi", description: "Mật khẩu phải có ít nhất 8 ký tự", variant: "destructive" })
      return
    }
    setUserFormLoading(true)
    try {
      await apiPost("/users", {
        full_name: userForm.full_name,
        email: userForm.email,
        phone: userForm.phone || null,
        password: userForm.password,
      })
      toast({ title: "Tạo thành công", description: `Tài khoản ${userForm.email} đã được tạo`, variant: "success" })
      setShowUserDialog(false)
      setUserForm({ full_name: "", email: "", phone: "", password: "" })
      fetchAccounts()
    } catch (error) {
      toast({ title: "Lỗi", description: error instanceof Error ? error.message : "Không thể tạo tài khoản", variant: "destructive" })
    } finally {
      setUserFormLoading(false)
    }
  }

  const handleToggleActive = async (userId: number, isActive: boolean) => {
    try {
      await apiPatch(`/users/${userId}/toggle-active`, {})
      toast({ title: isActive ? "Đã khóa tài khoản" : "Đã mở khóa tài khoản", variant: "success" })
      fetchAccounts()
    } catch (error) {
      toast({ title: "Lỗi", description: error instanceof Error ? error.message : "Không thể thực hiện", variant: "destructive" })
    }
  }

  const fetchAppSettings = async () => {
    try {
      const data = await apiGet<{
        telegram_bot_token_set: boolean
        telegram_bot_token_masked: string
        payment_management_unit: string
        payment_bank_account: string
        payment_bank_name: string
        payment_account_holder: string
        telegram_ktv_bot_token_set: boolean
        telegram_ktv_bot_token_masked: string
        telegram_ktv_password_set: boolean
        manager_telegram_chat_id: string
      }>("/settings")
      setTelegramKeySet(data.telegram_bot_token_set)
      setTelegramMasked(data.telegram_bot_token_masked)
      setPaymentUnit(data.payment_management_unit || "")
      setPaymentBankAccount(data.payment_bank_account || "")
      setPaymentBankName(data.payment_bank_name || "")
      setPaymentAccountHolder(data.payment_account_holder || "")
      setKtvBotTokenSet(data.telegram_ktv_bot_token_set)
      setKtvBotTokenMasked(data.telegram_ktv_bot_token_masked)
      setKtvPasswordSet(data.telegram_ktv_password_set)
      setManagerChatId(data.manager_telegram_chat_id || "")
    } catch {
      // Settings API might not be available yet
    }
  }

  const handleSaveConfig = async (field: "telegram") => {
    setConfigSaving(true)
    try {
      const payload: Record<string, string> = {}
      if (field === "telegram" && telegramToken) {
        payload.telegram_bot_token = telegramToken
      }

      await apiPatch("/settings", payload)
      toast({
        title: "Lưu thành công",
        description: "Telegram Bot Token đã được cập nhật",
        variant: "success",
      })
      setTelegramToken("")
      fetchAppSettings()
    } catch (error) {
      toast({
        title: "Lỗi",
        description: error instanceof Error ? error.message : "Không thể lưu cấu hình",
        variant: "destructive",
      })
    } finally {
      setConfigSaving(false)
    }
  }

  const handleSavePayment = async () => {
    setPaymentSaving(true)
    try {
      await apiPatch("/settings", {
        payment_management_unit: paymentUnit,
        payment_bank_account: paymentBankAccount,
        payment_bank_name: paymentBankName,
        payment_account_holder: paymentAccountHolder,
      })
      toast({
        title: "Lưu thành công",
        description: "Thông tin thanh toán đã được cập nhật",
        variant: "success",
      })
    } catch (error) {
      toast({
        title: "Lỗi",
        description: error instanceof Error ? error.message : "Không thể lưu thông tin thanh toán",
        variant: "destructive",
      })
    } finally {
      setPaymentSaving(false)
    }
  }

  const handleSaveKtv = async () => {
    setKtvSaving(true)
    try {
      const payload: Record<string, string> = {}
      if (ktvBotToken) payload.telegram_ktv_bot_token = ktvBotToken
      if (ktvPassword) payload.telegram_ktv_password = ktvPassword
      if (Object.keys(payload).length === 0) {
        toast({ title: "Không có thay đổi", description: "Nhập token hoặc mật khẩu mới", variant: "destructive" })
        return
      }
      await apiPatch("/settings", payload)
      toast({ title: "Lưu thành công", description: "Cài đặt Bot KTV đã được cập nhật", variant: "success" })
      setKtvBotToken("")
      setKtvPassword("")
      fetchAppSettings()
    } catch (error) {
      toast({ title: "Lỗi", description: error instanceof Error ? error.message : "Không thể lưu", variant: "destructive" })
    } finally {
      setKtvSaving(false)
    }
  }

  const handleSaveManagerChatId = async () => {
    setManagerChatIdSaving(true)
    try {
      await apiPatch("/settings", { manager_telegram_chat_id: managerChatId })
      toast({ title: "Lưu thành công", description: "Manager Chat ID đã được cập nhật", variant: "success" })
      fetchAppSettings()
    } catch (error) {
      toast({ title: "Lỗi", description: error instanceof Error ? error.message : "Không thể lưu", variant: "destructive" })
    } finally {
      setManagerChatIdSaving(false)
    }
  }

  const fetchPriceConfigs = async () => {
    setIsLoading(true)
    try {
      const data = await apiGet<PriceConfig[]>("/price-configs")
      setPriceConfigs(data)
    } catch (error) {
      toast({
        title: "Lỗi",
        description: "Không thể tải danh sách bảng giá",
        variant: "destructive",
      })
    } finally {
      setIsLoading(false)
    }
  }

  const openCreateDialog = () => {
    setEditingConfig(null)
    setFormName("")
    setFormType("tiered")
    setFormFixedPrice("3500")
    setFormTiers([
      { min: 0, max: 50, price: 1984 },
      { min: 51, max: 100, price: 2050 },
      { min: 101, max: 200, price: 2417 },
      { min: 201, max: 300, price: 2953 },
      { min: 301, max: 400, price: 3351 },
      { min: 401, max: null, price: 3460 },
    ])
    setFormVat("8")
    setShowDialog(true)
  }

  const openEditDialog = (config: PriceConfig) => {
    setEditingConfig(config)
    setFormName(config.config_name)
    setFormType(config.pricing_type)

    try {
      const parsed = JSON.parse(config.config_json) as
        | FixedPriceConfig
        | TieredPriceConfig
      if (config.pricing_type === "fixed") {
        const fixedConfig = parsed as FixedPriceConfig
        setFormFixedPrice(fixedConfig.price.toString())
        setFormVat(((fixedConfig.vat ?? 0) * 100).toString())
      } else {
        const tieredConfig = parsed as TieredPriceConfig
        setFormTiers(tieredConfig.tiers)
        setFormVat((tieredConfig.vat * 100).toString())
      }
    } catch {
      // Use defaults
    }

    setShowDialog(true)
  }

  const handleSave = async () => {
    if (!formName) {
      toast({
        title: "Lỗi",
        description: "Vui lòng nhập tên bảng giá",
        variant: "destructive",
      })
      return
    }

    const configJson =
      formType === "fixed"
        ? JSON.stringify({
            price: parseFloat(formFixedPrice),
            vat: parseFloat(formVat) / 100,
          })
        : JSON.stringify({
            tiers: formTiers,
            vat: parseFloat(formVat) / 100,
          })

    const payload = {
      config_name: formName,
      pricing_type: formType,
      config_json: configJson,
    }

    try {
      if (editingConfig) {
        await apiPatch(`/price-configs/${editingConfig.id}`, payload)
        toast({
          title: "Cập nhật thành công",
          description: "Bảng giá đã được cập nhật",
          variant: "success",
        })
      } else {
        await apiPost("/price-configs", payload)
        toast({
          title: "Tạo thành công",
          description: "Bảng giá mới đã được tạo",
          variant: "success",
        })
      }
      setShowDialog(false)
      fetchPriceConfigs()
    } catch (error) {
      toast({
        title: "Lỗi",
        description:
          error instanceof Error ? error.message : "Không thể lưu bảng giá",
        variant: "destructive",
      })
    }
  }

  const confirmDelete = (config: PriceConfig) => {
    setDeleteTarget(config)
    setShowDeleteDialog(true)
  }

  const handleDelete = async () => {
    if (!deleteTarget) return

    try {
      await apiDelete(`/price-configs/${deleteTarget.id}`)
      toast({
        title: "Đã xóa",
        description: "Bảng giá đã được xóa",
        variant: "success",
      })
      fetchPriceConfigs()
    } catch (error) {
      toast({
        title: "Lỗi",
        description:
          error instanceof Error ? error.message : "Không thể xóa bảng giá",
        variant: "destructive",
      })
    } finally {
      setShowDeleteDialog(false)
      setDeleteTarget(null)
    }
  }

  const updateTier = (
    index: number,
    field: keyof TierConfig,
    value: string
  ) => {
    setFormTiers((prev) => {
      const updated = [...prev]
      if (field === "max" && value === "") {
        updated[index] = { ...updated[index], max: null }
      } else {
        updated[index] = {
          ...updated[index],
          [field]: parseFloat(value) || 0,
        }
      }
      return updated
    })
  }

  const addTier = () => {
    setFormTiers((prev) => {
      if (prev.length === 0) {
        return [{ min: 0, max: null, price: 0 }]
      }

      const updated = [...prev]
      const lastTier = updated[updated.length - 1]
      const lastMax = lastTier.max ?? lastTier.min + 99
      updated[updated.length - 1] = { ...lastTier, max: lastMax }
      return [...updated, { min: lastMax + 1, max: null, price: 0 }]
    })
  }

  const removeTier = (index: number) => {
    if (formTiers.length <= 1) return
    setFormTiers((prev) => prev.filter((_, i) => i !== index))
  }

  const formatPrice = (price: number) => {
    return new Intl.NumberFormat("vi-VN").format(price) + "đ/kWh"
  }

  const parseConfigDisplay = (config: PriceConfig) => {
    try {
      const parsed = JSON.parse(config.config_json) as
        | FixedPriceConfig
        | TieredPriceConfig
      if (config.pricing_type === "fixed") {
        const fixedConfig = parsed as FixedPriceConfig
        return `${formatPrice(fixedConfig.price)} + VAT ${(fixedConfig.vat ?? 0) * 100}%`
      } else {
        const tieredConfig = parsed as TieredPriceConfig
        return `${tieredConfig.tiers.length} bậc + VAT ${tieredConfig.vat * 100}%`
      }
    } catch {
      return "N/A"
    }
  }

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
      <div>
        <h1 className="text-3xl font-bold tracking-tight">Cài đặt</h1>
        <p className="text-muted-foreground">
          Quản lý bảng giá điện và cấu hình hệ thống
        </p>
      </div>

      {/* Price configs */}
      <Card>
        <CardHeader>
          <div className="flex items-center justify-between">
            <div>
              <CardTitle className="flex items-center gap-2">
                <DollarSign className="h-5 w-5" />
                Bảng giá điện
              </CardTitle>
              <CardDescription>
                Cấu hình bảng giá bậc thang hoặc giá cố định
              </CardDescription>
            </div>
            <Button onClick={openCreateDialog}>
              <Plus className="mr-2 h-4 w-4" />
              Thêm bảng giá
            </Button>
          </div>
        </CardHeader>
        <CardContent>
          {priceConfigs.length === 0 ? (
            <div className="flex flex-col items-center justify-center py-12 text-center">
              <DollarSign className="mb-3 h-12 w-12 text-muted-foreground/50" />
              <p className="text-lg font-medium">Chưa có bảng giá nào</p>
              <p className="text-sm text-muted-foreground">
                Thêm bảng giá để bắt đầu tính hóa đơn
              </p>
            </div>
          ) : (
            <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
              {priceConfigs.map((config) => (
                <div
                  key={config.id}
                  className="rounded-lg border p-4 transition-colors hover:bg-muted/50"
                >
                  <div className="flex items-start justify-between">
                    <div className="space-y-1">
                      <div className="flex items-center gap-2">
                        <span className="font-medium">{config.config_name}</span>
                        {config.is_default && (
                          <Badge variant="success" className="text-xs">
                            Mặc định
                          </Badge>
                        )}
                      </div>
                      <Badge
                        variant={
                          config.pricing_type === "tiered"
                            ? "default"
                            : "secondary"
                        }
                        className="text-xs"
                      >
                        {config.pricing_type === "tiered"
                          ? "Bậc thang"
                          : "Cố định"}
                      </Badge>
                      <p className="text-sm text-muted-foreground">
                        {parseConfigDisplay(config)}
                      </p>
                    </div>
                    <div className="flex gap-1">
                      <Button
                        variant="ghost"
                        size="icon"
                        className="h-8 w-8"
                        onClick={() => openEditDialog(config)}
                      >
                        <Pencil className="h-3.5 w-3.5" />
                      </Button>
                      <Button
                        variant="ghost"
                        size="icon"
                        className="h-8 w-8 text-red-500 hover:text-red-600"
                        onClick={() => confirmDelete(config)}
                      >
                        <Trash2 className="h-3.5 w-3.5" />
                      </Button>
                    </div>
                  </div>
                </div>
              ))}
            </div>
          )}
        </CardContent>
      </Card>

      {/* API Configurations */}
      <div className="grid gap-6">
        {/* Payment info for PDF invoice */}
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <Building2 className="h-5 w-5" />
              Thông tin thanh toán (hiển thị trên hóa đơn PDF)
            </CardTitle>
            <CardDescription>
              Thông tin ngân hàng và đơn vị quản lý để in trên hóa đơn gửi cư dân
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="grid gap-3 sm:grid-cols-2">
              <div className="space-y-2">
                <Label>Đơn vị quản lý</Label>
                <Input
                  value={paymentUnit}
                  onChange={(e) => setPaymentUnit(e.target.value)}
                  placeholder="Ví dụ: Công Ty Cổ Phần SAVISTA"
                />
              </div>
              <div className="space-y-2">
                <Label>Số tài khoản ngân hàng</Label>
                <Input
                  value={paymentBankAccount}
                  onChange={(e) => setPaymentBankAccount(e.target.value)}
                  placeholder="Ví dụ: 113 002 965 007"
                />
              </div>
              <div className="space-y-2">
                <Label>Tên ngân hàng</Label>
                <Input
                  value={paymentBankName}
                  onChange={(e) => setPaymentBankName(e.target.value)}
                  placeholder="Ví dụ: VIETINBANK-CN2-TPHCM"
                />
              </div>
              <div className="space-y-2">
                <Label>Chủ tài khoản</Label>
                <Input
                  value={paymentAccountHolder}
                  onChange={(e) => setPaymentAccountHolder(e.target.value)}
                  placeholder="Ví dụ: Công Ty Cổ Phần SAVISTA"
                />
              </div>
            </div>
            <Button
              disabled={paymentSaving}
              onClick={handleSavePayment}
            >
              {paymentSaving ? (
                <Loader2 className="mr-2 h-4 w-4 animate-spin" />
              ) : (
                <Settings className="mr-2 h-4 w-4" />
              )}
              Lưu thông tin thanh toán
            </Button>
          </CardContent>
        </Card>

        {/* Telegram Bot Token */}
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <MessageCircle className="h-5 w-5" />
              Telegram Bot
              {telegramKeySet ? (
                <CheckCircle2 className="h-4 w-4 text-green-500" />
              ) : (
                <XCircle className="h-4 w-4 text-red-500" />
              )}
            </CardTitle>
            <CardDescription>
              Bot token để gửi thông báo hóa đơn qua Telegram
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            {telegramKeySet && (
              <div className="rounded-md bg-green-50 p-3 dark:bg-green-950">
                <p className="text-sm text-green-800 dark:text-green-200">
                  Token hiện tại: <code className="font-mono">{telegramMasked}</code>
                </p>
              </div>
            )}
            <div className="space-y-2">
              <Label>{telegramKeySet ? "Thay đổi Bot Token" : "Nhập Bot Token"}</Label>
              <Input
                type="password"
                value={telegramToken}
                onChange={(e) => setTelegramToken(e.target.value)}
                placeholder="Nhập Telegram Bot Token"
              />
              <p className="text-xs text-muted-foreground">
                Tạo bot mới tại @BotFather trên Telegram để lấy token
              </p>
            </div>
            <Button
              disabled={configSaving || !telegramToken}
              onClick={() => handleSaveConfig("telegram")}
            >
              {configSaving ? (
                <Loader2 className="mr-2 h-4 w-4 animate-spin" />
              ) : (
                <Settings className="mr-2 h-4 w-4" />
              )}
              Lưu Bot Token
            </Button>
          </CardContent>
        </Card>

        {/* Bot KTV Token and Password */}
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <MessageCircle className="h-5 w-5" />
              Bot KTV (Kỹ Thuật Viên)
              {ktvBotTokenSet ? (
                <CheckCircle2 className="h-4 w-4 text-green-500" />
              ) : (
                <XCircle className="h-4 w-4 text-red-500" />
              )}
            </CardTitle>
            <CardDescription>
              Bot riêng cho kỹ thuật viên gửi ảnh đồng hồ. Cần token từ @BotFather và mật khẩu dùng chung cho KTV.
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            {ktvBotTokenSet && (
              <div className="rounded-md bg-green-50 p-3 dark:bg-green-950">
                <p className="text-sm text-green-800 dark:text-green-200">
                  Token KTV hiện tại: <code className="font-mono">{ktvBotTokenMasked}</code>
                </p>
              </div>
            )}
            <div className="space-y-2">
              <Label>{ktvBotTokenSet ? "Thay đổi Bot KTV Token" : "Nhập Bot KTV Token"}</Label>
              <Input
                type="password"
                value={ktvBotToken}
                onChange={(e) => setKtvBotToken(e.target.value)}
                placeholder="Token của Bot KTV từ @BotFather"
              />
            </div>
            <div className="space-y-2">
              <Label>
                Mật khẩu KTV
                {ktvPasswordSet && <span className="ml-2 text-xs text-green-600">Đã cấu hình</span>}
              </Label>
              <Input
                type="password"
                value={ktvPassword}
                onChange={(e) => setKtvPassword(e.target.value)}
                placeholder="Mật khẩu để KTV xác thực bot (mật khẩu chung)"
              />
              <p className="text-xs text-muted-foreground">
                KTV dùng lệnh /ktv [mật khẩu này] để xác thực Bot KTV
              </p>
            </div>
            <Button
              disabled={ktvSaving || (!ktvBotToken && !ktvPassword)}
              onClick={handleSaveKtv}
            >
              {ktvSaving ? (
                <Loader2 className="mr-2 h-4 w-4 animate-spin" />
              ) : (
                <Settings className="mr-2 h-4 w-4" />
              )}
              Lưu cài đặt Bot KTV
            </Button>
          </CardContent>
        </Card>

        {/* Manager Chat ID */}
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <MessageCircle className="h-5 w-5" />
              Nhận thông báo từ KTV
            </CardTitle>
            <CardDescription>
              Chat ID của quản lý để nhận thông báo khi KTV hoàn thành ghi chỉ số. Lấy ID bằng cách gõ /id trong Bot Manager.
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="space-y-2">
              <Label>Manager Chat ID</Label>
              <Input
                value={managerChatId}
                onChange={(e) => setManagerChatId(e.target.value)}
                placeholder="Ví dụ: 123456789"
              />
              <p className="text-xs text-muted-foreground">
                Gõ /id trong Bot Manager để lấy Chat ID của bạn
              </p>
            </div>
            <Button
              disabled={managerChatIdSaving}
              onClick={handleSaveManagerChatId}
            >
              {managerChatIdSaving ? (
                <Loader2 className="mr-2 h-4 w-4 animate-spin" />
              ) : (
                <Settings className="mr-2 h-4 w-4" />
              )}
              Lưu Manager Chat ID
            </Button>
          </CardContent>
        </Card>
      </div>

      {/* Price config dialog */}
      <Dialog open={showDialog} onOpenChange={setShowDialog}>
        <DialogContent className="max-h-[80vh] overflow-y-auto sm:max-w-xl">
          <DialogHeader>
            <DialogTitle>
              {editingConfig ? "Sửa bảng giá" : "Thêm bảng giá mới"}
            </DialogTitle>
            <DialogDescription>
              {editingConfig
                ? "Cập nhật thông tin bảng giá"
                : "Tạo bảng giá điện mới cho hệ thống"}
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-4 py-4">
            <div className="space-y-2">
              <Label>Tên bảng giá *</Label>
              <Input
                value={formName}
                onChange={(e) => setFormName(e.target.value)}
                placeholder="Ví dụ: Giá EVN 2025, Giá cố định..."
              />
            </div>
            <div className="space-y-2">
              <Label>Loại giá</Label>
              <Select
                value={formType}
                onValueChange={(value: PricingType) => setFormType(value)}
              >
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="tiered">Bậc thang (EVN)</SelectItem>
                  <SelectItem value="fixed">Giá cố định</SelectItem>
                </SelectContent>
              </Select>
            </div>

            {formType === "fixed" ? (
              <div className="space-y-2">
                <Label>Giá mỗi kWh (VND)</Label>
                <Input
                  type="number"
                  value={formFixedPrice}
                  onChange={(e) => setFormFixedPrice(e.target.value)}
                  placeholder="3500"
                />
              </div>
            ) : (
              <div className="space-y-3">
                <div className="flex items-center justify-between">
                  <Label>Các bậc giá</Label>
                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    onClick={addTier}
                  >
                    <Plus className="mr-1 h-3 w-3" />
                    Thêm bậc
                  </Button>
                </div>
                {formTiers.map((tier, index) => (
                  <div
                    key={index}
                    className="flex items-center gap-2 rounded-lg border p-3"
                  >
                    <div className="flex-1 space-y-1">
                      <p className="text-xs font-medium text-muted-foreground">
                        Bậc {index + 1}
                      </p>
                      <div className="flex items-center gap-2">
                        <Input
                          type="number"
                          value={tier.min}
                          onChange={(e) =>
                            updateTier(index, "min", e.target.value)
                          }
                          className="h-8 text-xs"
                          placeholder="Từ"
                        />
                        <span className="text-xs">-</span>
                        <Input
                          type="number"
                          value={tier.max ?? ""}
                          onChange={(e) =>
                            updateTier(index, "max", e.target.value)
                          }
                          className="h-8 text-xs"
                          placeholder="Đến (trống = ∞)"
                        />
                        <span className="text-xs">kWh:</span>
                        <Input
                          type="number"
                          value={tier.price}
                          onChange={(e) =>
                            updateTier(index, "price", e.target.value)
                          }
                          className="h-8 text-xs"
                          placeholder="Giá"
                        />
                        <span className="text-xs whitespace-nowrap">đ/kWh</span>
                      </div>
                    </div>
                    {formTiers.length > 1 && (
                      <Button
                        type="button"
                        variant="ghost"
                        size="icon"
                        className="h-8 w-8 text-red-500"
                        onClick={() => removeTier(index)}
                      >
                        <Trash2 className="h-3.5 w-3.5" />
                      </Button>
                    )}
                  </div>
                ))}
              </div>
            )}

            <div className="space-y-2">
              <Label>VAT (%)</Label>
              <Input
                type="number"
                value={formVat}
                onChange={(e) => setFormVat(e.target.value)}
                placeholder="8"
              />
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setShowDialog(false)}>
              Hủy
            </Button>
            <Button onClick={handleSave}>
              {editingConfig ? "Cập nhật" : "Tạo mới"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Account management */}
      <Card>
        <CardHeader>
          <div className="flex items-center justify-between">
            <div>
              <CardTitle className="flex items-center gap-2">
                <Users className="h-5 w-5" />
                Quản lý tài khoản
              </CardTitle>
              <CardDescription>
                Tạo và quản lý tài khoản quản trị viên
              </CardDescription>
            </div>
            <Button onClick={() => setShowUserDialog(true)}>
              <UserPlus className="mr-2 h-4 w-4" />
              Tạo tài khoản
            </Button>
          </div>
        </CardHeader>
        <CardContent>
          {accountsLoading ? (
            <div className="flex items-center justify-center py-8">
              <Loader2 className="h-6 w-6 animate-spin text-primary" />
            </div>
          ) : accounts.length === 0 ? (
            <div className="flex flex-col items-center justify-center py-10 text-center">
              <Users className="mb-3 h-10 w-10 text-muted-foreground/50" />
              <p className="text-sm text-muted-foreground">Chưa có tài khoản nào</p>
            </div>
          ) : (
            <div className="divide-y">
              {accounts.map((acc) => (
                <div key={acc.id} className="flex items-center justify-between py-3">
                  <div className="space-y-0.5">
                    <div className="flex items-center gap-2">
                      <span className="font-medium">{acc.full_name}</span>
                      {acc.id === currentUser?.id && (
                        <Badge variant="secondary" className="text-xs">Bạn</Badge>
                      )}
                      <Badge variant={acc.is_active ? "success" : "outline"} className="text-xs">
                        {acc.is_active ? "Hoạt động" : "Đã khóa"}
                      </Badge>
                    </div>
                    <p className="text-sm text-muted-foreground">{acc.email}</p>
                  </div>
                  {acc.id !== currentUser?.id && (
                    <Button
                      variant="ghost"
                      size="sm"
                      className={acc.is_active ? "text-red-500 hover:text-red-600" : "text-green-600 hover:text-green-700"}
                      onClick={() => handleToggleActive(acc.id, acc.is_active)}
                    >
                      {acc.is_active ? (
                        <><ShieldOff className="mr-1 h-4 w-4" />Khóa</>
                      ) : (
                        <><ShieldCheck className="mr-1 h-4 w-4" />Mở khóa</>
                      )}
                    </Button>
                  )}
                </div>
              ))}
            </div>
          )}
        </CardContent>
      </Card>

      {/* Create user dialog */}
      <Dialog open={showUserDialog} onOpenChange={setShowUserDialog}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>Tạo tài khoản mới</DialogTitle>
            <DialogDescription>Tạo tài khoản quản trị viên mới cho hệ thống</DialogDescription>
          </DialogHeader>
          <div className="space-y-4 py-4">
            <div className="space-y-2">
              <Label>Họ và tên <span className="text-destructive">*</span></Label>
              <Input
                placeholder="Nguyễn Văn A"
                value={userForm.full_name}
                onChange={(e) => setUserForm((f) => ({ ...f, full_name: e.target.value }))}
                disabled={userFormLoading}
              />
            </div>
            <div className="space-y-2">
              <Label>Email <span className="text-destructive">*</span></Label>
              <Input
                type="email"
                placeholder="admin@example.com"
                value={userForm.email}
                onChange={(e) => setUserForm((f) => ({ ...f, email: e.target.value }))}
                disabled={userFormLoading}
              />
            </div>
            <div className="space-y-2">
              <Label>Số điện thoại</Label>
              <Input
                type="tel"
                placeholder="0901234567"
                value={userForm.phone}
                onChange={(e) => setUserForm((f) => ({ ...f, phone: e.target.value }))}
                disabled={userFormLoading}
              />
            </div>
            <div className="space-y-2">
              <Label>Mật khẩu <span className="text-destructive">*</span></Label>
              <Input
                type="password"
                placeholder="Ít nhất 8 ký tự"
                value={userForm.password}
                onChange={(e) => setUserForm((f) => ({ ...f, password: e.target.value }))}
                disabled={userFormLoading}
              />
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setShowUserDialog(false)} disabled={userFormLoading}>Hủy</Button>
            <Button onClick={handleCreateUser} disabled={userFormLoading}>
              {userFormLoading ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <UserPlus className="mr-2 h-4 w-4" />}
              Tạo tài khoản
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Delete confirmation */}
      <Dialog open={showDeleteDialog} onOpenChange={setShowDeleteDialog}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Xác nhận xóa</DialogTitle>
            <DialogDescription>
              Bạn có chắc muốn xóa bảng giá{" "}
              <strong>{deleteTarget?.config_name}</strong>? Hành động này không
              thể hoàn tác.
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
    </div>
  )
}
