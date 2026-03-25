import * as React from "react"
import { Eye, EyeOff, Save } from "lucide-react"
import { Button } from "@/shared/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/shared/components/ui/card"
import { Input } from "@/shared/components/ui/input"
import { Label } from "@/shared/components/ui/label"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/shared/components/ui/tabs"
import { maskSecret } from "@/shared/utils/secret-sanitizer"
import { useGitHubSettings } from "../hooks/useGitHubRepos"
import { useGitLabSettings } from "../hooks/useGitLabRepos"

export function TokenSettingsCard() {
  const { settings: ghSettings, saveSettings: saveGitHub } = useGitHubSettings()
  const { settings: glSettings, saveSettings: saveGitLab } = useGitLabSettings()

  const [ghToken, setGhToken] = React.useState("")
  const [ghUsername, setGhUsername] = React.useState("")
  const [ghShowToken, setGhShowToken] = React.useState(false)
  const [ghSaving, setGhSaving] = React.useState(false)

  const [glToken, setGlToken] = React.useState("")
  const [glUrl, setGlUrl] = React.useState("https://gitlab.com")
  const [glUsername, setGlUsername] = React.useState("")
  const [glShowToken, setGlShowToken] = React.useState(false)
  const [glSaving, setGlSaving] = React.useState(false)

  React.useEffect(() => {
    if (ghSettings) setGhUsername(ghSettings.username)
  }, [ghSettings])

  React.useEffect(() => {
    if (glSettings) {
      setGlUrl(glSettings.url || "https://gitlab.com")
      setGlUsername(glSettings.username)
    }
  }, [glSettings])

  const ghTokenPlaceholder = ghSettings?.has_token ? `Current: ${maskSecret(ghSettings.token_masked || "")}` : "ghp_..."
  const glTokenPlaceholder = glSettings?.has_token ? `Current: ${maskSecret(glSettings.token_masked || "")}` : "glpat-..."

  const handleSaveGitHub = async () => {
    setGhSaving(true)
    try {
      await saveGitHub(ghToken || undefined, ghUsername || undefined)
      setGhToken("")
    } finally {
      setGhSaving(false)
    }
  }

  const handleSaveGitLab = async () => {
    setGlSaving(true)
    try {
      await saveGitLab(glToken || undefined, glUrl || undefined, glUsername || undefined)
      setGlToken("")
    } finally {
      setGlSaving(false)
    }
  }

  return (
    <Card className="!shadow-none">
      <CardHeader className="pb-3">
        <CardTitle className="text-sm">API Token Settings</CardTitle>
      </CardHeader>
      <CardContent>
        <Tabs defaultValue="github">
          <TabsList className="mb-4">
            <TabsTrigger value="github" className="text-xs">GitHub</TabsTrigger>
            <TabsTrigger value="gitlab" className="text-xs">GitLab</TabsTrigger>
          </TabsList>

          <TabsContent value="github" className="space-y-3 mt-0">
            <div className="space-y-1.5">
              <Label className="text-xs">Personal Access Token</Label>
              <div className="relative">
                <Input
                  type={ghShowToken ? "text" : "password"}
                  placeholder={ghTokenPlaceholder}
                  value={ghToken}
                  onChange={(e) => setGhToken(e.target.value)}
                  className="pr-8 text-xs h-8"
                />
                <button
                  type="button"
                  className="absolute right-2 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground"
                  onClick={() => setGhShowToken((v) => !v)}
                >
                  {ghShowToken ? <EyeOff className="size-3.5" /> : <Eye className="size-3.5" />}
                </button>
              </div>
              <p className="text-xs text-muted-foreground">Needs <code>repo</code> scope for private repos, <code>public_repo</code> for public only.</p>
            </div>
            <div className="space-y-1.5">
              <Label className="text-xs">Username / Org (optional)</Label>
              <Input
                placeholder="e.g. octocat or my-org"
                value={ghUsername}
                onChange={(e) => setGhUsername(e.target.value)}
                className="text-xs h-8"
              />
            </div>
            <Button size="sm" className="gap-1.5" onClick={handleSaveGitHub} disabled={ghSaving}>
              <Save className="size-3.5" />
              {ghSaving ? "Saving..." : "Save"}
            </Button>
          </TabsContent>

          <TabsContent value="gitlab" className="space-y-3 mt-0">
            <div className="space-y-1.5">
              <Label className="text-xs">Personal Access Token</Label>
              <div className="relative">
                <Input
                  type={glShowToken ? "text" : "password"}
                  placeholder={glTokenPlaceholder}
                  value={glToken}
                  onChange={(e) => setGlToken(e.target.value)}
                  className="pr-8 text-xs h-8"
                />
                <button
                  type="button"
                  className="absolute right-2 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground"
                  onClick={() => setGlShowToken((v) => !v)}
                >
                  {glShowToken ? <EyeOff className="size-3.5" /> : <Eye className="size-3.5" />}
                </button>
              </div>
              <p className="text-xs text-muted-foreground">Needs <code>read_api</code> + <code>read_repository</code> scope.</p>
            </div>
            <div className="space-y-1.5">
              <Label className="text-xs">GitLab URL</Label>
              <Input
                placeholder="https://gitlab.com"
                value={glUrl}
                onChange={(e) => setGlUrl(e.target.value)}
                className="text-xs h-8"
              />
            </div>
            <div className="space-y-1.5">
              <Label className="text-xs">Username (optional)</Label>
              <Input
                placeholder="e.g. johndoe"
                value={glUsername}
                onChange={(e) => setGlUsername(e.target.value)}
                className="text-xs h-8"
              />
            </div>
            <Button size="sm" className="gap-1.5" onClick={handleSaveGitLab} disabled={glSaving}>
              <Save className="size-3.5" />
              {glSaving ? "Saving..." : "Save"}
            </Button>
          </TabsContent>
        </Tabs>
      </CardContent>
    </Card>
  )
}
