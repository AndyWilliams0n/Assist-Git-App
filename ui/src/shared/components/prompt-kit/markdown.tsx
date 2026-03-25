import { cn } from "@/shared/utils/utils.ts"
import { memo } from "react"
import ReactMarkdown from "react-markdown"
import type { Components } from "react-markdown"
import remarkBreaks from "remark-breaks"
import remarkGfm from "remark-gfm"
import { CodeBlock, CodeBlockCode } from "./code-block.tsx"

export type MarkdownProps = {
  children: string
  className?: string
  components?: Partial<Components>
}

const normalizeMarkdownInput = (value: string) => {
  const withNormalizedLineEndings = value.replace(/\r\n/g, "\n")

  if (!withNormalizedLineEndings.includes("\n") && withNormalizedLineEndings.includes("\\n")) {
    return withNormalizedLineEndings.replace(/\\n/g, "\n")
  }

  return withNormalizedLineEndings
}

function extractLanguage(className?: string): string {
  if (!className) return "plaintext"
  const match = className.match(/language-(\w+)/)
  return match ? match[1] : "plaintext"
}

const INITIAL_COMPONENTS: Partial<Components> = {
  code: function CodeComponent({ className, children, ...props }) {
    const isInline =
      !props.node?.position?.start.line ||
      props.node?.position?.start.line === props.node?.position?.end.line

    if (isInline) {
      return (
        <span
          className={cn(
            "bg-primary-foreground rounded-sm px-1 font-mono text-sm",
            className
          )}
          {...props}
        >
          {children}
        </span>
      )
    }

    const language = extractLanguage(className)

    return (
      <CodeBlock className={className}>
        <CodeBlockCode code={children as string} language={language} />
      </CodeBlock>
    )
  },
  pre: function PreComponent({ children }) {
    return <>{children}</>
  },
}

function MarkdownComponent({
  children,
  className,
  components = INITIAL_COMPONENTS,
}: MarkdownProps) {
  const normalizedContent = normalizeMarkdownInput(children)

  return (
    <div className={className}>
      <ReactMarkdown
        remarkPlugins={[remarkGfm, remarkBreaks]}
        components={components}
      >
        {normalizedContent}
      </ReactMarkdown>
    </div>
  )
}

const Markdown = memo(MarkdownComponent)
Markdown.displayName = "Markdown"

export { Markdown }
