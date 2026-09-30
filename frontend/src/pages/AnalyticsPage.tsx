import { useAnalytics } from '@/api/queries'
import { DistributionBar } from '@/charts/DistributionBar'
import { PainTrendChart } from '@/charts/PainTrendChart'
import { PageHeader } from '@/components/PageHeader'
import { StatTile } from '@/components/StatTile'
import { Card, CardBody, CardHeader } from '@/components/ui/card'
import { EmptyState, QueryState } from '@/components/ui/feedback'
import { formatScore, humanise } from '@/utils/format'

const BAND_COLOURS: Record<string, string> = {
  None: '#0f766e',
  Mild: '#15803d',
  Moderate: '#b45309',
  Severe: '#c2410c',
  Extreme: '#b91c1c',
}

export function AnalyticsPage() {
  const analytics = useAnalytics()

  return (
    <>
      <PageHeader
        title="Analytics"
        description="Aggregates over the records this deployment holds. Synthetic records are included and counted separately."
      />

      <QueryState isPending={analytics.isPending} error={analytics.error}>
        {analytics.data && (
          <>
            <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
              <StatTile label="Patients" value={analytics.data.patients_total} />
              <StatTile label="Assessments" value={analytics.data.assessments_total} />
              <StatTile
                label="Mean estimate"
                value={formatScore(analytics.data.mean_estimated_pain)}
              />
              <StatTile
                label="Mean self-report"
                value={formatScore(analytics.data.mean_self_report)}
              />
            </div>

            <Card>
              <CardHeader
                title="Estimate against the patient's own score"
                description="Mean absolute difference over the assessments that carry both."
              />
              <CardBody className="space-y-2">
                <p className="text-3xl font-semibold text-ink tabular">
                  {formatScore(analytics.data.estimate_vs_self_report_mae, 2)}
                  <span className="ml-1 text-base font-normal text-muted">points</span>
                </p>
                <p className="max-w-2xl text-[0.8125rem] leading-relaxed text-muted">
                  This describes how far the two have diverged in these records. It is not an
                  accuracy figure: the patient&rsquo;s own score is a subjective reference, and a
                  difference does not establish which of the two is closer to the experience.
                </p>
              </CardBody>
            </Card>

            <Card>
              <CardHeader title="Estimated pain over the last 30 days" />
              <CardBody>
                {analytics.data.daily_mean_pain.length > 1 ? (
                  <PainTrendChart
                    points={analytics.data.daily_mean_pain.map((point) => ({
                      assessment_id: point.date,
                      created_at: point.date,
                      estimated_pain: point.mean_pain,
                      self_report: null,
                      priority_score: null,
                      band: null,
                      hr: null,
                      resp_rate: null,
                      sbp: null,
                      dbp: null,
                      spo2: null,
                      temperature_c: null,
                    }))}
                  />
                ) : (
                  <EmptyState title="Not enough estimates yet to draw a trend" />
                )}
              </CardBody>
            </Card>

            <div className="grid gap-4 lg:grid-cols-2">
              <Card>
                <CardHeader
                  title="Estimates by band"
                  description="Bands are for reading the scale, not a classification of the patient."
                />
                <CardBody>
                  <DistributionBar
                    layout="horizontal"
                    colours={BAND_COLOURS}
                    data={Object.entries(analytics.data.band_distribution).map(([band, count]) => ({
                      name: humanise(band),
                      value: count,
                    }))}
                  />
                </CardBody>
              </Card>
              <Card>
                <CardHeader title="Sites recorded, by region" />
                <CardBody>
                  <DistributionBar
                    data={Object.entries(analytics.data.region_distribution).map(
                      ([region, count]) => ({ name: humanise(region), value: count }),
                    )}
                  />
                </CardBody>
              </Card>
            </div>
          </>
        )}
      </QueryState>
    </>
  )
}
