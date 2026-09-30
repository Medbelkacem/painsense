import { PageHeader } from '@/components/PageHeader'
import { LinkButton } from '@/components/ui/button'
import { EmptyState } from '@/components/ui/feedback'

export function NotFoundPage() {
  return (
    <>
      <PageHeader title="Page not found" />
      <EmptyState
        title="That page does not exist"
        description="The address may have changed, or the record may have been removed."
        action={<LinkButton to="/dashboard">Back to the dashboard</LinkButton>}
      />
    </>
  )
}
