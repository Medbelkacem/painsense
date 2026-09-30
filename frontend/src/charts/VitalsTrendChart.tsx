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

const SERIES = [
  { key: 'hr', name: 'Heart rate', colour: '#b45309' },
  { key: 'resp_rate', name: 'Respiratory rate', colour: '#0f766e' },
  { key: 'sbp', name: 'Systolic pressure', colour: '#0e7490' },
  { key: 'spo2', name: 'Oxygen saturation', colour: '#7c3aed' },
] as const

export function VitalsTrendChart({ points }: { points: HistoryPoint[] }) {
  const data = points.map((point) => ({
    date: formatDate(point.created_at),
    hr: point.hr,
    resp_rate: point.resp_rate,
    sbp: point.sbp,
    spo2: point.spo2,
  }))

  return (
    <ResponsiveContainer width="100%" height={240}>
      <LineChart data={data} margin={{ top: 8, right: 12, bottom: 4, left: -18 }}>
        <CartesianGrid stroke="#eef3f7" vertical={false} />
        <XAxis dataKey="date" tick={AXIS} tickLine={false} axisLine={{ stroke: '#dde6ed' }} />
        <YAxis tick={AXIS} tickLine={false} axisLine={false} />
        <Tooltip
          contentStyle={{ borderRadius: 8, border: '1px solid #dde6ed', fontSize: 12 }}
        />
        <Legend wrapperStyle={{ fontSize: 12, paddingTop: 4 }} />
        {SERIES.map((series) => (
          <Line
            key={series.key}
            type="monotone"
            dataKey={series.key}
            name={series.name}
            stroke={series.colour}
            strokeWidth={1.6}
            dot={{ r: 2.5 }}
            connectNulls
            isAnimationActive={false}
          />
        ))}
      </LineChart>
    </ResponsiveContainer>
  )
}
