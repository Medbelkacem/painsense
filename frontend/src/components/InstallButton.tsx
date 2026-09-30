import { Check, Download } from 'lucide-react'
import { useState } from 'react'

import { Button } from '@/components/ui/button'
import { useInstallPrompt } from '@/hooks/useInstallPrompt'

/**
 * Installs the application on the device.
 *
 * The browser decides whether an install is offered at all, so the button only appears
 * once it has said so. Safari never fires that event, which is why the fallback explains
 * the manual route instead of showing a button that would do nothing.
 */
export function InstallButton({
  variant = 'secondary',
  className,
}: {
  variant?: 'primary' | 'secondary'
  className?: string
}) {
  const { installable, installed, install } = useInstallPrompt()
  const [dismissed, setDismissed] = useState(false)

  if (installed) {
    return (
      <span className="inline-flex items-center gap-1.5 text-[0.8125rem] text-positive">
        <Check aria-hidden className="size-4" />
        Installed on this device
      </span>
    )
  }

  if (!installable) {
    return (
      <span className={className}>
        <span className="text-[0.8125rem] text-muted">
          To install, use your browser menu and choose &ldquo;Add to home screen&rdquo;.
        </span>
      </span>
    )
  }

  return (
    <Button
      variant={variant}
      className={className}
      onClick={async () => {
        const outcome = await install()
        if (outcome === 'dismissed') setDismissed(true)
      }}
    >
      <Download aria-hidden className="size-4" />
      {dismissed ? 'Install anyway' : 'Install the app'}
    </Button>
  )
}
