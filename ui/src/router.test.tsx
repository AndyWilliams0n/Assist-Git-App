import { describe, expect, it } from "vitest"

import { router } from "@/router"

describe("router", () => {
  it("exposes only Workspace and Git routes inside the main layout", () => {
    const protectedRoot = router.routes.find((route) => route.path === "/")
    expect(protectedRoot).toBeDefined()

    const rootChildren = protectedRoot?.children ?? []
    const mainLayout = rootChildren.find((route) => !route.path)
    expect(mainLayout).toBeDefined()

    const routePaths = (mainLayout?.children ?? []).map((route) => route.path ?? "(index)")
    expect(routePaths).toEqual(["(index)", "git", "workspace"])

    expect(routePaths).not.toContain("chat")
    expect(routePaths).not.toContain("agents-pipeline")
    expect(routePaths).not.toContain("pipelines")
    expect(routePaths).not.toContain("stitch")
    expect(routePaths).not.toContain("prompt")
  })
})
