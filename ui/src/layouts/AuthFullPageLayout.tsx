import type { ReactNode } from "react"

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/shared/components/ui/card"
import assistBackgroundImage from "@/assets/assist-background-image-v2.png"

type AuthFullPageLayoutVariant = "split" | "centered"

type AuthFullPageLayoutProps = {
  title: string
  description: string
  children: ReactNode
  icon?: ReactNode
  variant?: AuthFullPageLayoutVariant
  imageSrc?: string
  imageAlt?: string
}

const DEFAULT_AUTH_IMAGE_SRC = assistBackgroundImage

export default function AuthFullPageLayout({
  title,
  description,
  children,
  icon,
  variant = "centered",
  imageSrc = DEFAULT_AUTH_IMAGE_SRC,
  imageAlt = "Authentication background",
}: AuthFullPageLayoutProps) {
  if (variant === "split") {
    return (
      <div className="bg-background text-foreground min-h-screen grid md:grid-cols-2">
        <div className="bg-muted/20 hidden md:block relative border-r">
          <img src={imageSrc} alt={imageAlt} className="h-full w-full object-cover" />

          <div className="absolute inset-0 bg-background/35 dark:bg-background/55" />
        </div>

        <div className="bg-muted/20 flex items-center justify-center p-6 sm:p-10">
          <Card className="bg-card/95 w-full max-w-md border shadow-lg backdrop-blur-sm">
            <CardHeader>
              <div className="flex justify-center mb-2">{icon}</div>

              <CardTitle className="text-center text-2xl">{title}</CardTitle>

              <CardDescription className="text-center">{description}</CardDescription>
            </CardHeader>

            <CardContent>{children}</CardContent>
          </Card>
        </div>
      </div>
    )
  }

  return (
    <div className="bg-background text-foreground relative min-h-screen flex items-center justify-center overflow-hidden p-6">
      <div className="from-background via-muted/30 to-background absolute inset-0 bg-linear-to-br" />

      <Card className="bg-card/95 relative w-full max-w-lg border shadow-lg backdrop-blur-sm">
        <CardHeader>
          <div className="flex justify-center mb-2">{icon}</div>

          <CardTitle className="text-center text-2xl">{title}</CardTitle>

          <CardDescription className="text-center">{description}</CardDescription>
        </CardHeader>

        <CardContent>{children}</CardContent>
      </Card>
    </div>
  )
}
