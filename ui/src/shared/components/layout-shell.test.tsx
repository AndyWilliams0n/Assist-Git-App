import { render, screen } from "@testing-library/react"
import { MemoryRouter } from "react-router-dom"
import { beforeEach, describe, expect, it, vi } from "vitest"

import { AppSidebar } from "@/shared/components/app-sidebar"
import { SiteHeader } from "@/shared/components/site-header"
import { SidebarProvider } from "@/shared/components/ui/sidebar"
import { useDashboardSettingsStore } from "@/shared/store/dashboard-settings"

vi.mock("@/shared/hooks/useAuth.ts", () => ({
  useAuth: () => ({
    user: {
      name: "Test User",
      email: "test@example.com",
      picture: "",
    },
    logout: vi.fn(),
  }),
}))

describe("Layout shell", () => {
  beforeEach(() => {
    useDashboardSettingsStore.setState({
      breadcrumbs: [
        { label: "Workspace", href: "/workspace" },
        { label: "Git", href: "/git" },
      ],
      theme: "light",
      primaryWorkspacePath: "",
      secondaryWorkspacePath: null,
      workspacePath: "",
      workspacePickerRequestId: 0,
    })
  })

  it("shows exactly Workspace and Git sidebar primary navigation entries", () => {
    render(
      <MemoryRouter>
        <SidebarProvider>
          <AppSidebar />
        </SidebarProvider>
      </MemoryRouter>
    )

    expect(screen.getByText("Workspace")).toBeInTheDocument()
    expect(screen.getByText("Git")).toBeInTheDocument()

    const primaryLinks = screen.getAllByRole("link").filter((link) => {
      const text = link.textContent?.trim()
      return text === "Workspace" || text === "Git"
    })
    expect(primaryLinks).toHaveLength(2)

    expect(screen.queryByText("Chat")).not.toBeInTheDocument()
    expect(screen.queryByText("Workflow Tasks")).not.toBeInTheDocument()
    expect(screen.queryByText("Spec Creator")).not.toBeInTheDocument()
  })

  it("renders only breadcrumbs and theme toggle in header controls", () => {
    render(
      <MemoryRouter>
        <SidebarProvider>
          <SiteHeader />
        </SidebarProvider>
      </MemoryRouter>
    )

    expect(screen.getByText("Workspace")).toBeInTheDocument()
    expect(screen.getByText("Git")).toBeInTheDocument()
    expect(screen.getByRole("button", { name: "Toggle theme" })).toBeInTheDocument()

    expect(screen.queryByText("Connected")).not.toBeInTheDocument()
    expect(screen.queryByText("Disconnected")).not.toBeInTheDocument()
    expect(screen.queryByText(/Health:/)).not.toBeInTheDocument()
    expect(screen.queryByText("Active")).not.toBeInTheDocument()
    expect(screen.queryByText("Inactive")).not.toBeInTheDocument()
  })
})
