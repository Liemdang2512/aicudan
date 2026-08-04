"use client"

import React, { useEffect, useState } from "react"
import { useRouter, usePathname } from "next/navigation"
import { Sidebar } from "@/components/layout/sidebar"
import { Header } from "@/components/layout/header"
import { useAuthStore } from "@/stores/auth-store"

export default function DashboardLayout({
  children,
}: {
  children: React.ReactNode
}) {
  const router = useRouter()
  const pathname = usePathname()
  const { isAuthenticated, isLoading, loadFromStorage } = useAuthStore()
  const [sidebarOpen, setSidebarOpen] = useState(false)

  // Fix Radix UI/react-remove-scroll leaks on navigation.
  // DismissableLayer sets body.style.pointerEvents="none" (via useEffect).
  // react-remove-scroll-bar sets data-scroll-locked attr → body overflow:hidden.
  // Both leak when user navigates while a Dialog/Select is open.
  // setTimeout(0) defers cleanup to a macrotask AFTER all React effect cleanups run,
  // avoiding races with DismissableLayer's own cleanup.
  useEffect(() => {
    const id = setTimeout(() => {
      document.body.style.pointerEvents = ""
      document.body.style.overflow = ""
      document.body.removeAttribute("data-scroll-locked")
    }, 0)
    return () => clearTimeout(id)
  }, [pathname])

  useEffect(() => {
    void loadFromStorage()
  }, [loadFromStorage])

  useEffect(() => {
    if (!isLoading && !isAuthenticated) {
      router.push("/login")
    }
  }, [isLoading, isAuthenticated, router])

  if (isLoading) {
    return (
      <div className="flex h-screen items-center justify-center">
        <div className="flex flex-col items-center gap-4">
          <div className="h-8 w-8 animate-spin rounded-full border-4 border-primary border-t-transparent" />
          <p className="text-sm text-muted-foreground">Đang tải...</p>
        </div>
      </div>
    )
  }

  if (!isAuthenticated) {
    return null
  }

  return (
    <div className="flex h-screen overflow-hidden">
      <Sidebar isOpen={sidebarOpen} onClose={() => setSidebarOpen(false)} />
      <div className="flex flex-1 flex-col overflow-hidden">
        <Header onMenuToggle={() => setSidebarOpen(!sidebarOpen)} />
        <main className="flex-1 overflow-y-auto bg-muted/30 p-4 sm:p-6 lg:p-8">
          {children}
        </main>
      </div>
    </div>
  )
}
