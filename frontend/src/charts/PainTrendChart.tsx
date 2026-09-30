import {
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'

import type { HistoryPoint } from '@/api/types'
import { formatDate } from '@/utils/format'

const AXIS = { fontSize: 11, fill: '#64798f' }

export function PainTrendChart({ points, height = 240 }: { points: HistoryPoint[]; height?: number }) {
  const data = points.map((point) => ({
    date: formatDate(point.created_at),
    estimate: point.estimated_pain,
    selfReport: point.self_report,
  }))

  return (
    <ResponsiveContainer width="100%" height={height}>
      <LineChart data={data} margin={{ top: 8, right: 12, bottom: 4, left: -18 }}>
        <CartesianGrid stroke="#eef3f7" vertical={false} />
        <XAxis dataKey="date" tick={AXIS} tickLine={false} axisLine={{ stroke: '#dde6ed' }} />
        <YAxis domain={[0, 10]} ticks={[0, 2, 4, 6, 8, 10]} tick={AXIS} tickLine={false} axisLine={false} />
        <Tooltip
          contentStyle={{
            borderRadius: 8,
            border: '1px solid #dde6ed',
            fontSize: 12,
            boxShadow: '0 4px 12px rgb(15 31 46 / 0.08)',
          }}
        />
        <Legend wrapperStyle={{ fontSize: 12, paddingTop: 4 }} />
        <Line
          type="monotone"
          dataKey="estimate"
          name="Estimated pain"
          stroke="#0e7490"
          strokeWidth={2}
          dot={{ r: 3 }}
          connectNulls
          isAnimationActive={false}
        />
        <Line
          type="monotone"
          dataKey="selfReport"
          name="Patient-reported"
          stroke="#64798f"
          strokeWidth={1.5}
          strokeDasharray="4 3"
          dot={{ r: 2.5 }}
          connectNulls
          isAnimationActive={false}
        />
      </LineChart>
    </ResponsiveContainer>
  )
}
