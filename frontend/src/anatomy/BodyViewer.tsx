import React, { useEffect, useMemo, useRef, useState } from 'react';
import { RotateCcw, ZoomIn, ZoomOut } from 'lucide-react';

import type { AnatomicalStructure, AnatomicalStructureTypeInfo, Side, StructureType } from '../api/types';
import { IconButton } from '../ui/Button';
import { Segmented } from '../ui/Segmented';
import { cx } from '../lib/cx';
import { TISSUE } from './palette';
import { AnatomyScene, webglAvailable, type PickedSite, type ViewName } from './scene';

export type BodyMode = 'outside' | 'inside';

const MODES = [
  { value: 'outside', label: 'Outside' },
  { value: 'inside', label: 'Inside' },
] as const;

const VIEWS = [
  { value: 'front', label: 'Front' },
  { value: 'back', label: 'Back' },
  { value: 'left', label: 'Left' },
  { value: 'right', label: 'Right' },
] as const;

const SIDE_WORD: Record<Side, string> = {
  LEFT: 'left',
  RIGHT: 'right',
  BILATERAL: 'both sides',
  MIDLINE: 'midline',
  NOT_APPLICABLE: '',
};

/** What is on when the body is first opened up: enough to orient, not the whole catalogue. */
const FIRST_LOOK_INSIDE: StructureType[] = ['BONE', 'ORGAN'];

export interface BodyViewerHandle {
  /** Turns the model to show a structure, opening the body if the structure is under the skin. */
  focus: (code: string, side: Side, type: StructureType) => void;
}

interface BodyViewerProps {
  structures: readonly AnatomicalStructure[];
  types: readonly AnatomicalStructureTypeInfo[];
  selected: PickedSite | null;
  onPick: (site: PickedSite) => void;
  handleRef?: React.MutableRefObject<BodyViewerHandle | null>;
}

/**
 * The 3D figure with its controls.
 *
 * "Outside" is the skin alone, solid. "Inside" turns the skin into a shell and shows the
 * layers under it, each of which can be switched on its own. The scene is built once per
 * ontology; switching layers or picking never rebuilds geometry.
 */
export const BodyViewer: React.FC<BodyViewerProps> = ({
  structures,
  types,
  selected,
  onPick,
  handleRef,
}) => {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const frameRef = useRef<HTMLDivElement>(null);
  const sceneRef = useRef<AnatomyScene | null>(null);
  const pickRef = useRef(onPick);
  pickRef.current = onPick;

  const supported = useMemo(webglAvailable, []);
  const [mode, setMode] = useState<BodyMode>('outside');
  const [inner, setInner] = useState<Set<StructureType>>(() => new Set(FIRST_LOOK_INSIDE));
  const [view, setView] = useState<ViewName>('front');
  const [hovered, setHovered] = useState<PickedSite | null>(null);

  const byCode = useMemo(
    () => new Map(structures.map((structure) => [structure.code, structure])),
    [structures],
  );

  // Only layers the model actually draws something for. Ligaments are in the ontology but
  // not in the figure, and an empty layer toggle would look broken.
  const innerLayers = useMemo(() => {
    const drawn = new Set(structures.filter((s) => s.has_mesh).map((s) => s.structure_type));
    return [...types]
      .sort((a, b) => a.display_order - b.display_order)
      .filter((type) => type.code !== 'REGION' && drawn.has(type.code));
  }, [structures, types]);

  const visible = useMemo<StructureType[]>(
    () => (mode === 'outside' ? ['REGION'] : ['REGION', ...inner]),
    [mode, inner],
  );
  const visibleRef = useRef(visible);
  visibleRef.current = visible;

  useEffect(() => {
    const canvas = canvasRef.current;
    const frame = frameRef.current;
    if (!supported || !canvas || !frame || !structures.length) return;

    const scene = new AnatomyScene({
      canvas,
      structures,
      onPick: (site) => pickRef.current(site),
      onHover: setHovered,
    });
    sceneRef.current = scene;
    scene.setLayers(visibleRef.current);

    const observer = new ResizeObserver(([entry]) => {
      const { width, height } = entry.contentRect;
      scene.resize(width, height);
    });
    observer.observe(frame);
    scene.resize(frame.clientWidth, frame.clientHeight);

    return () => {
      observer.disconnect();
      sceneRef.current = null;
      scene.dispose();
    };
  }, [supported, structures]);

  useEffect(() => {
    if (!handleRef) return;
    handleRef.current = {
      focus: (code, side, type) => {
        if (type !== 'REGION') {
          setMode('inside');
          setInner((current) => (current.has(type) ? current : new Set(current).add(type)));
        }
        const turned = sceneRef.current?.focus(code, side);
        if (turned) setView(turned);
      },
    };
    return () => {
      handleRef.current = null;
    };
  }, [handleRef]);

  useEffect(() => {
    sceneRef.current?.setLayers(visible);
  }, [visible]);

  useEffect(() => {
    sceneRef.current?.setSelected(selected);
  }, [selected]);

  useEffect(() => {
    sceneRef.current?.setView(view);
  }, [view]);

  const toggleInner = (code: StructureType) =>
    setInner((current) => {
      const next = new Set(current);
      if (next.has(code)) next.delete(code);
      else next.add(code);
      // Inside with nothing under the skin is just a see-through shell with nothing in it.
      if (!next.size) next.add('ORGAN');
      return next;
    });

  if (!supported) {
    return (
      <div className="rounded-[10px] border border-warn/25 bg-warn/10 p-4 text-xs text-warn">
        <p className="font-semibold">The 3D model cannot be shown on this device.</p>
        <p className="mt-1 opacity-80">
          This browser did not provide a WebGL context. The structure list beside it covers
          the same anatomy.
        </p>
      </div>
    );
  }

  const hoveredStructure = hovered ? byCode.get(hovered.code) : undefined;
  const hoveredSide = hovered ? SIDE_WORD[hovered.side] : '';

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex flex-wrap items-center gap-2">
          <Segmented options={MODES} value={mode} onChange={setMode} />
          <Segmented options={VIEWS} value={view} onChange={setView} />
        </div>
        <div className="flex items-center gap-1">
          <IconButton label="Zoom in" onClick={() => sceneRef.current?.zoomBy(0.8)}>
            <ZoomIn className="h-4 w-4" />
          </IconButton>
          <IconButton label="Zoom out" onClick={() => sceneRef.current?.zoomBy(1.25)}>
            <ZoomOut className="h-4 w-4" />
          </IconButton>
          <IconButton
            label="Reset the view"
            onClick={() => {
              sceneRef.current?.resetView();
              setView('front');
            }}
          >
            <RotateCcw className="h-4 w-4" />
          </IconButton>
        </div>
      </div>

      {/* The stage is dark in both themes: a pale figure needs something to stand against,
          and a skin tone on a white card reads as a sticker. */}
      <div
        ref={frameRef}
        className="relative h-[600px] w-full overflow-hidden rounded-[10px] border border-hairline bg-[radial-gradient(ellipse_at_50%_35%,#1b2a44_0%,#0f172a_55%,#060b14_100%)]"
      >
        <canvas ref={canvasRef} className="h-full w-full touch-none" aria-hidden />
        <p className="pointer-events-none absolute inset-x-3 bottom-3 truncate rounded-lg border border-white/10 bg-[#0d1829]/85 px-3 py-1.5 text-center text-xs text-[#a9bad4] backdrop-blur">
          {hoveredStructure
            ? `${hoveredStructure.label}${hoveredSide ? ` · ${hoveredSide}` : ''}`
            : mode === 'outside'
              ? 'Drag to turn, scroll to zoom, click a zone to name it'
              : 'The skin is see-through: click anything inside to name it'}
        </p>
        <span className="pointer-events-none absolute top-3 left-3 rounded-md bg-[#0d1829]/70 px-2 py-1 text-[10px] font-semibold tracking-[0.14em] text-[#8295b2] uppercase">
          {mode === 'outside' ? 'Surface' : 'Interior'} · {view}
        </span>
        <span className="pointer-events-none absolute top-3 right-3 rounded-md bg-[#0d1829]/70 px-2 py-1 text-[10px] text-[#65789a]">
          Patient's left is on your right
        </span>
      </div>

      {mode === 'inside' && (
        <div className="flex flex-wrap items-center gap-1.5">
          <span className="eyebrow mr-1">Layers</span>
          {innerLayers.map((layer) => {
            const on = inner.has(layer.code);
            return (
              <button
                key={layer.code}
                type="button"
                role="checkbox"
                aria-checked={on}
                onClick={() => toggleInner(layer.code)}
                className={cx(
                  'inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs font-medium transition-colors',
                  on
                    ? 'border-hairline-strong bg-sunken text-ink'
                    : 'border-hairline text-faint hover:text-soft',
                )}
              >
                <span
                  aria-hidden
                  className={cx('h-2.5 w-2.5 rounded-full', !on && 'opacity-40')}
                  style={{ background: TISSUE[layer.code] }}
                />
                {layer.label}
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
};
