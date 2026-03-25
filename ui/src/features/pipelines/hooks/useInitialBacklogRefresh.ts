import { useEffect, useState } from "react"

type UseInitialBacklogRefreshArgs = {
  isLoading: boolean
  backlogLength: number
  refreshBacklog: () => Promise<void>
}

export const useInitialBacklogRefresh = ({
  isLoading,
  backlogLength,
  refreshBacklog,
}: UseInitialBacklogRefreshArgs) => {
  const [didInitialBacklogRefresh, setDidInitialBacklogRefresh] = useState(false)

  useEffect(() => {
    if (isLoading || didInitialBacklogRefresh) return
    if (backlogLength > 0) return

    setDidInitialBacklogRefresh(true)
    void refreshBacklog()
  }, [backlogLength, didInitialBacklogRefresh, isLoading, refreshBacklog])
}
