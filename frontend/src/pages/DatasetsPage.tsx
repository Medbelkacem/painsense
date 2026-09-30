import { useState } from 'react'

import { useDatasets, useGenerateDataset } from '@/api/queries'
import { useAuth } from '@/auth/AuthProvider'
import { DistributionBar } from '@/charts/DistributionBar'
import { PageHeader } from '@/components/PageHeader'
import { StatTile } from '@/components/StatTile'
import { Button } from '@/components/ui/button'
import { Card, CardBody, CardHeader } from '@/components/ui/card'
import { Field, Input } from '@/components/ui/field'
import { EmptyState, Notice, QueryState } from '@/components/ui/feedback'
import { formatDateTime, humanise } from '@/utils/format'

export function DatasetsPage() {
  const { user } = useAuth()
  const datasets = useDatasets()
  const generate = useGenerateDataset()
  const [rows, setRows] = useState(10000)
  const [seed, setSeed] = useState(42)
  const isAdmin = user?.role === 'ADMIN'
  const latest = datasets.data?.[0]

  return (
    <>
      <PageHeader
        title="Datasets"
        description="The data the estimator is trained on. All of it is generated."
      />

      <Notice tone="caution" title="Synthetic data">
        No record in any dataset here comes from a person. The generator builds records from
        clinical archetypes so the structure is realistic, and the files make no claim to represent
        any real population.
      </Notice>

      {isAdmin && (
        <Card>
          <CardHeader
            title="Generate a dataset"
            description="Reproducible: the same seed and row count produce the same file."
          />
          <CardBody>
            <div className="flex flex-wrap items-end gap-3">
              <Field label="Rows" className="w-32">
                {(props) => (
                  <Input
                    {...props}
                    type="number"
                    min={100}
                    max={200000}
                    value={rows}
                    onChange={(event) => setRows(Number(event.target.value))}
                  />
                )}
              </Field>
              <Field label="Seed" className="w-32">
                {(props) => (
                  <Input
                    {...props}
                    type="number"
                    min={0}
                    value={seed}
                    onChange={(event) => setSeed(Number(event.target.value))}
                  />
                )}
              </Field>
              <Button
                loading={generate.isPending}
                onClick={() => generate.mutate({ rows, seed })}
                className="mb-0.5"
              >
                Generate
              </Button>
            </div>
            {generate.isError && (
              <Notice tone="alert" className="mt-3">
                {generate.error instanceof Error ? generate.error.message : 'Unexpected error'}
              </Notice>
            )}
          </CardBody>
        </Card>
      )}

      <QueryState
        isPending={datasets.isPending}
        error={datasets.error}
        isEmpty={!datasets.data?.length}
        empty={
          <EmptyState
            title="No dataset has been generated"
            description="The model cannot be trained until one exists."
          />
        }
      >
        {latest && (
          <>
            <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
              <StatTile label="Rows" value={latest.n_rows.toLocaleString('en-GB')} />
              <StatTile label="Seed" value={latest.seed} />
              <StatTile
                label="Mean self-report"
                value={latest.distribution.self_report_mean ?? '—'}
                hint={`sd ${latest.distribution.self_report_sd ?? '—'}`}
              />
              <StatTile
                label="Presentations"
                value={Object.keys(latest.distribution.archetypes ?? {}).length}
              />
            </div>

            <Card>
              <CardHeader
                title={latest.version}
                description={`Generated ${formatDateTime(latest.generated_at)} · ${latest.path}`}
              />
            </Card>

            <div className="grid gap-4 lg:grid-cols-2">
              <Card>
                <CardHeader
                  title="Self-reported score"
                  description="The training reference, which is never a model input."
                />
                <CardBody>
                  <DistributionBar
                    layout="horizontal"
                    data={Object.entries(latest.distribution.self_report_histogram ?? {}).map(
                      ([score, count]) => ({ name: score, value: count }),
                    )}
                  />
                </CardBody>
              </Card>
              <Card>
                <CardHeader title="Presentations drawn" />
                <CardBody>
                  <DistributionBar
                    height={420}
                    data={Object.entries(latest.distribution.archetypes ?? {}).map(
                      ([name, count]) => ({ name: humanise(name), value: count }),
                    )}
                  />
                </CardBody>
              </Card>
              <Card>
                <CardHeader title="Sites by region" />
                <CardBody>
                  <DistributionBar
                    data={Object.entries(latest.distribution.regions ?? {}).map(([name, count]) => ({
                      name: humanise(name),
                      value: count,
                    }))}
                  />
                </CardBody>
              </Card>
              <Card>
                <CardHeader
                  title="Measurements present"
                  description="Values are dropped at generation time, because real records are incomplete."
                />
                <CardBody>
                  <DistributionBar
                    data={Object.entries(latest.distribution.vitals_recorded ?? {}).map(
                      ([name, count]) => ({ name: humanise(name), value: count }),
                    )}
                  />
                </CardBody>
              </Card>
            </div>

            {datasets.data && datasets.data.length > 1 && (
              <Card>
                <CardHeader title="Earlier versions" />
                <CardBody>
                  <ul className="divide-y divide-line text-[0.8125rem]">
                    {datasets.data.slice(1).map((dataset) => (
                      <li key={dataset.version} className="flex justify-between gap-3 py-2">
                        <span className="font-mono text-xs text-body">{dataset.version}</span>
                        <span className="text-muted">
                          {dataset.n_rows.toLocaleString('en-GB')} rows ·{' '}
                          {formatDateTime(dataset.generated_at)}
                        </span>
                      </li>
                    ))}
                  </ul>
                </CardBody>
              </Card>
            )}
          </>
        )}
      </QueryState>
    </>
  )
}
