import { useState } from 'react'

import { useActivateModel, useModelStatus, useTrainModel } from '@/api/queries'
import { useAuth } from '@/auth/AuthProvider'
import { PageHeader } from '@/components/PageHeader'
import { StatTile } from '@/components/StatTile'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardBody, CardHeader } from '@/components/ui/card'
import { Notice, QueryState } from '@/components/ui/feedback'
import { Td, TableWrap, Th, Tr } from '@/components/ui/table'
import { formatDateTime } from '@/utils/format'

export function ModelPage() {
  const { user } = useAuth()
  const status = useModelStatus()
  const train = useTrainModel()
  const activate = useActivateModel()
  const [showFeatures, setShowFeatures] = useState(false)
  const isAdmin = user?.role === 'ADMIN'

  return (
    <>
      <PageHeader
        title="Estimation model"
        description="Every figure here was measured on held-out data. Nothing is asserted that was not."
        actions={
          isAdmin && (
            <Button
              loading={train.isPending}
              onClick={() => train.mutate({ test_size: 0.2, seed: 0, cv_folds: 5 })}
            >
              Train on the latest dataset
            </Button>
          )
        }
      />

      <QueryState isPending={status.isPending} error={status.error}>
        {status.data && (
          <>
            {!status.data.trained && (
              <Notice tone="caution" title="No model has been trained">
                The estimate endpoint refuses rather than returning a number.
                {isAdmin
                  ? ' Generate a dataset, then train.'
                  : ' An administrator has to train one.'}
              </Notice>
            )}

            {train.isError && (
              <Notice tone="alert" title="Training did not run">
                {train.error instanceof Error ? train.error.message : 'Unexpected error'}
              </Notice>
            )}

            {status.data.active && (
              <>
                <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
                  <StatTile
                    label="MAE"
                    value={status.data.active.mae}
                    hint="Mean absolute error, points of the 0-10 scale"
                  />
                  <StatTile label="RMSE" value={status.data.active.rmse} />
                  <StatTile label="R squared" value={status.data.active.r2} />
                  <StatTile label="Pearson r" value={status.data.active.pearson} />
                </div>

                <Card>
                  <CardHeader
                    title={status.data.active.version}
                    description={`${status.data.active.algorithm}. Trained ${formatDateTime(
                      status.data.active.trained_at,
                    )}.`}
                    actions={<Badge tone="positive">Active</Badge>}
                  />
                  <CardBody className="space-y-4">
                    <dl className="grid gap-x-6 gap-y-3 text-[0.8125rem] sm:grid-cols-2 lg:grid-cols-3">
                      <Entry term="Training data" value={status.data.active.dataset_version} />
                      <Entry
                        term="Split"
                        value={`${status.data.active.n_train} train, ${status.data.active.n_test} held out`}
                      />
                      <Entry
                        term="Cross-validated MAE"
                        value={`${status.data.active.cv_mae_mean} (sd ${status.data.active.cv_mae_sd}, ${status.data.active.cv_folds} folds)`}
                      />
                      <Entry term="Residual sd" value={String(status.data.active.residual_sd)} />
                      <Entry term="Features" value={`${status.data.feature_count}`} />
                      <Entry term="Target" value="Patient-reported 0-10 score" />
                    </dl>
                    <p className="text-[0.8125rem] leading-relaxed text-body">
                      {status.data.active.notes}
                    </p>
                  </CardBody>
                </Card>
              </>
            )}

            <div className="grid gap-4 lg:grid-cols-2">
              <Card>
                <CardHeader
                  title="Never used as an input"
                  description="Kept out of the feature vector by construction, not by convention."
                />
                <CardBody>
                  <ul className="space-y-2 text-[0.8125rem] text-body">
                    {status.data.excluded_from_features.map((item) => (
                      <li key={item} className="flex gap-2">
                        <span aria-hidden className="text-alert">
                          &times;
                        </span>
                        {item}
                      </li>
                    ))}
                  </ul>
                </CardBody>
              </Card>

              <Card>
                <CardHeader title="Limitations" />
                <CardBody>
                  <ul className="space-y-2 text-[0.8125rem] leading-relaxed text-body">
                    {status.data.limitations.map((item) => (
                      <li key={item} className="border-l-2 border-caution/40 pl-3">
                        {item}
                      </li>
                    ))}
                  </ul>
                </CardBody>
              </Card>
            </div>

            {status.data.active && (
              <Card>
                <CardHeader
                  title="Features"
                  description={`${status.data.feature_count} inputs, in the order the model reads them.`}
                  actions={
                    <Button
                      size="sm"
                      variant="ghost"
                      onClick={() => setShowFeatures((value) => !value)}
                    >
                      {showFeatures ? 'Hide' : 'Show'}
                    </Button>
                  }
                />
                {showFeatures && (
                  <CardBody>
                    <div className="flex flex-wrap gap-1.5">
                      {status.data.active.features.map((feature) => (
                        <span
                          key={feature}
                          className="rounded bg-canvas px-2 py-0.5 font-mono text-[0.6875rem] text-body"
                        >
                          {feature}
                        </span>
                      ))}
                    </div>
                  </CardBody>
                )}
              </Card>
            )}

            {status.data.versions.length > 1 && (
              <Card>
                <CardHeader title="Trained versions" />
                <TableWrap>
                  <thead>
                    <tr>
                      <Th>Version</Th>
                      <Th>Trained</Th>
                      <Th align="right">MAE</Th>
                      <Th align="right">RMSE</Th>
                      <Th align="right">R squared</Th>
                      <Th>State</Th>
                    </tr>
                  </thead>
                  <tbody>
                    {status.data.versions.map((version) => (
                      <Tr key={version.version}>
                        <Td className="font-mono text-xs">{version.version}</Td>
                        <Td className="text-muted">{formatDateTime(version.trained_at)}</Td>
                        <Td align="right">{version.mae}</Td>
                        <Td align="right">{version.rmse}</Td>
                        <Td align="right">{version.r2}</Td>
                        <Td>
                          {version.is_active ? (
                            <Badge tone="positive">Active</Badge>
                          ) : isAdmin ? (
                            <Button
                              size="sm"
                              variant="ghost"
                              loading={activate.isPending}
                              onClick={() => activate.mutate(version.version)}
                            >
                              Activate
                            </Button>
                          ) : (
                            <span className="text-muted">—</span>
                          )}
                        </Td>
                      </Tr>
                    ))}
                  </tbody>
                </TableWrap>
              </Card>
            )}
          </>
        )}
      </QueryState>
    </>
  )
}

function Entry({ term, value }: { term: string; value: string }) {
  return (
    <div>
      <dt className="text-muted">{term}</dt>
      <dd className="font-medium text-ink">{value}</dd>
    </div>
  )
}
