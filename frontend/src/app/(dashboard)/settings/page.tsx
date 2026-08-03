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
  Bot,
  CheckCircle2,
  XCircle,
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
  const [geminiApiKey, setGeminiApiKey] = useState("")
  const [telegramToken, setTelegramToken] = useState("")
  const [configSaving, setConfigSaving] = useState(false)
  const [geminiKeySet, setGeminiKeySet] = useState(false)
  const [telegramKeySet, setTelegramKeySet] = useState(false)
  const [geminiMasked, setGeminiMasked] = useState("")
  const [telegramMasked, setTelegramMasked] = useState("")

  useEffect(() => {
    fetchPriceConfigs()
    fetchAppSettings()
  }, [])

  const fetchAppSettings = async () => {
    try {
      const data = await apiGet<{
        gemini_api_key_set: boolean
        telegram_bot_token_set: boolean
        gemini_api_key_masked: string
        telegram_bot_token_masked: string
      }>("/settings")
      setGeminiKeySet(data.gemini_api_key_set)
      setTelegramKeySet(data.telegram_bot_token_set)
      setGeminiMasked(data.gemini_api_key_masked)
      setTelegramMasked(data.telegram_bot_token_masked)
    } catch {
      // Settings API might not be available yet
    }
  }

  const handleSaveConfig = async (field: "gemini" | "telegram") => {
    setConfigSaving(true)
    try {
      const payload: Record<string, string> = {}
      if (field === "gemini" && geminiApiKey) {
        payload.gemini_api_key = geminiApiKey
      }
      if (field === "telegram" && telegramToken) {
        payload.telegram_bot_token = telegramToken
      }

      await apiPatch("/settings", payload)
      toast({
        title: "Lưu thành công",
        description: field === "gemini" ? "Gemini API Key đã được cập nhật" : "Telegram Bot Token đã được cập nhật",
        variant: "success",
      })
      setGeminiApiKey("")
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
      <div className="grid gap-6 lg:grid-cols-2">
        {/* Gemini API Key */}
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <Bot className="h-5 w-5" />
              Google Gemini AI
              {geminiKeySet ? (
                <CheckCircle2 className="h-4 w-4 text-green-500" />
              ) : (
                <XCircle className="h-4 w-4 text-red-500" />
              )}
            </CardTitle>
            <CardDescription>
              API Key cho nhận dạng chỉ số đồng hồ bằng AI
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            {geminiKeySet && (
              <div className="rounded-md bg-green-50 p-3 dark:bg-green-950">
                <p className="text-sm text-green-800 dark:text-green-200">
                  Key hiện tại: <code className="font-mono">{geminiMasked}</code>
                </p>
              </div>
            )}
            <div className="space-y-2">
              <Label>{geminiKeySet ? "Thay đổi API Key" : "Nhập API Key"}</Label>
              <Input
                type="password"
                value={geminiApiKey}
                onChange={(e) => setGeminiApiKey(e.target.value)}
                placeholder="AIzaSy..."
              />
              <p className="text-xs text-muted-foreground">
                Lấy API Key tại Google AI Studio (aistudio.google.com)
              </p>
            </div>
            <Button
              disabled={configSaving || !geminiApiKey}
              onClick={() => handleSaveConfig("gemini")}
            >
              {configSaving ? (
                <Loader2 className="mr-2 h-4 w-4 animate-spin" />
              ) : (
                <Settings className="mr-2 h-4 w-4" />
              )}
              Lưu API Key
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
