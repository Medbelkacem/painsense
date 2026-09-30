import { Bar, BarChart, CartesianGrid, Cell, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'

const AXIS = { fontSize: 11, fill: '#64798f' }

export function DistributionBar({
  data,
  colours,
  height = 220,
  layout = 'vertical',
}: {
  data: { name: string; value: number }[]
  colours?: Record<string, string>
  height?: number
  layout?: 'vertical' | 'horizontal'
}) {
  const horizontal = layout === 'horizontal'
  return (
    <ResponsiveContainer width="100%" height={height}>
      <BarChart
        data={data}
        layout={horizontal ? 'horizontal' : 'vertical'}
        margin={{ top: 4, right: 16, bottom: 4, left: horizontal ? -18 : 8 }}
      >
        <CartesianGrid stroke="#eef3f7" horizontal={horizontal} vertical={!horizontal} />
        {horizontal ? (
          <>
            <XAxis dataKey="name" tick={AXIS} tickLine={false} axisLine={{ stroke: '#dde6ed' }} />
            <YAxis tick={AXIS} tickLine={false} axisLine={false} allowDecimals={false} />
          </>
        ) : (
          <>
            <XAxis type="number" tick={AXIS} tickLine={false} axisLine={false} allowDecimals={false} />
            <YAxis
              type="category"
              dataKey="name"
              width={130}
              tick={AXIS}
              tickLine={false}
              axisLine={false}
            />
          </>
        )}
        <Tooltip
          cursor={{ fill: '#f2f7fa' }}
          contentStyle={{ borderRadius: 8, border: '1px solid #dde6ed', fontSize: 12 }}
        />
        <Bar dataKey="value" radius={3} maxBarSize={38} isAnimationActive={false}>
          {data.map((entry) => (
            <Cell key={entry.name} fill={colours?.[entry.name] ?? '#0e7490'} />
          ))}
        </Bar>
      </BarChart>
    </ResponsiveContainer>
  )
}
