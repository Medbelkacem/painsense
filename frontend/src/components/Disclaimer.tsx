import { Notice } from '@/components/ui/feedback'

export const DISCLAIMER =
  'This system is an AI-assisted research and educational prototype. It does not constitute ' +
  'a medical diagnosis and does not replace professional clinical judgement.'

export function Disclaimer({ className }: { className?: string }) {
  return (
    <Notice tone="info" className={className}>
      {DISCLAIMER}
    </Notice>
  )
}
