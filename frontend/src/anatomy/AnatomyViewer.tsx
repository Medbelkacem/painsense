import { Maximize2, RotateCcw, ZoomIn, ZoomOut } from 'lucide-react'
import { useEffect, useMemo, useRef, useState } from 'react'

import type { AnatomicalSite, AnatomicalStructure, Side, StructureType } from '@/api/types'
import { Checkbox } from '@/components/ui/choice'
import { Notice } from '@/components/ui/feedback'
import { cn } from '@/utils/cn'
import { AnatomyScene, webglAvailable, type PickedSite, type ViewName } from './scene'
import { TISSUE } from './palette'

const VIEWS: { value: ViewName; label: string }[] = [
  { value: 'front', label: 'Front' },
  { value: 'back', label: 'Back' },
  { value: 'left', label: 'Left' },
  { value: 'right', label: 'Right' },
]

const SIDE_WORD: Record<Side, string> = {
  LEFT: 'left',
  RIGHT: 'right',
  BILATERAL: 'both sides',
  MIDLINE: 'midline',
  NOT_APPLICABLE: '',
}

export interface AnatomyViewerHandle {
  focus: (code: string, side: Side) => void
}

/**
 * The 3D model.
 *
 * Owns the canvas and the scene; every clinical decision belongs to the caller, which is
 * handed the structure that was pointed at and decides what to record. The scene is built
 * once per ontology, so selecting and turning layers on and off never rebuilds geometry.
 *
 * There is no keyboard path through a canvas. The structure list beside it is the one that
 * works without a pointer, and it is also what appears when WebGL is unavailable, so
 * neither case leaves a clinician without a way to record a site.
 */
export function AnatomyViewer({
  structures,
  layers,
  sites,
  onPick,
  handleRef,
}: {
  structures: readonly AnatomicalStructure[]
  layers: { code: StructureType; label: string }[]
  sites: readonly AnatomicalSite[]
  onPick: (site: PickedSite) => void
  handleRef?: { current: AnatomyViewerHandle | null }
}) {
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const frameRef = useRef<HTMLDivElement>(null)
  const sceneRef = useRef<AnatomyScene | null>(null)
  const pickRef = useRef(onPick)
  pickRef.current = onPick

  const supported = useMemo(webglAvailable, [])
  const [visible, setVisible] = useState<Set<StructureType>>(() => new Set(['REGION']))
  const [view, setView] = useState<ViewName>('front')
  const [hovered, setHovered] = useState<PickedSite | null>(null)

  const byCode = useMemo(
    () => new Map(structures.map((structure) => [structure.code, structure])),
    [structures],
  )

  useEffect(() => {
    const canvas = canvasRef.current
    const frame = frameRef.current
    if (!supported || !canvas || !frame || !structures.length) return

    const scene = new AnatomyScene({
      canvas,
      structures,
      onPick: (site) => pickRef.current(site),
      onHover: setHovered,
    })
    sceneRef.current = scene
    if (handleRef) handleRef.current = { focus: (code, side) => scene.focus(code, side) }

    const observer = new ResizeObserver(([entry]) => {
      const { width, height } = entry.contentRect
      scene.resize(width, height)
    })
    observer.observe(frame)
    scene.resize(frame.clientWidth, frame.clientHeight)

    return () => {
      observer.disconnect()
      if (handleRef) handleRef.current = null
      sceneRef.current = null
      scene.dispose()
    }
  }, [supported, structures, handleRef])

  useEffect(() => {
    sceneRef.current?.setLayers(visible)
  }, [visible])

  useEffect(() => {
    sceneRef.current?.setSelection(sites)
  }, [sites])

  useEffect(() => {
    sceneRef.current?.setView(view)
  }, [view])

  const toggleLayer = (code: StructureType, on: boolean) =>
    setVisible((current) => {
      const next = new Set(current)
      if (on) next.add(code)
      else next.delete(code)
      // Something has to stay pickable, so the surface comes back if the last layer goes.
      if (!next.size) next.add('REGION')
      return next
    })

  if (!supported) {
    return (
      <Notice tone="caution" title="The 3D model cannot be shown on this device">
        This browser did not provide a WebGL context. Record the site from the structure list
        instead; it stores exactly the same thing.
      </Notice>
    )
  }

  const hoveredStructure = hovered ? byCode.get(hovered.code) : undefined
  const hoveredSide = hovered ? SIDE_WORD[hovered.side] : ''

  return (
    <div className="space-y-2">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div role="radiogroup" aria-label="Viewpoint" className="inline-flex rounded-md border border-line p-0.5">
          {VIEWS.map((option) => (
            <button
              key={option.value}
              type="button"
              role="radio"
              aria-checked={view === option.value}
              onClick={() => setView(option.value)}
              className={cn(
                'rounded px-3 py-1.5 text-[0.8125rem] transition-colors',
                view === option.value
                  ? 'bg-accent text-white'
                  : 'text-body hover:bg-canvas hover:text-ink',
              )}
            >
              {option.label}
            </button>
          ))}
        </div>
        <div className="flex items-center gap-1">
          <IconButton label="Zoom in" onClick={() => sceneRef.current?.zoomBy(0.8)}>
            <ZoomIn aria-hidden className="size-4" />
          </IconButton>
          <IconButton label="Zoom out" onClick={() => sceneRef.current?.zoomBy(1.25)}>
            <ZoomOut aria-hidden className="size-4" />
          </IconButton>
          <IconButton
            label="Reset the view"
            onClick={() => {
              sceneRef.current?.resetView()
              setView('front')
            }}
          >
            <RotateCcw aria-hidden className="size-4" />
          </IconButton>
        </div>
      </div>

      <div
        ref={frameRef}
        className="relative aspect-[3/4] w-full overflow-hidden rounded-md border border-line bg-gradient-to-b from-[#f2f7fa] to-[#e3ebf1]"
      >
        <canvas ref={canvasRef} className="size-full touch-none" aria-hidden />
        <p className="pointer-events-none absolute inset-x-2 bottom-2 truncate rounded bg-surface/85 px-2 py-1 text-center text-xs text-body">
          {hoveredStructure
            ? `${hoveredStructure.label}${hoveredSide ? ` · ${hoveredSide}` : ''}`
            : 'Drag to turn, scroll to zoom, click a structure to record it'}
        </p>
        <span className="pointer-events-none absolute top-2 right-2 inline-flex items-center gap-1 rounded bg-surface/85 px-2 py-1 text-xs text-muted">
          <Maximize2 aria-hidden className="size-3" />
          {view}
        </span>
      </div>

      <fieldset className="rounded-md border border-line px-3 py-2">
        <legend className="px-1 text-xs font-medium tracking-wide text-muted uppercase">
          Layers
        </legend>
        <div className="grid gap-x-4 gap-y-1 sm:grid-cols-2 lg:grid-cols-4">
          {layers.map((layer) => (
            <Checkbox
              key={layer.code}
              checked={visible.has(layer.code)}
              onChange={(on) => toggleLayer(layer.code, on)}
              label={
                <span className="inline-flex items-center gap-1.5">
                  <span
                    aria-hidden
                    className="size-2.5 shrink-0 rounded-full border border-line-strong"
                    style={{ background: TISSUE[layer.code] }}
                  />
                  {layer.label}
                </span>
              }
            />
          ))}
        </div>
      </fieldset>
    </div>
  )
}

function IconButton({
  label,
  onClick,
  children,
}: {
  label: string
  onClick: () => void
  children: React.ReactNode
}) {
  return (
    <button
      type="button"
      aria-label={label}
      title={label}
      onClick={onClick}
      className="inline-flex size-8 items-center justify-center rounded-md border border-line bg-surface text-body transition-colors hover:bg-canvas hover:text-ink"
    >
      {children}
    </button>
  )
}
