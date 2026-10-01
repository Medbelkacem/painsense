/**
 * The dropdown family.
 *
 * Three things in this product open a panel under a control and they should feel
 * identical: the filter row on Patients, the account menu in the top bar, and the
 * multi-choice pickers on Analytics. They share `Popover` below, which owns the parts
 * that are easy to get subtly wrong — dismissal, focus return, flipping upwards when
 * the trigger sits near the bottom of a long table, and roving keyboard focus.
 */
import React, {
  useCallback,
  useEffect,
  useId,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
} from 'react';
import { Check, ChevronDown, Search, X } from 'lucide-react';
import { cx } from '../lib/cx';

type Align = 'start' | 'end';

interface PopoverProps {
  open: boolean;
  onClose: () => void;
  align?: Align;
  /** Match the trigger's width — right for selects, wrong for a wide account menu. */
  matchWidth?: boolean;
  className?: string;
  children: React.ReactNode;
}

/**
 * The panel itself. It is rendered inside the trigger's wrapper rather than a portal:
 * every dropdown here sits in normal page flow, and staying in the DOM subtree keeps
 * focus and screen-reader order intact without a focus-trap.
 */
const Popover: React.FC<PopoverProps> = ({
  open,
  onClose,
  align = 'start',
  matchWidth = false,
  className,
  children,
}) => {
  const panel = useRef<HTMLDivElement>(null);
  const [dropUp, setDropUp] = useState(false);

  // Measured after layout but before paint, so a panel that has to flip never shows
  // itself in the wrong place for a frame.
  useLayoutEffect(() => {
    if (!open || !panel.current) return;
    const rect = panel.current.getBoundingClientRect();
    const below = window.innerHeight - rect.top;
    setDropUp(rect.height > below - 12 && rect.top > rect.height);
  }, [open]);

  useEffect(() => {
    if (!open) return;
    const onPointerDown = (event: PointerEvent) => {
      const node = panel.current?.parentElement;
      if (node && !node.contains(event.target as Node)) onClose();
    };
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        event.stopPropagation();
        onClose();
      }
    };
    // Capture, so a click on another dropdown's trigger closes this one first.
    document.addEventListener('pointerdown', onPointerDown, true);
    document.addEventListener('keydown', onKeyDown);
    return () => {
      document.removeEventListener('pointerdown', onPointerDown, true);
      document.removeEventListener('keydown', onKeyDown);
    };
  }, [open, onClose]);

  if (!open) return null;

  return (
    <div
      ref={panel}
      className={cx(
        'absolute z-50 rounded-xl border border-hairline bg-surface p-1.5 shadow-pop',
        'origin-top animate-[ps-pop_120ms_ease-out]',
        dropUp ? 'bottom-full mb-1.5' : 'top-full mt-1.5',
        align === 'end' ? 'right-0' : 'left-0',
        matchWidth ? 'min-w-full' : 'min-w-[12rem]',
        className,
      )}
    >
      {children}
    </div>
  );
};

/* -------------------------------------------------------------------------- */
/* Shared trigger                                                              */
/* -------------------------------------------------------------------------- */

interface TriggerProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  open: boolean;
  /** A set filter is tinted, the way the Patients filter row shows its live facets. */
  active?: boolean;
  size?: 'sm' | 'md';
}

export const DropdownTrigger = React.forwardRef<HTMLButtonElement, TriggerProps>(
  ({ open, active = false, size = 'md', className, children, ...rest }, ref) => (
    <button
      ref={ref}
      type="button"
      aria-haspopup="listbox"
      aria-expanded={open}
      className={cx(
        'inline-flex max-w-full items-center gap-1.5 rounded-[10px] border font-medium',
        'transition-colors duration-150 select-none',
        size === 'sm' ? 'h-8 px-2.5 text-xs' : 'h-9 px-3 text-[13px]',
        active
          ? 'border-accent-edge bg-accent-wash text-accent-ink'
          : 'border-hairline bg-surface text-soft hover:border-hairline-strong hover:text-ink',
        open && !active && 'border-hairline-strong text-ink',
        className,
      )}
      {...rest}
    >
      {children}
      <ChevronDown
        className={cx(
          'ml-auto h-3.5 w-3.5 shrink-0 opacity-70 transition-transform duration-200',
          open && 'rotate-180',
        )}
      />
    </button>
  ),
);
DropdownTrigger.displayName = 'DropdownTrigger';

/* -------------------------------------------------------------------------- */
/* Keyboard driving                                                            */
/* -------------------------------------------------------------------------- */

/**
 * Roving focus over the visible rows. Kept here rather than in each component so the
 * account menu and the facet selects answer the arrow keys the same way.
 */
function useRovingIndex(count: number, open: boolean) {
  const [index, setIndex] = useState(0);
  useEffect(() => {
    if (open) setIndex(0);
  }, [open]);
  useEffect(() => {
    if (index > count - 1) setIndex(Math.max(0, count - 1));
  }, [count, index]);

  const onKeyDown = useCallback(
    (event: React.KeyboardEvent, onPick: (at: number) => void, onOpen?: () => void) => {
      switch (event.key) {
        case 'ArrowDown':
          event.preventDefault();
          if (!open) return onOpen?.();
          setIndex((at) => (at + 1) % Math.max(1, count));
          break;
        case 'ArrowUp':
          event.preventDefault();
          if (!open) return onOpen?.();
          setIndex((at) => (at - 1 + count) % Math.max(1, count));
          break;
        case 'Home':
          if (!open) return;
          event.preventDefault();
          setIndex(0);
          break;
        case 'End':
          if (!open) return;
          event.preventDefault();
          setIndex(Math.max(0, count - 1));
          break;
        case 'Enter':
        case ' ':
          if (!open) return onOpen?.();
          event.preventDefault();
          if (count > 0) onPick(index);
          break;
        default:
          break;
      }
    },
    [count, index, open],
  );

  return { index, setIndex, onKeyDown };
}

/* -------------------------------------------------------------------------- */
/* Row                                                                         */
/* -------------------------------------------------------------------------- */

interface RowProps {
  highlighted: boolean;
  selected?: boolean;
  onSelect: () => void;
  onHover: () => void;
  tone?: 'default' | 'danger';
  icon?: React.ReactNode;
  hint?: string;
  children: React.ReactNode;
}

const Row: React.FC<RowProps> = ({
  highlighted,
  selected = false,
  onSelect,
  onHover,
  tone = 'default',
  icon,
  hint,
  children,
}) => (
  <div
    role="option"
    aria-selected={selected}
    tabIndex={-1}
    onPointerMove={onHover}
    // `pointerup` rather than `click`: the trigger closes the panel on pointerdown
    // elsewhere, and a mousedown-drag-release still has to land on the right row.
    onPointerUp={onSelect}
    className={cx(
      'flex h-9 cursor-pointer items-center gap-2.5 rounded-lg px-2.5 text-[13px]',
      tone === 'danger' ? 'text-danger' : 'text-soft',
      highlighted && (tone === 'danger' ? 'bg-danger/10' : 'bg-sunken text-ink'),
      selected && 'font-medium text-ink',
    )}
  >
    {icon && <span className="grid h-4 w-4 shrink-0 place-items-center opacity-80">{icon}</span>}
    <span className="min-w-0 flex-1 truncate">{children}</span>
    {hint && <span className="shrink-0 text-[11px] text-faint">{hint}</span>}
    {selected && <Check className="h-3.5 w-3.5 shrink-0 text-accent" />}
  </div>
);

/* -------------------------------------------------------------------------- */
/* Select — one choice, the shape used across the filter rows                  */
/* -------------------------------------------------------------------------- */

export interface Option<T extends string = string> {
  value: T;
  label: string;
  hint?: string;
  icon?: React.ReactNode;
}

interface SelectProps<T extends string> {
  /** Shown on its own while nothing is picked, then as the "Priority:" prefix. */
  label: string;
  options: readonly Option<T>[];
  value: T | null;
  onChange: (value: T | null) => void;
  /** Adds a filter box once the list is long enough to be worth scanning. */
  searchable?: boolean;
  clearable?: boolean;
  align?: Align;
  size?: 'sm' | 'md';
  className?: string;
}

export function Select<T extends string>({
  label,
  options,
  value,
  onChange,
  searchable = false,
  clearable = true,
  align = 'start',
  size = 'md',
  className,
}: SelectProps<T>) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState('');
  const trigger = useRef<HTMLButtonElement>(null);
  const listId = useId();

  const showSearch = searchable || options.length > 8;
  const visible = useMemo(() => {
    const needle = query.trim().toLowerCase();
    if (!needle) return options;
    return options.filter((option) => option.label.toLowerCase().includes(needle));
  }, [options, query]);

  const { index, setIndex, onKeyDown } = useRovingIndex(visible.length, open);

  const close = useCallback(() => {
    setOpen(false);
    setQuery('');
    trigger.current?.focus();
  }, []);

  const pick = useCallback(
    (at: number) => {
      const option = visible[at];
      if (option) onChange(option.value === value ? null : option.value);
      close();
    },
    [visible, value, onChange, close],
  );

  const selected = options.find((option) => option.value === value) ?? null;

  return (
    <div className={cx('relative', className)}>
      <DropdownTrigger
        ref={trigger}
        open={open}
        active={selected !== null}
        size={size}
        aria-controls={open ? listId : undefined}
        onClick={() => (open ? close() : setOpen(true))}
        onKeyDown={(event) => onKeyDown(event, pick, () => setOpen(true))}
      >
        <span className="truncate">
          {selected ? (
            <>
              <span className="opacity-70">{label}:</span>{' '}
              <span className="font-semibold">{selected.label}</span>
            </>
          ) : (
            label
          )}
        </span>
      </DropdownTrigger>

      <Popover open={open} onClose={close} align={align} className="w-max min-w-[13rem]">
        {showSearch && (
          <div className="mb-1 flex items-center gap-2 border-b border-hairline px-2 pb-1.5">
            <Search className="h-3.5 w-3.5 shrink-0 text-faint" />
            <input
              autoFocus
              value={query}
              onChange={(event) => {
                setQuery(event.target.value);
                setIndex(0);
              }}
              onKeyDown={(event) => onKeyDown(event, pick)}
              placeholder={`Filter ${label.toLowerCase()}…`}
              className="h-7 w-full bg-transparent text-[13px] text-ink outline-none placeholder:text-faint"
            />
          </div>
        )}

        <div role="listbox" id={listId} aria-label={label} className="max-h-64 overflow-y-auto">
          {visible.map((option, at) => (
            <Row
              key={option.value}
              highlighted={at === index}
              selected={option.value === value}
              onHover={() => setIndex(at)}
              onSelect={() => pick(at)}
              icon={option.icon}
              hint={option.hint}
            >
              {option.label}
            </Row>
          ))}
          {visible.length === 0 && (
            <p className="px-2.5 py-3 text-center text-xs text-faint">No match</p>
          )}
        </div>

        {clearable && selected && (
          <>
            <div className="my-1 h-px bg-hairline" />
            <Row
              highlighted={false}
              onHover={() => undefined}
              onSelect={() => {
                onChange(null);
                close();
              }}
              icon={<X className="h-3.5 w-3.5" />}
            >
              Clear {label.toLowerCase()}
            </Row>
          </>
        )}
      </Popover>
    </div>
  );
}

/* -------------------------------------------------------------------------- */
/* MultiSelect — several choices, counted on the trigger                       */
/* -------------------------------------------------------------------------- */

interface MultiSelectProps<T extends string> {
  label: string;
  options: readonly Option<T>[];
  values: readonly T[];
  onChange: (values: T[]) => void;
  align?: Align;
  size?: 'sm' | 'md';
  className?: string;
}

export function MultiSelect<T extends string>({
  label,
  options,
  values,
  onChange,
  align = 'start',
  size = 'md',
  className,
}: MultiSelectProps<T>) {
  const [open, setOpen] = useState(false);
  const trigger = useRef<HTMLButtonElement>(null);
  const { index, setIndex, onKeyDown } = useRovingIndex(options.length, open);

  const close = useCallback(() => {
    setOpen(false);
    trigger.current?.focus();
  }, []);

  // No close on pick: choosing three pain types should not mean reopening twice.
  const toggle = useCallback(
    (at: number) => {
      const option = options[at];
      if (!option) return;
      onChange(
        values.includes(option.value)
          ? values.filter((value) => value !== option.value)
          : [...values, option.value],
      );
    },
    [options, values, onChange],
  );

  const summary =
    values.length === 0
      ? label
      : values.length === 1
        ? (options.find((option) => option.value === values[0])?.label ?? label)
        : `${label} · ${values.length}`;

  return (
    <div className={cx('relative', className)}>
      <DropdownTrigger
        ref={trigger}
        open={open}
        active={values.length > 0}
        size={size}
        onClick={() => (open ? close() : setOpen(true))}
        onKeyDown={(event) => onKeyDown(event, toggle, () => setOpen(true))}
      >
        <span className="truncate font-semibold">{summary}</span>
      </DropdownTrigger>

      <Popover open={open} onClose={close} align={align} className="w-max min-w-[13rem]">
        <div
          role="listbox"
          aria-multiselectable
          aria-label={label}
          className="max-h-64 overflow-y-auto"
        >
          {options.map((option, at) => {
            const checked = values.includes(option.value);
            return (
              <div
                key={option.value}
                role="option"
                aria-selected={checked}
                onPointerMove={() => setIndex(at)}
                onPointerUp={() => toggle(at)}
                className={cx(
                  'flex h-9 cursor-pointer items-center gap-2.5 rounded-lg px-2.5 text-[13px] text-soft',
                  at === index && 'bg-sunken text-ink',
                )}
              >
                <span
                  className={cx(
                    'grid h-4 w-4 shrink-0 place-items-center rounded-[5px] border transition-colors',
                    checked ? 'border-accent bg-accent text-white' : 'border-hairline-strong',
                  )}
                >
                  {checked && <Check className="h-3 w-3" strokeWidth={3} />}
                </span>
                <span className="flex-1 truncate">{option.label}</span>
                {option.hint && <span className="text-[11px] text-faint">{option.hint}</span>}
              </div>
            );
          })}
        </div>

        <div className="mt-1 flex items-center justify-between border-t border-hairline px-2.5 pt-1.5 text-[11px]">
          <button
            type="button"
            onClick={() => onChange(options.map((option) => option.value))}
            className="font-medium text-accent-ink hover:underline"
          >
            Select all
          </button>
          <button
            type="button"
            onClick={() => onChange([])}
            className="font-medium text-mute hover:text-ink"
          >
            Clear
          </button>
        </div>
      </Popover>
    </div>
  );
}

/* -------------------------------------------------------------------------- */
/* Menu — actions rather than values                                           */
/* -------------------------------------------------------------------------- */

export interface MenuEntry {
  label: string;
  icon?: React.ReactNode;
  hint?: string;
  tone?: 'default' | 'danger';
  onSelect: () => void;
}

interface MenuProps {
  /** Rendered as the clickable trigger; gets the open state so it can show a chevron. */
  trigger: (props: { open: boolean; toggle: () => void }) => React.ReactNode;
  /** A `null` entry draws a divider. */
  entries: readonly (MenuEntry | null)[];
  header?: React.ReactNode;
  align?: Align;
  width?: string;
}

export const Menu: React.FC<MenuProps> = ({
  trigger,
  entries,
  header,
  align = 'end',
  width = 'w-60',
}) => {
  const [open, setOpen] = useState(false);
  const actionable = useMemo(
    () => entries.filter((entry): entry is MenuEntry => entry !== null),
    [entries],
  );
  const { index, setIndex, onKeyDown } = useRovingIndex(actionable.length, open);

  const close = useCallback(() => setOpen(false), []);
  const run = useCallback(
    (at: number) => {
      actionable[at]?.onSelect();
      close();
    },
    [actionable, close],
  );

  return (
    <div
      className="relative"
      onKeyDown={(event) => onKeyDown(event, run, () => setOpen(true))}
    >
      {trigger({ open, toggle: () => setOpen((value) => !value) })}
      <Popover open={open} onClose={close} align={align} className={width}>
        {header && <div className="px-2.5 pt-1.5 pb-2">{header}</div>}
        <div role="menu">
          {entries.map((entry, position) => {
            if (entry === null) {
              return <div key={`rule-${position}`} className="my-1 h-px bg-hairline" />;
            }
            const at = actionable.indexOf(entry);
            return (
              <Row
                key={entry.label}
                highlighted={at === index}
                tone={entry.tone}
                icon={entry.icon}
                hint={entry.hint}
                onHover={() => setIndex(at)}
                onSelect={() => run(at)}
              >
                {entry.label}
              </Row>
            );
          })}
        </div>
      </Popover>
    </div>
  );
};
